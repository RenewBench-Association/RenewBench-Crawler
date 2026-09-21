# tests/weather/regridding/test_barra2.py
"""Tests for rbc.weather.regridding.barra2: Barra2Regridder."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from rbc.weather.barra.mappings import MODEL_CONFIG
from rbc.weather.regridding.barra2 import (
    Barra2Regridder,
    _interval_center_shift,
    _packed_encoding,
)
from rbc.weather.utils import raw_data_dir


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
        "checkpoint_path": Path(tmp_path, "status.pickle"),
        "min_level": 4,
        "max_level": 10,
        "variables": ["temperature"],
        "years": [2025],
        "months": ["01"],
    }


def _write_var_file(
    raw_dir: Path,
    filename: str,
    var_name: str,
    value: float,
    model: str = "C2",
    extra_coords: dict | None = None,
    time: list | None = None,
    cell_methods: str | None = None,
    packing: dict | None = None,
) -> None:
    """Write a minimal single-variable NetCDF file, matching real BARRA2 layout.

    Writes under raw_data_dir(raw_dir, ...) -- utils.py's shared convention,
    the same one the regridder itself resolves from raw_dir.

    Args:
        raw_dir (Path): Regridder's raw_dir (base dir shared by every model
            variant).
        filename (str): File name (without directory).
        var_name (str): The single data variable's name.
        value (float): A scalar value to fill the variable with.
        model (str): BARRA2 model variant. Defaults to "C2".
        extra_coords (dict | None): Additional scalar coordinates to attach,
            e.g. {"pressure": 950.0} -- mimics real BARRA2 files, which carry
            their own per-file scalar "pressure"/"height" coordinate.
        time (list | None): Timestamps to add as a "time" dimension. Omitted
            (the default) writes a plain (lat, lon) file, as most tests need.
        cell_methods (str | None): "cell_methods" attribute to attach to the
            variable, e.g. "time: mean (interval: 1 hour)".
        packing (dict | None): NetCDF `encoding` for the variable, e.g.
            {"dtype": "int32", "scale_factor": 0.01, "add_offset": 270.0} --
            mimics real BARRA2 files' own CF integer packing.
    """
    config = MODEL_CONFIG[model]
    source_dir = raw_data_dir(
        raw_dir, config["raw_folder"], config["temporal_res_folder"]
    )
    source_dir.mkdir(parents=True, exist_ok=True)
    coords = dict(extra_coords or {})
    data: tuple
    if time is not None:
        coords["time"] = time
        data = ("time", "lat", "lon"), np.full((len(time), 1, 1), value)
    else:
        data = ("lat", "lon"), [[value]]
    ds = xr.Dataset({var_name: data}, coords=coords)
    if cell_methods is not None:
        ds[var_name].attrs["cell_methods"] = cell_methods
    encoding = {var_name: packing} if packing is not None else None
    ds.to_netcdf(Path(source_dir, filename), encoding=encoding)


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

        Uses a "level" dim, per the weather Zarr contract's naming convention.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta1000.nc",
            "ta1000",
            1.0,
            extra_coords={"pressure": 1000.0},
        )
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta950.nc",
            "ta950",
            2.0,
            extra_coords={"pressure": 950.0},
        )
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta975.nc",
            "ta975",
            3.0,
            extra_coords={"pressure": 975.0},
        )

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "temperature")

        assert "ta_plev" in result.data_vars
        assert "level" in result["ta_plev"].dims
        assert list(result["level"].values) == [1000.0, 975.0, 950.0]
        assert result["level"].dtype == np.float64
        np.testing.assert_allclose(result["ta_plev"].values.squeeze(), [1.0, 3.0, 2.0])
        # each file's own scalar "pressure" coord is dropped, not merged
        assert "pressure" not in result.coords

    def test_consolidates_height_level_files(self, base_args: dict) -> None:
        """Same-quantity height-level files stack into "ta_height", ascending.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta100m.nc",
            "ta100m",
            20.0,
            extra_coords={"height": 100.0},
        )
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta50m.nc",
            "ta50m",
            10.0,
            extra_coords={"height": 50.0},
        )

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "temperature_at_height")

        assert "ta_height" in result.data_vars
        assert list(result["height"].values) == [50.0, 100.0]
        assert result["height"].dtype == np.float64
        np.testing.assert_allclose(result["ta_height"].values.squeeze(), [10.0, 20.0])

    def test_single_level_file_passes_through_unchanged(self, base_args: dict) -> None:
        """A plain single-level file keeps its own variable name, no suffix.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "1.5m_temperature")

        assert "tas" in result.data_vars
        assert "tas_plev" not in result.data_vars
        assert "tas_height" not in result.data_vars

    def test_ignores_auxiliary_time_bnds_variable(self, base_args: dict) -> None:
        """A file with an extra "time_bnds" variable doesn't crash or leak it through.

        Confirmed on real data: time-averaged quantities like "clt" (total
        cloud cover) carry a CF-convention "time_bnds" variable alongside the
        real one, unlike the purely-instantaneous variables this module was
        first verified against -- a plain `(var_name,) = ds.data_vars` unpack
        breaks the moment a file has more than one variable.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        config = MODEL_CONFIG["C2"]
        source_dir = raw_data_dir(
            raw_dir, config["raw_folder"], config["temporal_res_folder"]
        )
        source_dir.mkdir(parents=True, exist_ok=True)
        ds = xr.Dataset(
            {
                "clt": (("time", "lat", "lon"), [[[50.0]]]),
                "time_bnds": (("time", "bnds"), [[0.0, 1.0]]),
            }
        )
        ds.to_netcdf(Path(source_dir, "barra2_C2_1hr_202501_clt.nc"))

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "total_cloud_cover")

        assert "clt" in result.data_vars
        assert "time_bnds" not in result.data_vars

    def test_level_value_comes_from_content_not_filename(self, base_args: dict) -> None:
        """The level/height coordinate value is read from the file, not parsed from its name.

        Deliberately mismatched here (filename says "ta950", file's own
        "pressure" coordinate says 900.0) to prove which one wins -- the
        file's own recorded value is authoritative, since it needs no
        filename-inferred-value caveat in STAC metadata the way a
        filename-parsed value would.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta950.nc",
            "ta950",
            1.0,
            extra_coords={"pressure": 900.0},
        )

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "temperature")

        assert list(result["level"].values) == [900.0]

    def test_only_matches_requested_task(self, base_args: dict) -> None:
        """Files for a different (year, month) aren't picked up.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202502_tas.nc", "tas", 50.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "1.5m_temperature")

        assert result["tas"].values.squeeze() == 5.0

    def test_only_matches_requested_variables_base_code(self, base_args: dict) -> None:
        """A single-level variable sharing the base's prefix is not pulled in.

        Requesting "temperature" (base "ta") globs "ta*", which also matches
        "tas.nc" -- a different, single-level variable. The anchored level
        regex must reject it.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta1000.nc",
            "ta1000",
            1.0,
            extra_coords={"pressure": 1000.0},
        )
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "temperature")

        assert set(result.data_vars) == {"ta_plev"}

    def test_shifts_interval_statistic_onto_the_point_clock(
        self, base_args: dict
    ) -> None:
        """A "time: mean" variable's half-hour-offset timestamps shift to on-the-hour.

        BARRA2 labels interval statistics at the interval's center, half an
        hour ahead of "time: point" variables.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_tasmax.nc",
            "tasmax",
            5.0,
            time=pd.to_datetime(["2025-01-01T00:30", "2025-01-01T01:30"]),
            cell_methods="time: maximum (interval: 1 hour)",
        )

        rg = Barra2Regridder(model="C2", **base_args)
        result = rg._load_source_chunk((2025, "01"), "1.5m_maximum_temperature")

        assert list(result["time"].values) == list(
            pd.to_datetime(["2025-01-01T00:00", "2025-01-01T01:00"])
        )


