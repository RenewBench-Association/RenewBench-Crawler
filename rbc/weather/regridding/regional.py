"""REGIONAL.

Compact-cell weight application and coarsening for non-global sources
(BARRA2, ICON-DREAM EU), working around grid-doctor issue #24:
`apply_weight_file()` assumes a full-global target size.
"""

from pathlib import Path

import grid_doctor.remap as _gd_remap
import grid_doctor.remap_apply as _gd_remap_apply
import grid_doctor.select as _gd_select
import numpy as np
import xarray as xr
from scipy.sparse import coo_matrix


def regrid_regional_to_healpix(
    ds: xr.Dataset, weights_path: Path, level: int
) -> xr.Dataset:
    """Regrid a regional source to one compact HEALPix level.

    Works around `apply_weight_file()`'s crash on regional sources: it sizes
    the target dimension as `row.max() + 1` rather than the count of unique
    referenced cells, leaving phantom all-zero rows (on real BARRA2 data only
    ~6% of that nominal size is ever referenced). Keeps grid-doctor's
    dimension resolution and weight application, replacing only the matrix
    construction and coordinate attachment.

    Args:
        ds (xr.Dataset): Source dataset, already renamed to canonical
            variable names.
        weights_path (Path): Path to the cached ESMF weight file for this level.
        level (int): HEALPix level being computed.

    Returns:
        xr.Dataset: Compact HEALPix Dataset at the given level — only cells
            actually covered by the source domain, no phantom/padded cells.
    """
    # Weight-file column names, normalized to grid-doctor's own.
    wds = xr.open_dataset(weights_path)
    row_name = "row" if "row" in wds else "dst_address"
    col_name = "col" if "col" in wds else "src_address"
    val_name = "S" if "S" in wds else "remap_matrix"

    # ESMF's Fortran heritage sometimes leaves these 1-based.
    row0 = wds[row_name].values
    col0 = wds[col_name].values
    if row0.min() >= 1:
        row0 = row0 - 1
    if col0.min() >= 1:
        col0 = col0 - 1
    row0 = row0.astype(np.int64)
    col0 = col0.astype(np.int64)
    vals = wds[val_name].values

    n_source = int(col0.max()) + 1

    # The weight file's own source_dims, for grid-doctor's dimension resolution.
    stored_sd = _gd_remap._parse_source_dims_attr(
        wds.attrs.get("grid_doctor_source_dims")
    )

    # Keep only the rows the weight file references, mapping the original
    # row indices onto a compact set. real_cell_ids is sorted, so
    # searchsorted does that for all millions of entries at once.
    real_cell_ids = np.unique(row0)
    compact_row = np.searchsorted(real_cell_ids, row0)
    matrix = coo_matrix(
        (vals, (compact_row, col0)), shape=(len(real_cell_ids), n_source)
    ).tocsr()

    # Source dims for weight application: the stored attribute if present,
    # otherwise auto-detected.
    resolved_sd = _gd_remap._resolve_source_dims_for_weight_application(
        ds,
        n_source=n_source,
        grid=None,
        source_dims=None,
        source_units="auto",
        stored_source_dims=stored_sd,
    )

    # Core dims consumed by apply_weights_nd must each be a single dask
    # chunk: any target cell can draw from any source cell.
    single_chunk = dict.fromkeys(resolved_sd, -1)

    regridded = {}
    for name, data in ds.data_vars.items():
        if not set(resolved_sd).issubset(map(str, data.dims)):
            regridded[str(name)] = data
            continue
        regridded[str(name)] = xr.apply_ufunc(
            _gd_remap_apply.apply_weights_nd,
            data.chunk(single_chunk),
            input_core_dims=[list(resolved_sd)],
            output_core_dims=[["cell"]],
            exclude_dims=set(resolved_sd),
            dask="parallelized",
            kwargs={
                "matrix": matrix,
                "n_source_dims": len(resolved_sd),
                "missing_policy": "renormalize",
            },
            output_dtypes=[np.float64],
            dask_gufunc_kwargs={"output_sizes": {"cell": len(real_cell_ids)}},
        )

    result = xr.Dataset(regridded, attrs=ds.attrs.copy())
    return _gd_select.attach_cell_coords(result, real_cell_ids, level=level)


