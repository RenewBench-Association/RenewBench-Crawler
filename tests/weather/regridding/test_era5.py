# tests/weather/regridding/test_era5.py
"""Tests for rbc.weather.regridding.era5: Era5Regridder."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from rbc.weather.era5.mappings import (
    ALL_PRESSURE_LEVEL_VARIABLES,
    ALL_SINGLE_LEVEL_VARIABLES,
    MODEL_CONFIG,
)
from rbc.weather.regridding.era5 import VARIABLE_MAPPING, Era5Regridder
from rbc.weather.utils import raw_data_dir


def _source_dir(raw_dir: Path) -> Path:
    """Return the expected ERA5 raw-data directory under raw_dir.

    Args:
        raw_dir (Path): Root raw-data directory (shared base).

    Returns:
        Path: Expected temporal-resolution-specific raw-data directory.
    """
    return raw_data_dir(
        raw_dir, MODEL_CONFIG["raw_folder"], MODEL_CONFIG["temporal_res_folder"]
    )


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def base_args(tmp_path: Path) -> dict:
    """Provide minimal valid keyword arguments for Era5Regridder.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        dict: Keyword arguments passed directly to Era5Regridder.
    """
    raw_dir = Path(tmp_path, "raw")
    raw_dir.mkdir()
    return {
        "raw_dir": raw_dir,
        "source_name": "era5",
        "weights_cache_dir": Path(tmp_path, "weights_cache"),
        "min_level": 4,
        "max_level": 7,
        "variables": ["2m_temperature"],
        "years": [2020],
        "months": ["04"],
    }


# ----------------------------------
# Era5Regridder._trim_to_month
# ----------------------------------
class TestTrimToMonth:
    """Tests for Era5Regridder._trim_to_month()."""

    def test_drops_out_of_month_timestamps(self, base_args: dict) -> None:
        """Only timestamps within the exact calendar month survive.

        Args:
            base_args (dict): Minimal valid keyword arguments for Era5Regridder.
        """
        rg = Era5Regridder(**base_args)
        # spans late March, three points across April, and early May
        time = pd.to_datetime(
            [
                "2020-03-31T22:00",
                "2020-03-31T23:00",
                "2020-04-01T00:00",
                "2020-04-15T12:00",
                "2020-04-30T23:00",
                "2020-05-01T00:00",
                "2020-05-01T01:00",
            ]
        )
        ds = xr.Dataset({"t2m": ("time", np.arange(len(time)))}, coords={"time": time})

        trimmed = rg._trim_to_month(ds, 2020, "04")

        expected = pd.to_datetime(
            ["2020-04-01T00:00", "2020-04-15T12:00", "2020-04-30T23:00"]
        )
        assert list(trimmed["time"].values) == list(expected)


# ----------------------------------
# Era5Regridder._open_single_level
# ----------------------------------
class TestOpenSingleLevel:
    """Tests for Era5Regridder._open_single_level()."""

    def test_flattens_step_hypercube(self, base_args: dict) -> None:
        """The (time, step) hypercube is flattened; flat-time passes through unchanged.

        Args:
            base_args (dict): Minimal valid keyword arguments for Era5Regridder.
        """
        rg = Era5Regridder(**base_args)

        flat_time_ds = xr.Dataset(
            {"t2m": ("time", [1.0, 2.0])},
            coords={"time": pd.to_datetime(["2020-04-01T00:00", "2020-04-01T01:00"])},
        )

        init_time = pd.to_datetime(["2020-04-01T00:00"]).values
        step = pd.to_timedelta([1, 2], unit="h").values
        valid_time = init_time[:, None] + step[None, :]
        step_ds = xr.Dataset(
            {"tp": (("time", "step"), [[0.1, 0.2]])},
            coords={
                "time": init_time,
                "step": step,
                "valid_time": (("time", "step"), valid_time),
            },
        )

        with patch(
            "rbc.weather.regridding.era5.cfgrib.open_datasets",
            return_value=[flat_time_ds, step_ds],
        ):
            opened = rg._open_single_level(Path("fake_sl.grib"))

        assert len(opened) == 2
        flattened = next(ds for ds in opened if "tp" in ds.data_vars)
        assert "step" not in flattened.dims
        assert "valid_time" not in flattened.coords
        assert list(flattened["time"].values) == list(
            pd.to_datetime(["2020-04-01T01:00", "2020-04-01T02:00"])
        )

        unchanged = next(ds for ds in opened if "t2m" in ds.data_vars)
        assert "step" not in unchanged.dims


# ----------------------------------
# Era5Regridder._open_pressure_level
# ----------------------------------
class TestOpenPressureLevel:
    """Tests for Era5Regridder._open_pressure_level()."""

    def test_renames_isobaricinhpa_to_level(self, base_args: dict) -> None:
        """The "isobaricInhPa" dim cfgrib gives is renamed to "level".

        Per the weather Zarr contract's naming convention for pressure-level
        variables.

        Args:
            base_args (dict): Minimal valid keyword arguments for Era5Regridder.
        """
        rg = Era5Regridder(**base_args)

        pl_ds = xr.Dataset(
            {"t": (("isobaricInhPa", "time"), [[1.0], [2.0]])},
            coords={"isobaricInhPa": [1000.0, 950.0], "time": [0]},
        )

        with patch(
            "rbc.weather.regridding.era5.xr.open_dataset", return_value=pl_ds
        ) as mock_open:
            result = rg._open_pressure_level(Path("fake_pl.grib"))

        mock_open.assert_called_once_with(
            Path("fake_pl.grib"), engine="cfgrib", chunks={}
        )
        assert "level" in result.dims
        assert "isobaricInhPa" not in result.dims
        assert list(result["level"].values) == [1000.0, 950.0]


# ----------------------------------
# Era5Regridder._load_source_chunk
# ----------------------------------
class TestLoadSourceChunk:
    """Tests for Era5Regridder._load_source_chunk()."""

    def test_discovers_and_merges_sl_and_pl_files(self, base_args: dict) -> None:
        """Single/pressure-level files are routed to the right opener, then merged.

        Args:
            base_args (dict): Minimal valid keyword arguments for Era5Regridder.
        """
        source_dir = _source_dir(base_args["raw_dir"])
        source_dir.mkdir(parents=True)
        sl_file = Path(source_dir, "era5_2020_04_sl_2t.grib")
        pl_file = Path(source_dir, "era5_2020_04_pl_1000_t.grib")
        sl_file.touch()
        pl_file.touch()

        rg = Era5Regridder(**base_args)

        time = pd.to_datetime(["2020-04-01T00:00", "2020-04-01T01:00"])
        sl_ds = xr.Dataset({"t2m": ("time", [1.0, 2.0])}, coords={"time": time})
        pl_ds = xr.Dataset(
            {"z": (("isobaricInhPa", "time"), [[3.0, 4.0]])},
            coords={"time": time, "isobaricInhPa": [1000.0]},
        )

        with (
            patch.object(rg, "_open_single_level", return_value=[sl_ds]) as mock_sl,
            patch(
                "rbc.weather.regridding.era5.xr.open_dataset", return_value=pl_ds
            ) as mock_pl,
        ):
            result = rg._load_source_chunk((2020, "04"))

        mock_sl.assert_called_once_with(sl_file)
        mock_pl.assert_called_once_with(pl_file, engine="cfgrib", chunks={})
        assert set(result.data_vars) == {"t2m", "z"}
        assert "level" in result["z"].dims
        assert "isobaricInhPa" not in result.dims
        assert list(result["time"].values) == list(time)

    def test_ignores_model_level_files(self, base_args: dict) -> None:
        """_ml_ files are never globbed or opened, even if present alongside others.

        Args:
            base_args (dict): Minimal valid keyword arguments for Era5Regridder.
        """
        source_dir = _source_dir(base_args["raw_dir"])
        source_dir.mkdir(parents=True)
        sl_file = Path(source_dir, "era5_2020_04_sl_2t.grib")
        sl_file.touch()
        Path(source_dir, "era5_2020_04_ml_133_q.grib").touch()

        rg = Era5Regridder(**base_args)

        time = pd.to_datetime(["2020-04-01T00:00"])
        sl_ds = xr.Dataset({"t2m": ("time", [1.0])}, coords={"time": time})

        with patch.object(rg, "_open_single_level", return_value=[sl_ds]) as mock_sl:
            rg._load_source_chunk((2020, "04"))

        mock_sl.assert_called_once_with(sl_file)


# ----------------------------------
# Era5Regridder._grid_metadata_path
# ----------------------------------
class TestGridMetadataPath:
    """Tests for Era5Regridder._grid_metadata_path()."""

    def test_returns_none(self, base_args: dict) -> None:
        """ERA5 has no separate grid definition file.

        Args:
            base_args (dict): Minimal valid keyword arguments for Era5Regridder.
        """
        rg = Era5Regridder(**base_args)
        assert rg._grid_metadata_path() is None


# ----------------------------------
# Era5Regridder._variable_mapping
# ----------------------------------
class TestVariableMapping:
    """Tests for Era5Regridder._variable_mapping()."""

    def test_returns_variable_mapping(self, base_args: dict) -> None:
        """Returns the module-level VARIABLE_MAPPING dict.

        Args:
            base_args (dict): Minimal valid keyword arguments for Era5Regridder.
        """
        rg = Era5Regridder(**base_args)
        assert rg._variable_mapping() == VARIABLE_MAPPING

    def test_mapping_values_are_known_era5_variables(self) -> None:
        """Every canonical name in VARIABLE_MAPPING is a real ERA5 variable.

        Catches VARIABLE_MAPPING silently drifting if era5/mappings.py ever
        renames a canonical variable.
        """
        known = ALL_SINGLE_LEVEL_VARIABLES | ALL_PRESSURE_LEVEL_VARIABLES
        unknown = set(VARIABLE_MAPPING.values()) - known
        assert not unknown, f"Unknown canonical names: {unknown}"