# ----------------------------------
# _interval_center_shift
# ----------------------------------
class TestIntervalCenterShift:
    """Tests for barra2._interval_center_shift()."""

    @pytest.mark.parametrize(
        "cell_methods, expected",
        [
            ("time: point (interval: 1 hour)", None),
            ("time: mean (interval: 1 hour)", -pd.Timedelta(minutes=30)),
            # interval is read from the file, not assumed (the 20-minute product)
            ("time: mean (interval: 20 minute)", -pd.Timedelta(minutes=10)),
            ("time: mean", None),
        ],
        ids=["point", "mean_1h", "mean_20min", "no_interval"],
    )
    def test_shift_is_minus_half_the_interval(
        self, cell_methods: str, expected: pd.Timedelta | None
    ) -> None:
        """Interval statistics shift back by half their interval; points don't move.

        Args:
            cell_methods (str): The variable's cell_methods attribute.
            expected (pd.Timedelta | None): Expected shift.
        """
        assert _interval_center_shift(cell_methods) == expected


# ----------------------------------
# Barra2Regridder._discover_variables
# ----------------------------------
class TestDiscoverVariables:
    """Tests for Barra2Regridder._discover_variables()."""

    def test_finds_single_pressure_and_height_variables(self, base_args: dict) -> None:
        """Single-level, pressure-level, and height-level files are all discovered.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta950.nc",
            "ta950",
            2.0,
            extra_coords={"pressure": 950.0},
        )
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta50m.nc",
            "ta50m",
            10.0,
            extra_coords={"height": 50.0},
        )

        rg = Barra2Regridder(model="C2", **base_args)
        found = rg._discover_variables((2025, "01"))

        assert set(found) == {
            "1.5m_temperature",
            "temperature",
            "temperature_at_height",
        }

    def test_digit_suffixed_single_level_variables_are_not_misclassified(
        self, base_args: dict
    ) -> None:
        """Single-level names that coincidentally end in digits stay single-level.

        BWD03/BWD06 (bulk wind difference over 0-3km/0-6km) and omega500
        (vertical velocity at a fixed 500 hPa) are real single-level BARRA2
        variables whose names happen to match the level-code regex -- they
        must not be classified as fake "_plev" stacks.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_BWD03.nc", "BWD03", 1.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_BWD06.nc", "BWD06", 2.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_omega500.nc", "omega500", 3.0)

        rg = Barra2Regridder(model="C2", **base_args)
        found = rg._discover_variables((2025, "01"))

        assert set(found) == {
            "bulk_wind_difference_0_3km",
            "bulk_wind_difference_0_6km",
            "vertical_velocity_500hpa",
        }

    def test_only_matches_requested_task(self, base_args: dict) -> None:
        """Files for a different (year, month) aren't picked up.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(raw_dir, "barra2_C2_1hr_202501_tas.nc", "tas", 5.0)
        _write_var_file(raw_dir, "barra2_C2_1hr_202502_clt.nc", "clt", 50.0)

        rg = Barra2Regridder(model="C2", **base_args)
        found = rg._discover_variables((2025, "01"))

        assert found == ["1.5m_temperature"]


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


# ----------------------------------
# _packed_encoding
# ----------------------------------
class TestPackedEncoding:
    """Tests for barra2._packed_encoding()."""

    def test_extracts_packing_fields(self) -> None:
        """A CF-packed encoding yields dtype/scale_factor/add_offset/_FillValue."""
        encoding = {
            "dtype": "int32",
            "scale_factor": 0.001953125,
            "add_offset": 270.125,
            "_FillValue": -2147483647,
            "zlib": True,  # not part of the packing itself -- must be dropped
        }
        assert _packed_encoding(encoding) == {
            "dtype": "int32",
            "scale_factor": 0.001953125,
            "add_offset": 270.125,
            "_FillValue": -2147483647,
        }

    def test_missing_scale_factor_returns_none(self) -> None:
        """An encoding without scale_factor isn't CF-packed -- returns None."""
        assert _packed_encoding({"dtype": "float64", "zlib": True}) is None


