# tests/weather/regridding/test_icon_dream.py
"""Tests for rbc.weather.regridding.icon_dream: IconDreamRegridder."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from rbc.weather.regridding.icon_dream import VARIABLE_MAPPING, IconDreamRegridder


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def base_args(tmp_path: Path) -> dict:
    """Provide minimal valid keyword arguments for IconDreamRegridder (minus model).

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        dict: Keyword arguments passed directly to IconDreamRegridder.
    """
    raw_dir = Path(tmp_path, "raw")
    raw_dir.mkdir()
    return {
        "raw_dir": raw_dir,
        "source_name": "icon_dream_global",
        "weights_cache_dir": Path(tmp_path, "weights_cache"),
        "min_level": 4,
        "max_level": 7,
        "variables": ["2m_temperature"],
        "years": [2025],
        "months": ["01"],
    }


def _hypercube(values_size: int = 2, with_level: bool = False) -> xr.Dataset:
    """Build a minimal synthetic (time, step, values) hypercube, like real ICON-DREAM GRIB.

    Args:
        values_size (int): Size of the unstructured "values" dim.
        with_level (bool): If True, adds a "generalVerticalLayer" dim (model-level shape).

    Returns:
        xr.Dataset: Synthetic dataset with a "t" or "t2m" variable.
    """
    init_time = pd.to_datetime(["2025-01-01T00:00"]).values
    step = pd.to_timedelta([1, 2, 3], unit="h").values
    valid_time = init_time[:, None] + step[None, :]
    coords = {
        "time": init_time,
        "step": step,
        "valid_time": (("time", "step"), valid_time),
    }
    if with_level:
        level_data = np.arange(1 * 3 * 2 * values_size, dtype=float).reshape(
            1, 3, 2, values_size
        )
        return xr.Dataset(
            {"t": (("time", "step", "generalVerticalLayer", "values"), level_data)},
            coords={**coords, "generalVerticalLayer": [111.0, 112.0]},
        )
    flat_data = np.arange(1 * 3 * values_size, dtype=float).reshape(1, 3, values_size)
    return xr.Dataset({"t2m": (("time", "step", "values"), flat_data)}, coords=coords)


# ----------------------------------
# IconDreamRegridder.__init__
# ----------------------------------
class TestInit:
    """Tests for IconDreamRegridder.__init__()."""

    @pytest.mark.parametrize("model_input", ["eu", "EU", "Europe", "europe"])
    def test_normalizes_eu_variants(self, model_input: str, base_args: dict) -> None:
        """'eu'/'EU'/'Europe'/'europe' all normalize to the "eu" model config.

        Args:
            model_input (str): Raw model string passed by the caller.
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model=model_input, **base_args)
        assert rg.model == "eu"
        assert rg.model_config["label"] == "ICON-DREAM-EU"

    def test_global_model(self, base_args: dict) -> None:
        """'global' picks up the global model config.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model="global", **base_args)
        assert rg.model == "global"
        assert rg.model_config["label"] == "ICON-DREAM-Global"


# ----------------------------------
# IconDreamRegridder._load_source_chunk
# ----------------------------------
class TestLoadSourceChunk:
    """Tests for IconDreamRegridder._load_source_chunk()."""

    def test_flattens_step_and_renames_values_to_cell(self, base_args: dict) -> None:
        """(time, step) is flattened via valid_time; "values" becomes "cell".

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        raw_dir = base_args["raw_dir"]
        f = Path(raw_dir, "ICON-DREAM-Global_202501_T_2M_hourly.grb")
        f.touch()
        rg = IconDreamRegridder(model="global", **base_args)

        with patch(
            "rbc.weather.regridding.icon_dream.cfgrib.open_datasets",
            return_value=[_hypercube()],
        ):
            result = rg._load_source_chunk((2025, "01"))

        assert "step" not in result.dims
        assert "values" not in result.dims
        assert "cell" in result.dims
        assert list(result["time"].values) == list(
            pd.to_datetime(["2025-01-01T01:00", "2025-01-01T02:00", "2025-01-01T03:00"])
        )

    def test_preserves_model_level_dim(self, base_args: dict) -> None:
        """The "generalVerticalLayer" dim passes through untouched, alongside flattening.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        raw_dir = base_args["raw_dir"]
        f = Path(raw_dir, "ICON-DREAM-Global_202501_T_hourly.grb")
        f.touch()
        rg = IconDreamRegridder(model="global", **base_args)

        with patch(
            "rbc.weather.regridding.icon_dream.cfgrib.open_datasets",
            return_value=[_hypercube(with_level=True)],
        ):
            result = rg._load_source_chunk((2025, "01"))

        assert "generalVerticalLayer" in result["t"].dims
        assert result.sizes["generalVerticalLayer"] == 2
        assert "cell" in result["t"].dims

    def test_merges_multiple_files(self, base_args: dict) -> None:
        """Single-level and model-level files merge into one Dataset.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        raw_dir = base_args["raw_dir"]
        Path(raw_dir, "ICON-DREAM-Global_202501_T_2M_hourly.grb").touch()
        Path(raw_dir, "ICON-DREAM-Global_202501_T_hourly.grb").touch()
        rg = IconDreamRegridder(model="global", **base_args)

        with patch(
            "rbc.weather.regridding.icon_dream.cfgrib.open_datasets",
            side_effect=[[_hypercube()], [_hypercube(with_level=True)]],
        ):
            result = rg._load_source_chunk((2025, "01"))

        assert set(result.data_vars) == {"t2m", "t"}

    def test_only_matches_requested_task(self, base_args: dict) -> None:
        """Files for a different (year, month) aren't globbed.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        raw_dir = base_args["raw_dir"]
        Path(raw_dir, "ICON-DREAM-Global_202501_T_2M_hourly.grb").touch()
        Path(raw_dir, "ICON-DREAM-Global_202502_T_2M_hourly.grb").touch()
        rg = IconDreamRegridder(model="global", **base_args)

        with patch(
            "rbc.weather.regridding.icon_dream.cfgrib.open_datasets",
            return_value=[_hypercube()],
        ) as mock_open:
            rg._load_source_chunk((2025, "01"))

        mock_open.assert_called_once_with(
            Path(raw_dir, "ICON-DREAM-Global_202501_T_2M_hourly.grb"), chunks={}
        )

    def test_trims_spillover_past_month_boundary(self, base_args: dict) -> None:
        """Timestamps outside the exact calendar month are dropped.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        raw_dir = base_args["raw_dir"]
        Path(raw_dir, "ICON-DREAM-Global_202501_T_2M_hourly.grb").touch()
        rg = IconDreamRegridder(model="global", **base_args)

        # A cycle initialized late on Dec 31 whose early lead hours land in
        # December, confirmed as real behavior against actual ICON-DREAM data.
        init_time = pd.to_datetime(["2024-12-31T21:00"]).values
        step = pd.to_timedelta([1, 2, 3], unit="h").values
        valid_time = init_time[:, None] + step[None, :]
        spillover_ds = xr.Dataset(
            {"t2m": (("time", "step", "values"), [[[1.0], [2.0], [3.0]]])},
            coords={
                "time": init_time,
                "step": step,
                "valid_time": (("time", "step"), valid_time),
            },
        )

        with patch(
            "rbc.weather.regridding.icon_dream.cfgrib.open_datasets",
            return_value=[spillover_ds],
        ):
            result = rg._load_source_chunk((2025, "01"))

        # Only the step-3 valid time (2025-01-01T00:00) falls inside January.
        assert list(result["time"].values) == list(pd.to_datetime(["2025-01-01T00:00"]))


