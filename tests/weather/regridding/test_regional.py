# tests/weather/regridding/test_regional.py
"""Tests for rbc.weather.regridding.regional: the regional-source workaround."""

import json
from pathlib import Path
from unittest.mock import call, patch

import numpy as np
import pytest
import xarray as xr

from rbc.weather.regridding.regional import (
    build_regional_healpix_pyramid,
    coarsen_regional,
    regrid_regional_to_healpix,
)


# ----------------------------------
# Helpers
# ----------------------------------
def _write_weights(
    path: Path,
    row: list[int],
    col: list[int],
    vals: list[float],
    source_dims: tuple[str, ...] = ("lat", "lon"),
    names: tuple[str, str, str] = ("row", "col", "S"),
) -> Path:
    """Write a minimal synthetic ESMF-style sparse weight file.

    Args:
        path (Path): Destination NetCDF path.
        row (list[int]): Target (HEALPix) cell index per weight entry.
        col (list[int]): Source cell index per weight entry.
        vals (list[float]): Weight value per entry.
        source_dims (tuple[str, ...]): Dims the weights were computed against.
        names (tuple[str, str, str]): (row, col, value) variable names to use.

    Returns:
        Path: The path written to.
    """
    row_name, col_name, val_name = names
    wds = xr.Dataset(
        {
            row_name: ("n_s", np.asarray(row, dtype=np.int64)),
            col_name: ("n_s", np.asarray(col, dtype=np.int64)),
            val_name: ("n_s", np.asarray(vals, dtype=np.float64)),
        },
        attrs={"grid_doctor_source_dims": json.dumps(list(source_dims))},
    )
    wds.to_netcdf(path)
    return path


def _make_cell_ds(cell_ids: list[int], values: list[float], level: int) -> xr.Dataset:
    """Build a minimal compact HEALPix Dataset for coarsen_regional() tests.

    Args:
        cell_ids (list[int]): Global HEALPix cell IDs.
        values (list[float]): One data value per cell.
        level (int): HEALPix level to record in attrs.

    Returns:
        xr.Dataset: Dataset with a "cell" dim/coord and healpix_level attr.
    """
    return xr.Dataset(
        {"var": ("cell", np.asarray(values, dtype=np.float64))},
        coords={"cell": ("cell", np.asarray(cell_ids, dtype=np.int64))},
        attrs={"healpix_level": level},
    )