# ----------------------------------
# Barra2Regridder.encoding_for
# ----------------------------------
class TestEncodingFor:
    """Tests for Barra2Regridder.encoding_for()."""

    def test_captures_single_level_packing(self, base_args: dict) -> None:
        """A single-level variable's own packing is captured after loading.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_tas.nc",
            "tas",
            5.0,
            packing={
                "dtype": "int32",
                "scale_factor": 0.000244140625,
                "add_offset": 267.0,
                "_FillValue": -2147483647,
            },
        )

        rg = Barra2Regridder(model="C2", **base_args)
        rg._load_source_chunk((2025, "01"), "1.5m_temperature")

        assert rg.encoding_for("1.5m_temperature") == {
            "dtype": np.dtype("int32"),
            "scale_factor": 0.000244140625,
            "add_offset": 267.0,
            "_FillValue": -2147483647,
        }

    def test_captures_packing_for_consolidated_level_variable(
        self, base_args: dict
    ) -> None:
        """A pressure-level variable's packing comes from its first level file.

        Args:
            base_args (dict): Minimal valid keyword arguments for Barra2Regridder.
        """
        raw_dir = base_args["raw_dir"]
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta950.nc",
            "ta950",
            1.0,
            extra_coords={"pressure": 950.0},
            packing={
                "dtype": "int32",
                "scale_factor": 0.001953125,
                "add_offset": 268.0,
                "_FillValue": -2147483647,
            },
        )
        _write_var_file(
            raw_dir,
            "barra2_C2_1hr_202501_ta1000.nc",
            "ta1000",
            2.0,
            extra_coords={"pressure": 1000.0},
            packing={
                "dtype": "int32",
                "scale_factor": 0.001953125,
                "add_offset": 270.0,
                "_FillValue": -2147483647,
            },
        )

        rg = Barra2Regridder(model="C2", **base_args)
        rg._load_source_chunk((2025, "01"), "temperature")

        result = rg.encoding_for("temperature")
        assert result is not None
        assert result["scale_factor"] == 0.001953125
        assert result["add_offset"] in (
            268.0,
            270.0,
        )  # either level file is safe to reuse
