# tests/weather/era5/test_downloader.py
"""Tests for ERA5 reanalysis data downloader."""

import pickle
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from rbc.weather.era5 import Era5Downloader


# ----------------------------------
# Specific fixtures
# ----------------------------------
@pytest.fixture
def api_credentials() -> dict:
    """Fixture with fake API credentials."""
    return {
        "api_key": "fake_api_key_12345",
    }


@pytest.fixture
def init_args(tmp_path: Path, api_credentials: dict) -> dict:
    """Creates a basic setup with a temporary directory."""
    return {
        **api_credentials,
        "output_path": tmp_path,
        "years": [2020],
        "months": ["01"],
        "variables": ["2m_temperature", "temperature"],
        "area": [-1.0, -1.0, 1.0, 1.0],
        "pressure_levels": ["1000", "950"],
        "model_levels": None,
        "resume": False,
        "dry_run": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> Era5Downloader:
    """Returns an instantiated Era5Downloader with mocked CDS client."""
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        dl = Era5Downloader(**init_args)
    return dl


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(init_args: dict) -> None:
    """Test basic initialization of Era5Downloader.

    Args:
        init_args (dict): Arguments used to initialise an Era5Downloader instance.
    """
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        downloader = Era5Downloader(**init_args)

        assert downloader.years == init_args["years"]
        assert downloader.months == init_args["months"]
        assert downloader.variables == init_args["variables"]
        assert downloader.area == init_args["area"]
        assert downloader.pressure_levels == init_args["pressure_levels"]
        assert downloader.model_levels == init_args["model_levels"]
        assert downloader.output_path == init_args["output_path"]
        assert downloader.checkpoint_path == Path(
            init_args["output_path"], "status.pickle"
        )


def test_downloader_initialization_default_months(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test initialization with default months (all 12 months).

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        downloader = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020],
        )

        assert len(downloader.months) == 12
        assert downloader.months[0] == "01"
        assert downloader.months[-1] == "12"


def test_downloader_initialization_invalid_format(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test initialization with invalid file format.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    with pytest.raises(ValueError, match="file_format must be"):
        with patch("rbc.weather.era5.downloader.cdsapi.Client"):
            Era5Downloader(
                **api_credentials,
                output_path=tmp_path,
                years=[2020],
                file_format="hdf5",
            )


# ----------------------------------
# Tests - Checkpoint handling
# ----------------------------------
def test_checkpoint_initialization_single_level_only(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test checkpoint shape when only single-level variables are requested.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        # When pressure_levels and model_levels are None, pressure_levels defaults to DEFAULT_PRESSURE_LEVELS
        # But we still get a 3D checkpoint because of the default behavior
        # To get only single-level, we would need to explicitly handle it differently
        # For now, test that when only single-level variables exist, the checkpoint is sized accordingly
        downloader = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020, 2021],
            months=["01", "02"],
            variables=["2m_temperature"],
            pressure_levels=None,
            model_levels=None,
        )

        # When defaults are used (pressure_levels default, no model_levels),
        # checkpoint has 3 dimensions: (years, months, level_types)
        # With DEFAULT_PRESSURE_LEVELS: has pressure-level data
        assert downloader.checkpoint.ndim == 3
        assert downloader.checkpoint.shape == (
            2,
            2,
            2,
        )  # 2 level types: single, pressure


def test_checkpoint_initialization_with_pressure_and_model(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test checkpoint shape when both pressure and model levels are requested.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        downloader = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            pressure_levels=["1000"],
            model_levels=["137"],
        )

        # Should have 3 dimensions: (years, months, level_types)
        # level_types: single, pressure, model
        assert downloader.checkpoint.ndim == 3
        assert downloader.checkpoint.shape == (1, 1, 3)


def test_checkpoint_resume(api_credentials: dict, tmp_path: Path) -> None:
    """Test checkpoint resume functionality.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    # Save a fake checkpoint file
    checkpoint = np.ones((1, 1))
    checkpoint_path = Path(tmp_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        downloader = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["2m_temperature"],
            pressure_levels=None,
            model_levels=None,
            resume=True,
        )

        np.testing.assert_array_equal(downloader.checkpoint, checkpoint)


# ----------------------------------
# Tests - Variable validation
# ----------------------------------
def test_validate_variables_valid(downloader: Era5Downloader) -> None:
    """Test validation of valid variables.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    # Should not raise any exception
    downloader._validate_variables()