# ----------------------------------
# regrid_regional_to_healpix
# ----------------------------------
class TestRegridRegionalToHealpix:
    """Tests for regrid_regional_to_healpix()."""

    def test_compacts_phantom_rows(self, tmp_path: Path) -> None:
        """Only unique referenced target cells appear, sized/valued correctly.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        weights_path = _write_weights(
            tmp_path / "weights.nc",
            row=[6, 6, 13, 13],  # 1-based; 0-based real cell ids are 5, 12
            col=[1, 2, 1, 4],  # 1-based; 0-based source indices 0, 1, 0, 3
            vals=[0.5, 0.5, 0.3, 0.7],
        )
        ds = xr.Dataset({"var": (("lat", "lon"), [[10.0, 20.0], [30.0, 40.0]])})

        result = regrid_regional_to_healpix(ds, weights_path, level=6)

        assert result.sizes["cell"] == 2
        assert list(result["cell"].values) == [5, 12]
        # The first target cell draws from source cells 0 and 1, averaging 10 and 20.
        # Calculation: 10 * 0.5 + 20 * 0.5 = 15.0
        # The second target cell draws from source cells 0 and 3, averaging 10 and 40.
        # Calculation: 10 * 0.3 + 40 * 0.7 = 31.0
        np.testing.assert_allclose(result["var"].values, [15.0, 31.0])

    def test_handles_already_zero_based_indices(self, tmp_path: Path) -> None:
        """Weight files whose indices already include 0 aren't shifted again.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        weights_path = _write_weights(
            tmp_path / "weights.nc",
            row=[0, 0, 7, 7],
            col=[0, 1, 0, 3],
            vals=[0.5, 0.5, 0.3, 0.7],
        )
        ds = xr.Dataset({"var": (("lat", "lon"), [[10.0, 20.0], [30.0, 40.0]])})

        result = regrid_regional_to_healpix(ds, weights_path, level=6)

        assert list(result["cell"].values) == [0, 7]
        np.testing.assert_allclose(result["var"].values, [15.0, 31.0])

    def test_alternate_weight_variable_names(self, tmp_path: Path) -> None:
        """dst_address/src_address/remap_matrix naming resolves the same way.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        weights_path = _write_weights(
            tmp_path / "weights.nc",
            row=[6, 6, 13, 13],
            col=[1, 2, 1, 4],
            vals=[0.5, 0.5, 0.3, 0.7],
            names=("dst_address", "src_address", "remap_matrix"),
        )
        ds = xr.Dataset({"var": (("lat", "lon"), [[10.0, 20.0], [30.0, 40.0]])})

        result = regrid_regional_to_healpix(ds, weights_path, level=6)

        assert list(result["cell"].values) == [5, 12]
        np.testing.assert_allclose(result["var"].values, [15.0, 31.0])

    def test_passes_through_non_spatial_variables(self, tmp_path: Path) -> None:
        """A variable without the resolved source dims is returned unchanged.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        weights_path = _write_weights(
            tmp_path / "weights.nc",
            row=[6, 6, 13, 13],
            col=[1, 2, 1, 4],
            vals=[0.5, 0.5, 0.3, 0.7],
        )
        ds = xr.Dataset(
            {
                "var": (("lat", "lon"), [[10.0, 20.0], [30.0, 40.0]]),
                "aux": ("foo", [1.0, 2.0, 3.0]),
            }
        )

        result = regrid_regional_to_healpix(ds, weights_path, level=6)

        np.testing.assert_array_equal(result["aux"].values, [1.0, 2.0, 3.0])
        assert result["aux"].dims == ("foo",)

    def test_renormalizes_over_nan_source_cells(self, tmp_path: Path) -> None:
        """A NaN source cell is excluded, not treated as a false zero.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        weights_path = _write_weights(
            tmp_path / "weights.nc",
            row=[6, 6, 13, 13],
            col=[1, 2, 1, 4],
            vals=[0.5, 0.5, 0.3, 0.7],
        )
        ds = xr.Dataset({"var": (("lat", "lon"), [[10.0, np.nan], [30.0, 40.0]])})

        result = regrid_regional_to_healpix(ds, weights_path, level=6)

        # cell 5 draws solely from the valid source cell once renormalized;
        # cell 12 is unaffected since neither of its source cells is NaN.
        np.testing.assert_allclose(result["var"].values, [10.0, 31.0])

    def test_sets_healpix_level_attr(self, tmp_path: Path) -> None:
        """The output carries the requested HEALPix level.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        weights_path = _write_weights(
            tmp_path / "weights.nc",
            row=[6, 6, 13, 13],
            col=[1, 2, 1, 4],
            vals=[0.5, 0.5, 0.3, 0.7],
        )
        ds = xr.Dataset({"var": (("lat", "lon"), [[10.0, 20.0], [30.0, 40.0]])})

        result = regrid_regional_to_healpix(ds, weights_path, level=6)

        assert result.attrs["healpix_level"] == 6
        assert "cell" in result.coords