def _coarsen_cells(
    block: np.ndarray,
    order: np.ndarray | None,
    starts: np.ndarray,
    divisor: int,
    min_valid_fraction: float,
) -> np.ndarray:
    """Average each parent's children along the last (cell) axis of one block.

    Args:
        block (np.ndarray): Values with "cell" as the last axis.
        order (np.ndarray | None): Permutation grouping each parent's children
            together, or None when they already are.
        starts (np.ndarray): Index where each parent's children begin.
        divisor (int): How many children a parent has (4**delta).
        min_valid_fraction (float): Fraction of those children that must be
            non-NaN for the parent to get a value.

    Returns:
        np.ndarray: Same leading axes, one value per parent.
    """
    if order is not None:
        block = block[..., order]
    valid = ~np.isnan(block)
    sums = np.add.reduceat(np.where(valid, block, 0.0), starts, axis=-1)
    counts = np.add.reduceat(valid, starts, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        means = sums / counts
    return np.where(counts / divisor >= min_valid_fraction, means, np.nan)


def coarsen_regional(
    ds: xr.Dataset, target_level: int, min_valid_fraction: float = 0.5
) -> xr.Dataset:
    """Coarsen a compact (regional) HEALPix dataset to a lower level.

    Groups by cell-ID value, since `grid_doctor.coarsen_healpix()` relies on
    array position encoding parent-child relationships, which holds only for
    a dense full-global array. Cross-validated against its dense output on
    real BARRA2 data: identical cells and values (~1e-13, float noise).

    Args:
        ds (xr.Dataset): Compact HEALPix Dataset with a "cell" dim and
            `healpix_level` attr.
        target_level (int): Target HEALPix level (must be lower than current).
        min_valid_fraction (float): Minimum fraction of a parent's 4
            theoretical children that must be valid (non-NaN) to produce a
            valid parent cell — matches `coarsen_healpix()`'s own default.

    Returns:
        xr.Dataset: Compact HEALPix Dataset coarsened to target_level.

    Raises:
        ValueError: If target_level is not lower than the current level.
    """
    current_level = int(ds.attrs["healpix_level"])
    delta = current_level - target_level
    if delta <= 0:
        raise ValueError(
            f"target_level ({target_level}) must be lower than the current "
            f"level ({current_level})."
        )
    divisor = 4**delta

    parents = ds["cell"].values // divisor
    # reduceat needs each parent's children adjacent; compact cell ids arrive
    # ascending, so the permutation is normally unnecessary.
    order = (
        None if np.all(np.diff(parents) >= 0) else np.argsort(parents, kind="stable")
    )
    unique_parents, starts = np.unique(
        parents if order is None else parents[order], return_index=True
    )

    data_vars = {}
    for name, da in ds.data_vars.items():
        if "cell" not in da.dims:
            data_vars[name] = da
            continue
        data_vars[name] = xr.apply_ufunc(
            _coarsen_cells,
            da,
            input_core_dims=[["cell"]],
            output_core_dims=[["cell"]],
            exclude_dims={"cell"},
            dask="parallelized",
            kwargs={
                "order": order,
                "starts": starts,
                "divisor": divisor,
                "min_valid_fraction": min_valid_fraction,
            },
            output_dtypes=[np.float64],
            dask_gufunc_kwargs={"output_sizes": {"cell": len(unique_parents)}},
        )

    result = xr.Dataset(data_vars, attrs={**ds.attrs, "healpix_level": target_level})
    return _gd_select.attach_cell_coords(result, unique_parents, level=target_level)


def build_regional_healpix_pyramid(
    ds: xr.Dataset, weights_path: Path, max_level: int, min_level: int
) -> dict[int, xr.Dataset]:
    """Build a full compact HEALPix pyramid for a regional source.

    Regrids `ds` directly to `max_level`, then coarsens down to `min_level`
    one level at a time. The regional equivalent of
    `grid_doctor.create_healpix_pyramid()`; every level stays lazy, so
    `HealpixZarrWriter` computes and writes them a block at a time.

    Args:
        ds (xr.Dataset): Source dataset, already renamed to canonical
            variable names.
        weights_path (Path): Path to the cached ESMF weight file for max_level.
        max_level (int): Finest HEALPix level to compute directly.
        min_level (int): Coarsest HEALPix level to retain.

    Returns:
        dict[int, xr.Dataset]: Pyramid keyed by level, max_level down to min_level.
    """
    finest = regrid_regional_to_healpix(ds, weights_path, level=max_level)
    pyramid = {max_level: finest}
    current = finest
    for level in range(max_level - 1, min_level - 1, -1):
        current = coarsen_regional(current, target_level=level)
        pyramid[level] = current
    return pyramid
