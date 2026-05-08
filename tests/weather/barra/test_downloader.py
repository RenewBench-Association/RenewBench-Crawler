# tests/weather/barra/test_downloader.py
"""Tests for BARRA2 reanalysis data downloader."""

import pickle
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from rbc.weather.barra import Barra2Downloader
from rbc.weather.barra.downloader import _is_available_variable
from rbc.weather.barra.mappings import (
    DEFAULT_VARIABLES,
)


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture(autouse=True)
def mock_connectivity_check() -> Iterator[None]:
    """Patch requests.head so the BARRA2 connectivity check never hits the network."""
    with patch("rbc.weather.barra.downloader.requests.head") as mock_head:
        mock_head.return_value.raise_for_status.return_value = None
        yield


@pytest.fixture
def init_args(tmp_path: Path) -> dict:
    """Creates a basic setup with a temporary directory.

    Args:
        tmp_path (Path): Path to the temporary directory.

    Returns:
        dict: Initialization arguments for Barra2Downloader.
    """
    return {
        "output_path": tmp_path,
        "model": "R2",
        "years": [2020],
        "months": ["01"],
        "variables": ["1.5m_temperature", "total_precipitation"],
        "dry_run": False,
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> Barra2Downloader:
    """Returns an instantiated Barra2Downloader.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.

    Returns:
        Barra2Downloader: Instance of Barra2Downloader class.
    """
    return Barra2Downloader(**init_args)


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the Barra2Downloader sets up paths and checkpoint correctly.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    downloader = Barra2Downloader(**init_args)

    assert downloader.model == "R2"
    assert downloader.years == init_args["years"]
    assert downloader.months == init_args["months"]
    assert downloader.variables == init_args["variables"]
    assert downloader.dry_run == init_args["dry_run"]
    assert downloader.output_path == Path(init_args["output_path"], "R2")
    assert downloader.output_path.exists()
    assert downloader.checkpoint_path == Path(
        init_args["output_path"], "R2", "status.pickle"
    )
    assert isinstance(downloader.checkpoint, dict)
    assert downloader.checkpoint == {}


def test_connectivity_check_failure(init_args: dict) -> None:
    """Test that ConnectionError is raised when a BARRA2 endpoint is unreachable.

    The autouse mock_connectivity_check fixture is overridden here so that
    raise_for_status raises an exception, triggering the connection-error branch.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    with patch("rbc.weather.barra.downloader.requests.head") as mock_head:
        mock_head.return_value.raise_for_status.side_effect = Exception("timeout")
        with pytest.raises(ConnectionError, match="BARRA2 endpoints are unreachable"):
            Barra2Downloader(**init_args)


def test_downloader_initialization_pre_suffixed_output_path(init_args: dict) -> None:
    """Test that passing an output path already ending in the model name is handled correctly.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    pre_suffixed = init_args["output_path"] / "R2"
    init_args["output_path"] = pre_suffixed
    downloader = Barra2Downloader(**init_args)
    # Path should not be doubled to .../R2/R2
    assert downloader.output_path == pre_suffixed


@pytest.mark.parametrize(
    "model, variables, exp_label, exp_spatial_res, exp_grid, exp_temporal_res",
    [
        ("R2", None, "R2", "11 km", "AUS-11", "1hr"),
        ("C2", None, "C2", "4 km", "AUST-04", "1hr"),
        ("C2_20min", ["1.5m_temperature"], "C2", "4 km", "AUST-04", "20min"),
    ],
)
def test_downloader_init_model_configs(
    tmp_path: Path,
    model: str,
    variables: list[str] | None,
    exp_label: str,
    exp_spatial_res: str,
    exp_grid: str,
    exp_temporal_res: str,
) -> None:
    """Happy paths for class initialization with different model configs.

    Args:
        tmp_path (Path): Path to the temporary directory.
        model (str): BARRA2 model key.
        variables (list[str] | None): Variables to pass; None uses model defaults.
        exp_label (str): Expected substring in config label.
        exp_spatial_res (str): Expected substring in config resolution.
        exp_grid (str): Expected substring in config grid.
        exp_temporal_res (str): Expected temporal resolution string.
    """
    downloader = Barra2Downloader(
        output_path=tmp_path, model=model, years=[2020], variables=variables
    )

    if variables is None:
        default_variables = [var for var in DEFAULT_VARIABLES if _is_available_variable(var, model)]
        assert downloader.variables == default_variables
    assert exp_label in downloader.model_config["label"]
    assert exp_spatial_res in downloader.model_config["resolution"]
    assert exp_grid in downloader.model_config["grid"]
    assert downloader.temporal_res == exp_temporal_res
    assert len(downloader.available_variables) > 0


@pytest.mark.parametrize(
    "kwargs, error_match",
    [
        ({"model": "INVALID"}, "Unknown BARRA2 model"),
        ({"model": "C2_invalid"}, "Unknown BARRA2 model"),
        ({"variables": ["nonexistent_var_xyz"]}, "Invalid variables"),
        # Variable exists in the mapping but is not available for R2
        (
            {"variables": ["vertical_velocity_in_pressure"]},
            "Variables not available for BARRA2",
        ),
    ],
)
def test_initialization_validation_errors(
    init_args: dict,
    kwargs: dict,
    error_match: str,
) -> None:
    """Different failure paths for class initialization.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
        kwargs (dict): Arguments to override in the default args dict.
        error_match (str): Expected error message pattern.
    """
    init_args.update(kwargs)

    with pytest.raises(ValueError, match=error_match):
        Barra2Downloader(**init_args)


def test_invalid_years_are_filtered_out(init_args: dict) -> None:
    """Years outside the valid range are silently filtered out, not raised.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    init_args["years"] = [1800, 2020, 9999]
    downloader = Barra2Downloader(**init_args)
    assert downloader.years == [2020]


def test_downloader_initialization_optional_args(tmp_path: Path) -> None:
    """Test default and overridden values for optional init arguments.

    Verifies that months default to all 12 and that model-default pressure levels
    are set, and that both can be overridden.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = Barra2Downloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    assert len(downloader.months) == 12
    assert downloader.months[0] == "01"
    assert downloader.months[-1] == "12"
    assert len(downloader.pressure_levels) > 0  # model defaults are set

    custom_levels = [500, 700, 850, 1000]
    dl_custom = Barra2Downloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
        months=["06"],
        pressure_levels=custom_levels,
    )
    assert dl_custom.months == ["06"]
    assert dl_custom.pressure_levels == custom_levels