# ----------------------------------
# coarsen_regional
# ----------------------------------
class TestCoarsenRegional:
    """Tests for coarsen_regional()."""

    def test_basic_single_group(self) -> None:
        """Four sibling cells average into their one parent cell."""
        ds = _make_cell_ds([8, 9, 10, 11], [1.0, 2.0, 3.0, 4.0], level=6)

        result = coarsen_regional(ds, target_level=5)

        assert result.sizes["cell"] == 1
        assert result["cell"].values[0] == 2
        assert result["var"].values[0] == pytest.approx(2.5)
        assert result.attrs["healpix_level"] == 5

    def test_multiple_non_contiguous_groups(self) -> None:
        """Widely separated parent groups are each averaged independently."""
        cell_ids = [8, 9, 10, 11, 4000, 4001, 4002, 4003]
        values = [1.0, 2.0, 3.0, 4.0, 10.0, 20.0, 30.0, 40.0]
        ds = _make_cell_ds(cell_ids, values, level=6)

        result = coarsen_regional(ds, target_level=5)

        assert list(result["cell"].values) == [2, 1000]
        np.testing.assert_allclose(result["var"].values, [2.5, 25.0])

    def test_min_valid_fraction_masks_low_coverage_parent(self) -> None:
        """A parent below the valid-fraction threshold becomes NaN.

        Also confirms skipna-mean and valid-fraction masking are distinct:
        a parent at exactly the 0.5 threshold keeps its skipna mean rather
        than being zeroed out by the missing children.
        """
        cell_ids = [8, 9, 10, 11, 12, 13, 14, 15]
        values = [1.0, np.nan, 3.0, np.nan, 10.0, np.nan, np.nan, np.nan]
        ds = _make_cell_ds(cell_ids, values, level=6)

        result = coarsen_regional(ds, target_level=5)

        by_cell = dict(zip(result["cell"].values, result["var"].values))
        assert by_cell[2] == pytest.approx(2.0)  # 2/4 valid, at threshold
        assert np.isnan(by_cell[3])  # 1/4 valid, below threshold

    def test_delta_greater_than_one(self) -> None:
        """Coarsening directly by more than one level groups by 4**delta."""
        cell_ids = list(range(16)) + list(range(96, 112))
        values = [float(v) for v in list(range(1, 17)) + list(range(101, 117))]
        ds = _make_cell_ds(cell_ids, values, level=6)

        result = coarsen_regional(ds, target_level=4)

        by_cell = dict(zip(result["cell"].values, result["var"].values))
        assert by_cell[0] == pytest.approx(8.5)
        assert by_cell[6] == pytest.approx(108.5)
        assert result.attrs["healpix_level"] == 4

    @pytest.mark.parametrize("target_level", [6, 7])
    def test_raises_for_invalid_target_level(self, target_level: int) -> None:
        """target_level must be strictly lower than the current level."""
        ds = _make_cell_ds([8, 9, 10, 11], [1.0, 2.0, 3.0, 4.0], level=6)

        with pytest.raises(ValueError, match="must be lower"):
            coarsen_regional(ds, target_level=target_level)

    def test_passes_through_non_cell_variables(self) -> None:
        """A variable without the "cell" dim is returned unchanged."""
        ds = _make_cell_ds([8, 9, 10, 11], [1.0, 2.0, 3.0, 4.0], level=6)
        ds["other"] = ("foo", [1.0, 2.0, 3.0])

        result = coarsen_regional(ds, target_level=5)

        np.testing.assert_array_equal(result["other"].values, [1.0, 2.0, 3.0])


# ----------------------------------
# build_regional_healpix_pyramid
# ----------------------------------
class TestBuildRegionalHealpixPyramid:
    """Tests for build_regional_healpix_pyramid()."""

    def test_builds_full_pyramid_via_chaining(self, tmp_path: Path) -> None:
        """Each coarser level is derived from the previous level's output.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        ds_input = xr.Dataset({"var": ("cell", [1.0])})
        weights_path = tmp_path / "weights.nc"

        with (
            patch(
                "rbc.weather.regridding.regional.regrid_regional_to_healpix"
            ) as mock_regrid,
            patch("rbc.weather.regridding.regional.coarsen_regional") as mock_coarsen,
        ):
            mock_regrid.return_value = "FINEST"
            mock_coarsen.side_effect = lambda ds, target_level: f"L{target_level}"

            pyramid = build_regional_healpix_pyramid(
                ds_input, weights_path, max_level=6, min_level=4
            )

        mock_regrid.assert_called_once_with(ds_input, weights_path, level=6)
        assert mock_coarsen.call_args_list == [
            call("FINEST", target_level=5),
            call("L5", target_level=4),
        ]
        assert pyramid == {6: "FINEST", 5: "L5", 4: "L4"}

    def test_single_level_when_min_equals_max(self, tmp_path: Path) -> None:
        """No coarsening happens when min_level == max_level.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        ds_input = xr.Dataset({"var": ("cell", [1.0])})
        weights_path = tmp_path / "weights.nc"

        with (
            patch(
                "rbc.weather.regridding.regional.regrid_regional_to_healpix"
            ) as mock_regrid,
            patch("rbc.weather.regridding.regional.coarsen_regional") as mock_coarsen,
        ):
            mock_regrid.return_value = "FINEST"

            pyramid = build_regional_healpix_pyramid(
                ds_input, weights_path, max_level=6, min_level=6
            )

        mock_coarsen.assert_not_called()
        assert pyramid == {6: "FINEST"}
