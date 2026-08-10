"""REGIONAL.

Workaround for grid-doctor's regional-source coordinate-attachment crash
(grid-doctor issue #24, confirmed still open upstream). Provides a compact-
cell weight-application and coarsening pipeline for non-global sources
(BARRA2, ICON-DREAM EU), bypassing `apply_weight_file()`'s full-global-size
assumption.
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

    Bypasses `apply_weight_file()`'s coordinate-attachment crash on regional
    sources: its weight-file reader sizes the target dimension as
    `row.max() + 1`, not the count of unique referenced cells, leaving mostly
    phantom all-zero rows that `_attach_healpix_coords()` can't handle.
    Confirmed on real BARRA2 data: only ~6% of that nominal size was ever
    actually referenced — the rest are phantom rows that would silently
    produce false zero-valued cells if not filtered out, not just a crash.

    Reuses grid-doctor's own dimension-resolution and `xr.apply_ufunc`
    application (the correct part) — only replaces the matrix construction
    (dropping phantom rows) and the coordinate-attachment step.

    Args:
        ds (xr.Dataset): Source dataset, already renamed to canonical
            variable names.
        weights_path (Path): Path to the cached ESMF weight file for this level.
        level (int): HEALPix level being computed.

    Returns:
        xr.Dataset: Compact HEALPix Dataset at the given level — only cells
            actually covered by the source domain, no phantom/padded cells.
    """
    # Normalize weight-file column names to grid-doctor's expected names
    wds = xr.open_dataset(weights_path)
    row_name = "row" if "row" in wds else "dst_address"
    col_name = "col" if "col" in wds else "src_address"
    val_name = "S" if "S" in wds else "remap_matrix"

    # Convert to 0-based indexing for matrix construction, if needed
    # (sometimes a leftover from ESMF's Fortran heritage)
    row0 = wds[row_name].values
    col0 = wds[col_name].values
    if row0.min() >= 1:
        row0 = row0 - 1
    if col0.min() >= 1:
        col0 = col0 - 1
    row0 = row0.astype(np.int64)
    col0 = col0.astype(np.int64)
    vals = wds[val_name].values

    # Determine the number of source cells (columns) from the weight file.
    n_source = int(col0.max()) + 1

    # read the original source_dims attribute from the weight file, if present,
    # to pass to grid-doctor's dimension resolution function.
    stored_sd = _gd_remap._parse_source_dims_attr(
        wds.attrs.get("grid_doctor_source_dims")
    )

    # This fixes the phantom-row problem in grid-doctor: only keep the rows
    # that are actually referenced in the weight file, and build a mapping
    # from the original row indices to a compacted set of indices.
    real_cell_ids = np.unique(row0)
    id_to_compact = {cid: i for i, cid in enumerate(real_cell_ids)}
    compact_row = np.array([id_to_compact[c] for c in row0], dtype=np.int64)
    matrix = coo_matrix(
        (vals, (compact_row, col0)), shape=(len(real_cell_ids), n_source)
    ).tocsr()

    # Resolve the source dimensions for weight application, using the stored
    # source_dims attribute if present, otherwise falling back to auto-detection.
    resolved_sd = _gd_remap._resolve_source_dims_for_weight_application(
        ds,
        n_source=n_source,
        grid=None,
        source_dims=None,
        source_units="auto",
        stored_source_dims=stored_sd,
    )

    # Core dims consumed by apply_weights_nd must each be a single dask
    # chunk, the spatial extent can't be split for weight application,
    # since any target cell can draw from any source cell.
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


def coarsen_regional(
    ds: xr.Dataset, target_level: int, min_valid_fraction: float = 0.5
) -> xr.Dataset:
    """Coarsen a compact (regional) HEALPix dataset to a lower level.

    `grid_doctor.coarsen_healpix()` can't be reused here — it relies on array
    *position* directly encoding parent-child relationships (a fast reshape
    assuming a dense, full-global nested array), confirmed to fail outright on
    a compact array (reshape `ValueError`). Groups by actual cell-ID value
    instead. Cross-validated against `coarsen_healpix()`'s own dense-array
    output as ground truth on real BARRA2 data: identical cells and values
    (~1e-13 max diff — floating-point noise).

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

    cell_ids = ds["cell"].values
    parent_ids = xr.DataArray(cell_ids // divisor, dims="cell", name="parent")
    ds2 = ds.assign_coords(parent=parent_ids)

    data_vars = {}
    for name, da in ds2.data_vars.items():
        if "cell" not in da.dims:
            data_vars[name] = da
            continue
        grouped = da.groupby("parent")
        mean_val = grouped.mean(dim="cell", skipna=True)
        valid_frac = da.notnull().groupby(ds2["parent"]).sum(dim="cell") / divisor
        data_vars[name] = mean_val.where(valid_frac >= min_valid_fraction)

    result = xr.Dataset(data_vars)
    result = result.rename({"parent": "cell"})
    parent_ids_sorted = result["cell"].values
    result.attrs.update(ds.attrs)
    result.attrs["healpix_level"] = target_level
    return _gd_select.attach_cell_coords(
        result.drop_vars("cell"), parent_ids_sorted, level=target_level
    )


def build_regional_healpix_pyramid(
    ds: xr.Dataset, weights_path: Path, max_level: int, min_level: int
) -> dict[int, xr.Dataset]:
    """Build a full compact HEALPix pyramid for a regional source.

    Regrids `ds` directly to `max_level` via `regrid_regional_to_healpix()`,
    then coarsens down to `min_level` via `coarsen_regional()` at each
    intermediate level — the regional-source equivalent of
    `grid_doctor.create_healpix_pyramid()`, which can't be used directly here
    (see this module's other two functions' docstrings for why).

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