# ----------------------------------
# Tests - Checkpoint handling
# ----------------------------------
@pytest.mark.parametrize(
    "resume, exp_checkpoint",
    [
        (True, {(2020, "01", "1.5m_temperature"): 1}),
        (False, {}),
    ],
)
def test_checkpoint_resume_behavior(
    init_args: dict,
    resume: bool,
    exp_checkpoint: dict,
) -> None:
    """Happy and skip paths for checkpoint resume behavior.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
        resume (bool): Whether to resume from checkpoint.
        exp_checkpoint (dict): Expected checkpoint state after initialization.
    """
    checkpoint = {(2020, "01", "1.5m_temperature"): 1}
    checkpoint_path = Path(init_args["output_path"], "R2", "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    init_args["resume"] = resume
    downloader = Barra2Downloader(**init_args)
    assert downloader.checkpoint == exp_checkpoint


# ----------------------------------
# Tests - File path & URL construction
# ----------------------------------
def test_construct_file_path(downloader: Barra2Downloader) -> None:
    """Test file path construction resolves to BARRA2 code.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """
    file_path = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert file_path.parent == downloader.output_path
    assert "R2" in str(file_path)
    assert "1hr" in str(file_path)
    assert "202001" in str(file_path)
    # File name uses resolved BARRA2 code, not descriptive name
    assert "tas" in str(file_path)
    assert str(file_path).endswith(".nc")
    # Passing a raw BARRA2 code directly is also accepted (passthrough fallback)
    file_path_raw = downloader._construct_file_path(2020, "01", "tas")
    assert file_path_raw == file_path


def test_construct_file_path_different_vars(downloader: Barra2Downloader) -> None:
    """Test file paths for different variables are distinct.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """
    path1 = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    path2 = downloader._construct_file_path(2020, "01", "total_precipitation")
    assert str(path1) != str(path2)
    assert "tas" in str(path1)
    assert "pr" in str(path2)


def test_construct_file_path_invariant_uses_fx_name(tmp_path: Path) -> None:
    """Invariant files should use fx naming without year/month in filename.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = Barra2Downloader(
        output_path=tmp_path,
        model="C2_20min",
        years=[2022],
        months=["04"],
        variables=["orography"],
    )

    # Invariant variables ignore year/month; use sentinel values matching the actual call site.
    file_path = downloader._construct_file_path(0, "fx", "orography")

    assert file_path.parent.name == "invariant"
    assert file_path.name == "barra2_C2_20min_fx_orog.nc"
    assert "202204" not in file_path.name


def test_include_invariants_adds_invariant_variables(tmp_path: Path) -> None:
    """Test that include_invariants appends invariant fields in downloader.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = Barra2Downloader(
        output_path=tmp_path,
        model="R2",
        years=[2022],
        months=["04"],
        variables=["1.5m_temperature"],
        include_invariants=True,
    )

    assert "orography" in downloader.variables
    assert "land_sea_mask" in downloader.variables


def test_build_opendap_url_r2(downloader: Barra2Downloader) -> None:
    """Test OPeNDAP URL construction for R2 model.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """
    url = downloader._build_opendap_url(2020, "06", "1.5m_temperature")
    assert "thredds.nci.org.au" in url
    assert "202006" in url
    # URL uses resolved BARRA2 code
    assert "tas" in url


def test_build_opendap_url_different_models(
    tmp_path: Path, downloader: Barra2Downloader
) -> None:
    """Test that URLs differ by model.

    Args:
        tmp_path (Path): Path to the temporary directory.
        downloader (Barra2Downloader): R2 downloader instance.
    """
    dl_c2 = Barra2Downloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    url_r2 = downloader._build_opendap_url(2020, "01", "1.5m_temperature")
    url_c2 = dl_c2._build_opendap_url(2020, "01", "1.5m_temperature")
    assert url_r2 != url_c2


def test_build_opendap_url_invariant_uses_fx_path(tmp_path: Path) -> None:
    """Invariant variables should be fetched from fx path, not temporal folders.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = Barra2Downloader(
        output_path=tmp_path,
        model="C2_20min",
        years=[2022],
        months=["04"],
        variables=["land_sea_mask"],
    )

    # Invariant variables ignore year/month; use sentinel values matching the actual call site.
    url = downloader._build_opendap_url(0, "fx", "land_sea_mask")

    assert "/fx/sftlf/latest/" in url
    assert "_v1.nc" in url
    assert "/20min/" not in url
    assert "202204" not in url


# ----------------------------------
# Tests - Temporal resolution
# ----------------------------------
def test_temporal_res_in_file_path(tmp_path: Path) -> None:
    """Test that model key controls temporal resolution in file paths.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_1hr = Barra2Downloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    dl_20min = Barra2Downloader(
        output_path=tmp_path,
        model="C2_20min",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    path_1hr = dl_1hr._construct_file_path(2020, "01", "1.5m_temperature")
    path_20min = dl_20min._construct_file_path(2020, "01", "1.5m_temperature")
    assert "1hr" in str(path_1hr)
    assert "20min" in str(path_20min)
    assert path_1hr != path_20min


def test_temporal_res_in_opendap_url(tmp_path: Path) -> None:
    """Test that model key controls temporal resolution in OPeNDAP URLs.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_1hr = Barra2Downloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    dl_20min = Barra2Downloader(
        output_path=tmp_path,
        model="C2_20min",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    url_1hr = dl_1hr._build_opendap_url(2020, "01", "1.5m_temperature")
    url_20min = dl_20min._build_opendap_url(2020, "01", "1.5m_temperature")
    assert "/1hr/" in url_1hr
    assert "/20min/" in url_20min


# ----------------------------------
# Tests - Download data
# ----------------------------------
def test_dry_run_flag(init_args: dict) -> None:
    """Test dry_run flag setting.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    init_args["dry_run"] = True
    dl_dry = Barra2Downloader(**init_args)
    assert dl_dry.dry_run is True

    init_args["dry_run"] = False
    dl_normal = Barra2Downloader(**init_args)
    assert dl_normal.dry_run is False


def test_dry_run_completes_without_error(init_args: dict) -> None:
    """Test that a dry run workflow completes without errors.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    init_args["dry_run"] = True
    downloader = Barra2Downloader(**init_args)
    downloader.download_data()

    # Dry run must not write to checkpoint
    assert downloader.checkpoint == {}
    assert not downloader.checkpoint_path.exists()


def test_download_data_skips_completed(init_args: dict) -> None:
    """Test that download_data skips tasks already in checkpoint.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    # Save a fake checkpoint marking all tasks as done
    checkpoint = {
        (2020, "01", "1.5m_temperature"): 1,
        (2020, "01", "total_precipitation"): 1,
    }
    checkpoint_path = Path(init_args["output_path"], "R2", "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    init_args["resume"] = True
    downloader = Barra2Downloader(**init_args)

    with patch.object(downloader, "_download_task") as mock_dl:
        downloader.download_data()
        mock_dl.assert_not_called()


def test_download_data_calls_download_variable(init_args: dict) -> None:
    """Test that download_data calls _download_variable for pending tasks.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    init_args["variables"] = ["1.5m_temperature"]
    downloader = Barra2Downloader(**init_args)

    with patch.object(downloader, "_download_task", return_value=1) as mock_dl:
        downloader.download_data()
        mock_dl.assert_called_once_with((2020, "01", "1.5m_temperature"))


def test_download_data_calls_download_variable_for_invariant(init_args: dict) -> None:
    """Test that download_data calls _download_variable with fx sentinels for invariants.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    init_args["variables"] = ["orography"]
    downloader = Barra2Downloader(**init_args)

    with patch.object(downloader, "_download_task", return_value=1) as mock_dl:
        downloader.download_data()
        mock_dl.assert_called_once_with(("fx", "fx", "orography"))


def test_download_data_skips_completed_invariant(init_args: dict) -> None:
    """Test that download_data skips an invariant already marked in the checkpoint.

    Args:
        init_args (dict): Initialization arguments for Barra2Downloader.
    """
    checkpoint: dict = {("fx", "fx", "orography"): 1}
    checkpoint_path = Path(init_args["output_path"], "R2", "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    init_args["variables"] = ["orography"]
    init_args["resume"] = True
    downloader = Barra2Downloader(**init_args)

    with patch.object(downloader, "_download_task") as mock_dl:
        downloader.download_data()
        mock_dl.assert_not_called()


# ----------------------------------
# Tests - Multiple models independent
# ----------------------------------
def test_multiple_models_independent(tmp_path: Path) -> None:
    """Test that downloaders for different models are independent.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_r2 = Barra2Downloader(
        output_path=tmp_path / "r2",
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    dl_c2 = Barra2Downloader(
        output_path=tmp_path / "c2",
        model="C2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    assert dl_r2.model == "R2"
    assert dl_c2.model == "C2"
    assert dl_r2.output_path != dl_c2.output_path


# ----------------------------------
# Tests - Download variable branches
# ----------------------------------
def test_download_variable_skips_when_file_exists(downloader: Barra2Downloader) -> None:
    """Test that existing output file is treated as successful and skipped.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """
    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    output_file.write_bytes(b"already here")

    result = downloader._download_task((2020, "01", "1.5m_temperature"))

    assert result == 1


def test_download_variable_success_writes_file(downloader: Barra2Downloader) -> None:
    """Test successful streamed download path and file creation.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """
    mock_response = MagicMock()
    mock_response.headers = {"content-length": "4"}
    mock_response.iter_content.return_value = [b"ab", b"cd"]
    mock_response.raise_for_status.return_value = None

    with patch("rbc.weather.utils.requests.get", return_value=mock_response), patch(
        "rbc.weather.utils.tqdm"
    ) as mock_tqdm:
        progress = MagicMock()
        progress.__enter__.return_value = progress  # make context manager return itself
        mock_tqdm.return_value = progress

        result = downloader._download_task((2020, "01", "1.5m_temperature"))

    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert result == 1
    assert output_file.exists()
    assert output_file.read_bytes() == b"abcd"
    assert progress.update.call_count == 2
    progress.close.assert_called_once()


def test_download_variable_request_exception_removes_partial(
    downloader: Barra2Downloader,
) -> None:
    """Test RequestException path returns failure and leaves no output file.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """
    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert not output_file.exists()

    with patch(
        "rbc.weather.utils.requests.get",
        side_effect=requests.exceptions.RequestException("boom"),
    ):
        result = downloader._download_task((2020, "01", "1.5m_temperature"))

    assert result == 0
    assert not output_file.exists()


def test_download_variable_request_exception_removes_existing_partial(
    downloader: Barra2Downloader,
) -> None:
    """Test RequestException during streaming cleans up the partially written file.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """

    def _failing_chunks(chunk_size: int):
        yield b"ab"
        raise requests.exceptions.RequestException("connection dropped")

    mock_response = MagicMock()
    mock_response.headers = {"content-length": "4"}
    mock_response.raise_for_status.return_value = None
    mock_response.iter_content.side_effect = _failing_chunks

    with patch("rbc.weather.utils.requests.get", return_value=mock_response), patch(
        "rbc.weather.utils.tqdm", return_value=MagicMock()
    ):
        result = downloader._download_task((2020, "01", "1.5m_temperature"))

    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert result == 0
    assert not output_file.exists()


def test_download_variable_generic_exception_removes_partial(
    downloader: Barra2Downloader,
) -> None:
    """Test generic exception path removes partially written output file.

    Args:
        downloader (Barra2Downloader): Instance of Barra2Downloader class.
    """

    def _broken_chunks(chunk_size: int):
        del chunk_size
        yield b"ab"
        raise RuntimeError("stream error")

    mock_response = MagicMock()
    mock_response.headers = {"content-length": "4"}
    mock_response.iter_content.side_effect = _broken_chunks
    mock_response.raise_for_status.return_value = None

    with patch("rbc.weather.utils.requests.get", return_value=mock_response), patch(
        "rbc.weather.utils.tqdm"
    ) as mock_tqdm:
        progress = MagicMock()
        progress.__enter__.return_value = progress
        mock_tqdm.return_value = progress
        result = downloader._download_task((2020, "01", "1.5m_temperature"))

    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert result == 0
    assert not output_file.exists()


# ----------------------------------
# Tests - Catalog printing
# ----------------------------------
def test_print_available_variables_for_all_models() -> None:
    """Test static variable logging for all models."""
    with patch("rbc.weather.barra.downloader.logger.info") as mock_log:
        Barra2Downloader.print_available_variables("all")

    logged_output = "\n".join(str(call.args[0]) for call in mock_log.call_args_list)
    assert "AVAILABLE BARRA2-R2 VARIABLES" in logged_output
    assert "AVAILABLE BARRA2-C2 VARIABLES" in logged_output
    assert "AVAILABLE BARRA2-C2_20min VARIABLES" in logged_output
    assert "USAGE EXAMPLES:" in logged_output


def test_print_available_variables_invalid_model_raises() -> None:
    """Test static variable printer rejects unknown model keys."""
    with pytest.raises(ValueError, match="Unknown BARRA2 model"):
        Barra2Downloader.print_available_variables("X2")
