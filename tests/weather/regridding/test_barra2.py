# tests/weather/regridding/test_barra2.py
"""Tests for rbc.weather.regridding.barra2: Barra2Regridder."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import xarray as xr

from rbc.weather.regridding.barra2 import Barra2Regridder


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def base_args(tmp_path: Path) -> dict:
    """Provide minimal valid keyword arguments for Barra2Regridder (minus model).

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        dict: Keyword arguments passed directly to Barra2Regridder.
    """
    raw_dir = Path(tmp_path, "raw")
    raw_dir.mkdir()
    return {
        "raw_dir": raw_dir,
        "source_name": "barra2_c2",
        "weights_cache_dir": Path(tmp_path, "weights_cache"),
        "min_level": 4,
        "max_level": 10,
        "variables": ["temperature"],
        "years": [2025],
        "months": ["01"],
    }


def _write_var_file(raw_dir: Path, filename: str, var_name: str, value: float) -> None:
    """Write a minimal single-variable NetCDF file, matching real BARRA2 layout.

    Args:
        raw_dir (Path): Directory to write into.
        filename (str): File name (without directory).
        var_name (str): The single data variable's name.
        value (float): A scalar value to fill the variable with.
    """
    ds = xr.Dataset({var_name: (("lat", "lon"), [[value]])})
    ds.to_netcdf(Path(raw_dir, filename))


# ----------------------------------
# Barra2Regridder.__init__
# ----------------------------------
class TestInit:
    """Tests for Barra2Regridder.__init__()."""

    def test_looks_up_temporal_res_from_model_config(self, base_args: dict) -> None:
        """temporal_res is looked up per model from MODEL_CONFIG.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        rg_c2 = Barra2Regridder(model="C2", **base_args)
        assert rg_c2.temporal_res == "1hr"

        rg_20min = Barra2Regridder(model="C2_20min", **base_args)
        assert rg_20min.temporal_res == "20min"


# ----------------------------------
# Barra2Regridder._load_source_chunk
# ----------------------------------
class TestLoadSourceChunk:
    """Tests for Barra2Regridder._load_source_chunk()."""

    def test_consolidates_pressure_level_files(self, base_args: dict) -> None:
        """Same-quantity pressure-level files stack into "ta_plev", descending.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_ta1000.nc", "ta1000", 1.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_ta950.nc", "ta950", 2.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_ta975.nc", "ta975", 3.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"))

        assert "ta_plev" in result.data_vars
        assert list(result["plev"].values) == [1000, 975, 950]
        np.testing.assert_allclose(result["ta_plev"].values.squeeze(), [1.0, 3.0, 2.0])

    def test_consolidates_height_level_files(self, base_args: dict) -> None:
        """Same-quantity height-level files stack into "ta_height", ascending.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_ta100m.nc", "ta100m", 20.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_ta50m.nc", "ta50m", 10.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"))

        assert "ta_height" in result.data_vars
        assert list(result["height"].values) == [50, 100]
        np.testing.assert_allclose(result["ta_height"].values.squeeze(), [10.0, 20.0])

    def test_single_level_file_passes_through_unchanged(self, base_args: dict) -> None:
        """A plain single-level file keeps its own variable name, no suffix.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"))

        assert "tas" in result.data_vars
        assert "tas_plev" not in result.data_vars
        assert "tas_height" not in result.data_vars

    def test_digit_suffixed_single_level_variables_are_not_misclassified(
        self, base_args: dict
    ) -> None:
        """Single-level names that coincidentally end in digits stay single-level.

        BWD03/BWD06 (bulk wind difference over 0-3km/0-6km) and omega500
        (vertical velocity at a fixed 500 hPa) are real single-level BARRA2
        variables whose names happen to match the level-code regex -- they
        must not be merged into fake "_plev" stacks.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_BWD03.nc", "BWD03", 1.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_BWD06.nc", "BWD06", 2.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_omega500.nc", "omega500", 3.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"))

        assert {"BWD03", "BWD06", "omega500"}.issubset(result.data_vars)
        assert "BWD_plev" not in result.data_vars
        assert "omega_plev" not in result.data_vars

    def test_merges_all_kinds_into_one_dataset(self, base_args: dict) -> None:
        """Single-level, pressure-level, and height-level files all merge.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_ta950.nc", "ta950", 2.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_ta50m.nc", "ta50m", 10.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"))

        assert set(result.data_vars) == {"tas", "ta_plev", "ta_height"}

    def test_only_matches_requested_task(self, base_args: dict) -> None:
        """Files for a different (year, month) aren't picked up.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202502_tas.nc", "tas", 50.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"))

        assert result["tas"].values.squeeze() == 5.0


# ----------------------------------
# Barra2Regridder._grid_metadata_path
# ----------------------------------
class TestGridMetadataPath:
    """Tests for Barra2Regridder._grid_metadata_path()."""

    def test_returns_none(self, base_args: dict) -> None:
        """BARRA2 has no separate grid definition file.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        rg = Barra2Regridder(model="C2", **base_args)
        assert rg._grid_metadata_path() is None


# ----------------------------------
# Barra2Regridder._regrid_chunk
# ----------------------------------
class TestRegridChunk:
    """Tests for Barra2Regridder._regrid_chunk()."""

    def test_delegates_to_regional_workaround(self, base_args: dict) -> None:
        """Delegates to build_regional_healpix_pyramid with the right kwargs.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        rg = Barra2Regridder(model="C2", **base_args)
        ds = xr.Dataset({"var": ("cell", [1.0])})
        weights = Path("fake_weights.nc")
        sentinel = {4: "pyramid"}

        with patch(
            "rbc.weather.regridding.barra2.build_regional_healpix_pyramid",
            return_value=sentinel,
        ) as mock_build:
            result = rg._regrid_chunk(ds, weights)

        mock_build.assert_called_once_with(
            ds, weights, max_level=rg.max_level, min_level=rg.min_level
        )
        assert result is sentinel


# ----------------------------------
# Barra2Regridder._variable_mapping
# ----------------------------------
class TestVariableMapping:
    """Tests for Barra2Regridder._variable_mapping()."""

    def test_plain_short_code_maps_to_canonical(self, base_args: dict) -> None:
        """A plain short code maps to its existing canonical name.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        rg = Barra2Regridder(model="C2", **base_args)
        mapping = rg._variable_mapping()
        assert mapping["tas"] == "1.5m_temperature"

    def test_height_level_bases_get_distinct_canonical_names(
        self, base_args: dict
    ) -> None:
        """Height-level consolidated names don't collide with pressure-level ones.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        rg = Barra2Regridder(model="C2", **base_args)
        mapping = rg._variable_mapping()
        assert mapping["ta_height"] == "temperature_at_height"
        assert mapping["ua_height"] == "u_component_of_wind_at_height"
        assert mapping["va_height"] == "v_component_of_wind_at_height"

    def test_pressure_level_bases_map_to_same_canonical_as_short_code(
        self, base_args: dict
    ) -> None:
        """'<base>_plev' maps to the same canonical name as the plain base code.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        rg = Barra2Regridder(model="C2", **base_args)
        mapping = rg._variable_mapping()
        assert mapping["ta_plev"] == mapping["ta"] == "temperature"