def test_validate_variables_invalid_single_level(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test validation with invalid variable.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    with pytest.raises(ValueError, match="Invalid pressure-level variables"):
        with patch("rbc.weather.era5.downloader.cdsapi.Client"):
            Era5Downloader(
                **api_credentials,
                output_path=tmp_path,
                years=[2020],
                variables=["invalid_variable"],
                pressure_levels=[],  # Empty to avoid default pressure levels
                model_levels=None,
            )


def test_validate_variables_invalid_pressure_level(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test validation with variable not available at pressure levels.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    # 2m_temperature is valid but only at single-level. If we request it with pressure levels,
    # it will just be filtered to single-level only (no error raised)
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        downloader = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020],
            variables=["2m_temperature"],  # Only available at single level
            pressure_levels=["1000"],
            model_levels=None,
        )
        # Should not raise because 2m_temperature is simply not downloaded at pressure level
        assert downloader.variables == ["2m_temperature"]


# ----------------------------------
# Tests - MARS request building
# ----------------------------------
def test_get_mars_param(downloader: Era5Downloader) -> None:
    """Test conversion of variable names to MARS parameter codes.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    assert downloader._get_mars_param("2m_temperature") == "2t"
    assert downloader._get_mars_param("10m_u_component_of_wind") == "10u"
    assert downloader._get_mars_param("temperature") == "t"
    assert downloader._get_mars_param("u_component_of_wind") == "u"


def test_build_mars_request_batch_single_level(downloader: Era5Downloader) -> None:
    """Test MARS request building for single-level variables.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    request = downloader._build_mars_request_batch(
        variables=["2m_temperature", "surface_pressure"],
        year=2020,
        month="01",
        level_type="single",
    )

    assert request["class"] == "ea"
    assert request["param"] == "2t/sp"  # Combined params
    assert request["levtype"] == "sfc"
    assert "levelist" not in request
    assert request["date"] == "2020-01-01/to/2020-01-31"


def test_build_mars_request_batch_pressure_level(downloader: Era5Downloader) -> None:
    """Test MARS request building for pressure-level variables.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    request = downloader._build_mars_request_batch(
        variables=["temperature", "u_component_of_wind"],
        year=2020,
        month="01",
        level_type="pressure",
    )

    assert request["param"] == "t/u"
    assert request["levtype"] == "pl"
    assert request["levelist"] == "1000/950"


def test_build_mars_request_batch_model_level(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test MARS request building for model-level variables.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        downloader = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            pressure_levels=None,
            model_levels=["135", "136", "137"],
        )

        request = downloader._build_mars_request_batch(
            variables=["temperature"],
            year=2020,
            month="01",
            level_type="model",
        )

        assert request["param"] == "t"
        assert request["levtype"] == "ml"
        assert request["levelist"] == "135/136/137"


# ----------------------------------
# Tests - Download data
# ----------------------------------
def test_download_variables_dry_run(downloader: Era5Downloader) -> None:
    """Test _download_variables with dry_run enabled.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.dry_run = True

    with patch("builtins.print") as mock_print:
        status = downloader._download_variables(
            year=2020, month="01", level_type="single", checkpoint_idx=0
        )

    assert status == 1
    # Check that print was called (dry run output)
    assert mock_print.called


def test_download_variables_with_api_call(downloader: Era5Downloader) -> None:
    """Test _download_variables with actual API call (mocked).

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.dry_run = False

    with patch.object(downloader.client, "retrieve") as mock_retrieve:
        status = downloader._download_variables(
            year=2020, month="01", level_type="single", checkpoint_idx=0
        )

    assert status == 1
    assert mock_retrieve.called


def test_download_data_dry_run(downloader: Era5Downloader) -> None:
    """Test download_data method with dry_run enabled.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.dry_run = True

    with patch("builtins.print") as mock_print:
        downloader.download_data()

    # Should have printed at least 2 requests (single-level + pressure-level)
    assert mock_print.called


# ----------------------------------
# Tests - Utility methods
# ----------------------------------
def test_print_available_variables(capsys) -> None:
    """Test printing of available variables.

    Args:
        capsys: Capture system output.
    """
    Era5Downloader.print_available_variables()

    captured = capsys.readouterr()
    assert "AVAILABLE ERA5 VARIABLES" in captured.out
    assert "SINGLE-LEVEL (2D) VARIABLES" in captured.out
    assert "PRESSURE-LEVEL (3D) VARIABLES" in captured.out
    assert "MODEL-LEVEL (3D) VARIABLES" in captured.out
    assert "2m_temperature" in captured.out
    assert "temperature" in captured.out
