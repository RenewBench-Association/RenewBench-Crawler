# tests/weather/era5/test_downloader.py
"""Tests for ERA5 reanalysis data downloader."""

import pickle
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rbc.weather.era5 import Era5Downloader


# ----------------------------------
# Specific fixtures
# ----------------------------------
@pytest.fixture(autouse=True)
def mock_requests_head() -> Iterator[MagicMock]:
    """Suppress the ERA5 connectivity check for all tests in this module.

    Yields:
        MagicMock: Mocked requests.head with a 200 status code response.
    """
    with patch("rbc.weather.era5.downloader.requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        yield mock_head


@pytest.fixture
def api_credentials() -> dict:
    """Fixture with fake API credentials.

    Returns:
        dict: API credentials for Era5Downloader.
    """
    return {
        "api_key": "fake_api_key_12345",
    }


@pytest.fixture
def init_args(tmp_path: Path, api_credentials: dict) -> dict:
    """Creates a basic setup with a temporary directory.

    Args:
        tmp_path (Path): Path to the temporary directory.
        api_credentials (dict): API credentials for Era5Downloader.

    Returns:
        dict: Initialization arguments for Era5Downloader.
    """
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
    """Returns an instantiated Era5Downloader with mocked CDS client.

    Args:
        init_args (dict): Initialization arguments for Era5Downloader.

    Returns:
        Era5Downloader: Instance of Era5Downloader class.
    """
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        dl = Era5Downloader(**init_args)
    return dl


@pytest.fixture
def model_level_downloader(api_credentials: dict, tmp_path: Path) -> Era5Downloader:
    """Returns an Era5Downloader configured with model levels only (no pressure levels).

    Args:
        api_credentials (dict): API credentials for Era5Downloader.
        tmp_path (Path): Path to the temporary directory.

    Returns:
        Era5Downloader: Era5Downloader instance configured with model levels.
    """
    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        dl = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            pressure_levels=None,
            model_levels=["135", "136", "137"],
        )
    return dl


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: Era5Downloader, init_args: dict) -> None:
    """Test basic initialization of Era5Downloader.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
        init_args (dict): Arguments used to initialize an Era5Downloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.months == init_args["months"]
    assert downloader.variables == init_args["variables"]
    assert downloader.area == init_args["area"]
    assert downloader.pressure_levels == init_args["pressure_levels"]
    assert downloader.model_levels == init_args["model_levels"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")


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


def test_downloader_initialization_unreachable_endpoint(
    api_credentials: dict, tmp_path: Path, mock_requests_head: MagicMock
) -> None:
    """Test that ConnectionError is raised when the CDS endpoint is unreachable.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
        mock_requests_head (MagicMock): Autouse fixture for requests.head mock.
    """
    mock_requests_head.side_effect = Exception("unreachable")

    with pytest.raises(ConnectionError, match="CDS API endpoint unreachable"):
        with patch("rbc.weather.era5.downloader.cdsapi.Client"):
            Era5Downloader(
                **api_credentials,
                output_path=tmp_path,
                years=[2020],
            )


def test_model_levels_empty_list_becomes_default(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test that model_levels=[] falls back to DEFAULT_MODEL_LEVELS.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    from rbc.weather.era5.mappings import DEFAULT_MODEL_LEVELS

    with patch("rbc.weather.era5.downloader.cdsapi.Client"):
        downloader = Era5Downloader(
            **api_credentials,
            output_path=tmp_path,
            years=[2020],
            pressure_levels=None,
            model_levels=[],
        )
    assert downloader.model_levels == DEFAULT_MODEL_LEVELS


def test_cdsapi_client_initialization_failure(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test that ValueError is raised when the CDS API client cannot be initialized.

    Args:
        api_credentials (dict): API credentials.
        tmp_path (Path): Temporary directory.
    """
    with patch(
        "rbc.weather.era5.downloader.cdsapi.Client",
        side_effect=Exception("auth failed"),
    ):
        with pytest.raises(ValueError, match="Failed to initialize CDS API client"):
            Era5Downloader(
                **api_credentials,
                output_path=tmp_path,
                years=[2020],
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

        # Checkpoint should be a dict initialized as empty (lazy population)
        assert isinstance(downloader.checkpoint, dict)
        # On fresh initialization, checkpoint is empty
        assert downloader.checkpoint == {}


def test_checkpoint_initialization_with_pressure_and_model(
    api_credentials: dict, tmp_path: Path
) -> None:
    """Test checkpoint structure when both pressure and model levels are requested.

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

        # Checkpoint should be a dict initialized as empty (lazy population)
        assert isinstance(downloader.checkpoint, dict)
        # On fresh initialization, checkpoint is empty
        assert downloader.checkpoint == {}


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
    with pytest.raises(ValueError, match="Unrecognized variables"):
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


def test_validate_variables_pressure_level_invalid(downloader: Era5Downloader) -> None:
    """Test validation when a variable is not available at the requested pressure levels.

    Patches ALL_PRESSURE_LEVEL_VARIABLES to be empty so 'temperature' (still in
    ALL_MODEL_LEVEL_VARIABLES) triggers the invalid-pressure-level error branch.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    with patch("rbc.weather.era5.downloader.ALL_PRESSURE_LEVEL_VARIABLES", set()):
        with pytest.raises(ValueError, match="Invalid pressure-level"):
            downloader._validate_variables()


def test_validate_variables_model_level_invalid(downloader: Era5Downloader) -> None:
    """Test validation when a variable is not available at the requested model levels.

    Patches ALL_MODEL_LEVEL_VARIABLES to be empty so 'temperature' (still in
    ALL_PRESSURE_LEVEL_VARIABLES) triggers the invalid-model-level error branch.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.model_levels = ["137"]  # enable model-level checking
    with patch("rbc.weather.era5.downloader.ALL_MODEL_LEVEL_VARIABLES", set()):
        with pytest.raises(ValueError, match="Invalid model-level"):
            downloader._validate_variables()


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


def test_get_mars_param_fallback_returns_variable_name(
    downloader: Era5Downloader,
) -> None:
    """Test that _get_mars_param returns the variable name when it is not in the mapping.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    result = downloader._get_mars_param("custom_unmapped_variable")
    assert result == "custom_unmapped_variable"


def test_build_mars_request_batch_single_level(downloader: Era5Downloader) -> None:
    """Test MARS request building for single-level variables.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    request = downloader._build_request_batch(
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
    request = downloader._build_request_batch(
        variables=["temperature", "u_component_of_wind"],
        year=2020,
        month="01",
        level_type="pressure",
    )

    assert request["param"] == "t/u"
    assert request["levtype"] == "pl"
    assert request["levelist"] == "1000/950"


def test_build_mars_request_batch_model_level(
    model_level_downloader: Era5Downloader,
) -> None:
    """Test MARS request building for model-level variables.

    Args:
        model_level_downloader (Era5Downloader): Downloader configured with model levels.
    """
    request = model_level_downloader._build_request_batch(
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

    with patch("rbc.weather.era5.downloader.logger.info") as mock_log:
        status = downloader._download_variables(
            year=2020, month="01", level_type="single"
        )

    assert status == 1
    # Check that logger was called with the dry run output
    logged = "".join(str(c.args[0]) for c in mock_log.call_args_list)
    assert "DRY RUN" in logged


def test_download_variables_with_api_call(downloader: Era5Downloader) -> None:
    """Test _download_variables with actual API call (mocked).

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.dry_run = False

    with patch.object(downloader.client, "retrieve") as mock_retrieve:
        status = downloader._download_variables(
            year=2020, month="01", level_type="single"
        )

    assert status == 1
    assert mock_retrieve.called


def test_download_variables_already_exists(downloader: Era5Downloader) -> None:
    """Test _download_variables skips the API call when the output file exists.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.dry_run = False

    # The fixture has variables=["2m_temperature", "temperature"] and
    # pressure_levels=["1000","950"]. For level_type="single", only
    # 2m_temperature (param "2t") is downloaded, producing this filename:
    existing_file = (
        downloader.output_path / f"era5_2020_01_sl_2t.grib"
    )
    existing_file.touch()

    with patch.object(downloader.client, "retrieve") as mock_retrieve:
        status = downloader._download_variables(
            year=2020, month="01", level_type="single"
        )

    assert status == 1
    assert not mock_retrieve.called


def test_download_data_dry_run(downloader: Era5Downloader) -> None:
    """Test download_data method with dry_run enabled.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.dry_run = True

    with patch("rbc.weather.era5.downloader.logger.info") as mock_log:
        downloader.download_data()

    # Should have logged at least 2 dry run requests (single-level + pressure-level)
    logged = "".join(str(c.args[0]) for c in mock_log.call_args_list)
    assert "DRY RUN" in logged


def test_get_tasks_includes_model_level(
    model_level_downloader: Era5Downloader,
) -> None:
    """Test that model-level tasks are generated when model_levels is set.

    Args:
        model_level_downloader (Era5Downloader): Downloader configured with model levels.
    """
    tasks = model_level_downloader._get_tasks()
    level_types = {t[2] for t in tasks}
    assert "model" in level_types
    assert "single" in level_types


def test_download_variables_model_level_dry_run(
    model_level_downloader: Era5Downloader,
) -> None:
    """Test _download_variables dry-run for model level (covers model branch and custom suffix).

    Uses non-default model_levels so the custom level suffix path is also exercised.

    Args:
        model_level_downloader (Era5Downloader): Downloader configured with model levels.
    """
    model_level_downloader.dry_run = True
    status = model_level_downloader._download_variables(
        year=2020, month="01", level_type="model"
    )
    assert status == 1


def test_download_variables_empty_variables_for_level_type_returns_1(
    downloader: Era5Downloader,
) -> None:
    """Test that _download_variables returns 1 immediately when no variables match the level type.

    With only single-level variables and level_type="pressure", variables_to_download
    is empty and the early-return path is exercised.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.variables = ["2m_temperature"]
    status = downloader._download_variables(
        year=2020, month="01", level_type="pressure"
    )
    assert status == 1


def test_download_variables_api_exception_returns_0(downloader: Era5Downloader) -> None:
    """Test that an exception raised by client.retrieve returns 0.

    Args:
        downloader (Era5Downloader): Instance of Era5Downloader.
    """
    downloader.dry_run = False
    with patch.object(
        downloader.client, "retrieve", side_effect=Exception("MARS error")
    ):
        status = downloader._download_variables(
            year=2020, month="01", level_type="single"
        )
    assert status == 0


# ----------------------------------
# Tests - Utility methods
# ----------------------------------
def test_print_available_variables() -> None:
    """Test logging of available variables output."""
    with patch("rbc.weather.era5.downloader.logger.info") as mock_log:
        Era5Downloader.print_available_variables()

    assert mock_log.call_count == 2
    logged_output = "\n".join(str(call.args[0]) for call in mock_log.call_args_list)

    assert "AVAILABLE ERA5 VARIABLES" in logged_output
    assert "SINGLE-LEVEL (2D) VARIABLES" in logged_output
    assert "PRESSURE-LEVEL (3D) VARIABLES" in logged_output
    assert "MODEL-LEVEL (3D) VARIABLES" in logged_output
    assert "2m_temperature" in logged_output
    assert "temperature" in logged_output