# ----------------------------------
# IconDreamRegridder._grid_metadata_path
# ----------------------------------
class TestGridMetadataPath:
    """Tests for IconDreamRegridder._grid_metadata_path()."""

    def test_global_picks_grid_file_not_grfinfo(self, base_args: dict) -> None:
        """Returns the plain grid definition file, not the -grfinfo.nc one.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model="global", **base_args)
        path = rg._grid_metadata_path()
        assert path == Path(
            base_args["raw_dir"], "metadata", "icon_grid_0026_R03B07_G.nc"
        )

    def test_eu_picks_grid_file_not_grfinfo(self, base_args: dict) -> None:
        """Returns the plain grid definition file for the EU variant too.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model="eu", **base_args)
        path = rg._grid_metadata_path()
        assert path == Path(
            base_args["raw_dir"], "metadata", "icon_grid_0027_R03B08_N02.nc"
        )


# ----------------------------------
# IconDreamRegridder._regrid_kwargs
# ----------------------------------
class TestRegridKwargs:
    """Tests for IconDreamRegridder._regrid_kwargs()."""

    @pytest.mark.parametrize("model", ["global", "eu"])
    def test_returns_unstructured_source_kind(
        self, model: str, base_args: dict
    ) -> None:
        """Always declares source_kind="unstructured", regardless of model.

        Args:
            model (str): Model variant under test.
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model=model, **base_args)
        assert rg._regrid_kwargs() == {"source_kind": "unstructured"}


# ----------------------------------
# IconDreamRegridder._regrid_chunk
# ----------------------------------
class TestRegridChunk:
    """Tests for IconDreamRegridder._regrid_chunk()."""

    def test_eu_delegates_to_regional_workaround(self, base_args: dict) -> None:
        """EU (regional) uses build_regional_healpix_pyramid(), not grid-doctor's own path.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model="eu", **base_args)
        ds = xr.Dataset({"var": ("cell", [1.0])})
        weights = Path("fake_weights.nc")
        sentinel = {4: "pyramid"}

        with patch(
            "rbc.weather.regridding.icon_dream.build_regional_healpix_pyramid",
            return_value=sentinel,
        ) as mock_build:
            result = rg._regrid_chunk(ds, weights)

        mock_build.assert_called_once_with(
            ds, weights, max_level=rg.max_level, min_level=rg.min_level
        )
        assert result is sentinel

    def test_global_uses_default_grid_doctor_path(self, base_args: dict) -> None:
        """Global falls through to the base class's default create_healpix_pyramid() path.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model="global", **base_args)
        ds = xr.Dataset({"var": ("cell", [1.0])})
        weights = Path("fake_weights.nc")
        sentinel = {4: "pyramid"}

        with patch(
            "rbc.weather.regridding.base.gd.create_healpix_pyramid",
            return_value=sentinel,
        ) as mock_create:
            result = rg._regrid_chunk(ds, weights)

        mock_create.assert_called_once_with(
            ds,
            max_level=rg.max_level,
            min_level=rg.min_level,
            weights_path=weights,
            source_kind="unstructured",
        )
        assert result is sentinel


# ----------------------------------
# IconDreamRegridder._variable_mapping
# ----------------------------------
class TestVariableMapping:
    """Tests for IconDreamRegridder._variable_mapping()."""

    def test_returns_variable_mapping(self, base_args: dict) -> None:
        """Returns the module-level VARIABLE_MAPPING dict.

        Args:
            base_args (dict): Minimal valid keyword arguments for IconDreamRegridder.
        """
        rg = IconDreamRegridder(model="global", **base_args)
        assert rg._variable_mapping() == VARIABLE_MAPPING

    def test_mapping_has_confirmed_entries(self) -> None:
        """Only the two cfgrib names confirmed against real sample data are mapped."""
        assert VARIABLE_MAPPING == {
            "t2m": "2m_temperature",
            "t": "temperature",
        }
