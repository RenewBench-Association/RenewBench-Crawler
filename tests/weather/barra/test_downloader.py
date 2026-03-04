# tests/weather/barra/test_downloader.py
"""Tests for BARRA reanalysis data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from rbc.weather.barra import BarraDownloader
from rbc.weather.barra.mappings import (
    DEFAULT_VARIABLES,
)


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def basic_args(tmp_path: Path) -> dict:
    """Creates a basic setup with a temporary directory.

    Args:
        tmp_path (Path): Path to the temporary directory.

    Returns:
        dict: Initialization arguments for BarraDownloader.
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
def downloader(basic_args: dict) -> BarraDownloader:
    """Returns an instantiated BarraDownloader.

    Args:
        basic_args (dict): Basic initialization arguments.

    Returns:
        BarraDownloader: Instance of BarraDownloader class.
    """
    return BarraDownloader(**basic_args)


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(basic_args: dict) -> None:
    """Happy path for class initialization.

    Check that the BarraDownloader sets up paths and checkpoint correctly.

    Args:
        basic_args (dict): Initialization arguments for BarraDownloader.
    """
    downloader = BarraDownloader(**basic_args)

    assert downloader.model == "R2"
    assert downloader.years == basic_args["years"]
    assert downloader.months == basic_args["months"]
    assert downloader.variables == basic_args["variables"]
    assert downloader.dry_run == basic_args["dry_run"]
    assert downloader.output_path == Path(basic_args["output_path"], "R2")
    assert downloader.checkpoint_path == Path(
        basic_args["output_path"], "R2", "status.pickle"
    )


def test_downloader_initialization_c2(tmp_path: Path) -> None:
    """Happy path for initialization with C2 model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2022],
        variables=["1.5m_temperature"],
    )
    assert downloader.model == "C2"
    assert len(downloader.available_variables) > 0


def test_downloader_initialization_invalid_model(tmp_path: Path) -> None:
    """Failure path for initialization with invalid model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with pytest.raises(ValueError, match="Unknown BARRA model"):
        BarraDownloader(
            output_path=tmp_path,
            model="INVALID",
            years=[2020],
            variables=["1.5m_temperature"],
        )


def test_downloader_initialization_creates_output_dir(tmp_path: Path) -> None:
    """Test that output directory is created upon initialization.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    output_path = tmp_path / "new_dir" / "barra_data"
    assert not output_path.exists()

    BarraDownloader(
        output_path=output_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    assert (output_path / "R2").exists()


def test_downloader_initialization_default_months(tmp_path: Path) -> None:
    """Test that all months are used by default.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    assert len(downloader.months) == 12
    assert downloader.months[0] == "01"
    assert downloader.months[-1] == "12"


def test_downloader_initialization_default_variables_r2(tmp_path: Path) -> None:
    """Test that R2 uses correct default variables.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
    )
    assert downloader.variables == DEFAULT_VARIABLES


def test_downloader_initialization_default_variables_c2(tmp_path: Path) -> None:
    """Test that C2 uses the same default variables as R2.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
    )
    assert downloader.variables == DEFAULT_VARIABLES


def test_downloader_initialization_custom_pressure_levels(tmp_path: Path) -> None:
    """Test initialization with custom pressure levels.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    levels = [500, 700, 850, 1000]
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
        pressure_levels=levels,
    )
    assert downloader.pressure_levels == levels


def test_downloader_initialization_invalid_variables(tmp_path: Path) -> None:
    """Failure path for initialization with invalid variables.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with pytest.raises(ValueError, match="Invalid variables"):
        BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
            variables=["nonexistent_var_xyz"],
        )


# ----------------------------------
# Tests - Checkpoint handling
# ----------------------------------
def test_checkpoint_initialization(basic_args: dict) -> None:
    """Test that checkpoint dict is initialized as empty on fresh start.

    Args:
        basic_args (dict): Initialization arguments for BarraDownloader.
    """
    downloader = BarraDownloader(**basic_args)

    assert isinstance(downloader.checkpoint, dict)
    assert downloader.checkpoint == {}


def test_checkpoint_resume(tmp_path: Path) -> None:
    """Happy path for checkpoint resume functionality.

    Check that BarraDownloader correctly loads an existing checkpoint file.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    # Save a fake checkpoint
    checkpoint = {(2020, "01", "1.5m_temperature"): 1}
    checkpoint_path = Path(tmp_path, "R2", "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["1.5m_temperature"],
        resume=True,
    )
    assert downloader.checkpoint == checkpoint


def test_checkpoint_not_resumed_if_resume_false(tmp_path: Path) -> None:
    """Test that checkpoint is ignored when resume=False.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    # Save a fake checkpoint
    checkpoint = {(2020, "01", "1.5m_temperature"): 1}
    checkpoint_path = Path(tmp_path, "R2", "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["1.5m_temperature"],
        resume=False,
    )
    assert downloader.checkpoint == {}


# ----------------------------------
# Tests - File path & URL construction
# ----------------------------------
def test_construct_file_path(downloader: BarraDownloader) -> None:
    """Test file path construction resolves to BARRA code.

    Args:
        downloader (BarraDownloader): Instance of BarraDownloader class.
    """
    file_path = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert file_path.parent == downloader.output_path
    assert "R2" in str(file_path)
    assert "1hr" in str(file_path)
    assert "202001" in str(file_path)
    # File name uses resolved BARRA code, not descriptive name
    assert "tas" in str(file_path)
    assert str(file_path).endswith(".nc")


def test_construct_file_path_different_vars(downloader: BarraDownloader) -> None:
    """Test file paths for different variables are distinct.

    Args:
        downloader (BarraDownloader): Instance of BarraDownloader class.
    """
    path1 = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    path2 = downloader._construct_file_path(2020, "01", "total_precipitation")
    assert str(path1) != str(path2)
    assert "tas" in str(path1)
    assert "pr" in str(path2)


def test_construct_file_path_invariant_uses_fx_name(tmp_path: Path) -> None:
    """Invariant files should use fx naming without year/month in filename."""
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="C2_20min",
        years=[2022],
        months=["04"],
        variables=["orography"],
    )

    file_path = downloader._construct_file_path(2022, "04", "orography")

    assert file_path.parent.name == "invariant"
    assert file_path.name == "barra_C2_20min_fx_orog.nc"
    assert "202204" not in file_path.name


def test_include_invariants_adds_invariant_variables(tmp_path: Path) -> None:
    """Test that include_invariants appends invariant fields in downloader."""
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2022],
        months=["04"],
        variables=["1.5m_temperature"],
        include_invariants=True,
    )

    assert "orography" in downloader.variables
    assert "land_sea_mask" in downloader.variables


def test_build_opendap_url_r2(tmp_path: Path) -> None:
    """Test OPeNDAP URL construction for R2 model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    url = downloader._build_opendap_url(2020, "06", "1.5m_temperature")
    assert "thredds.nci.org.au" in url
    assert "202006" in url
    # URL uses resolved BARRA code
    assert "tas" in url


def test_build_opendap_url_different_models(tmp_path: Path) -> None:
    """Test that URLs differ by model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_r2 = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    dl_c2 = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    url_r2 = dl_r2._build_opendap_url(2020, "01", "1.5m_temperature")
    url_c2 = dl_c2._build_opendap_url(2020, "01", "1.5m_temperature")
    assert url_r2 != url_c2


def test_build_opendap_url_invariant_uses_fx_path(tmp_path: Path) -> None:
    """Invariant variables should be fetched from fx path, not temporal folders."""
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="C2_20min",
        years=[2022],
        months=["04"],
        variables=["land_sea_mask"],
    )

    url = downloader._build_opendap_url(2022, "04", "land_sea_mask")

    assert "/fx/sftlf/latest/" in url
    assert "_v1.nc" in url
    assert "/20min/" not in url
    assert "202204" not in url


# ----------------------------------
# Tests - Configuration
# ----------------------------------
def test_r2_config(tmp_path: Path) -> None:
    """Test R2 configuration.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path, model="R2", years=[2020], variables=["1.5m_temperature"]
    )
    assert "R2" in downloader.config["label"]
    assert "11 km" in downloader.config["resolution"]
    assert "AUS-11" in downloader.config["grid"]


def test_c2_config(tmp_path: Path) -> None:
    """Test C2 configuration.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path, model="C2", years=[2020], variables=["1.5m_temperature"]
    )
    assert "C2" in downloader.config["label"]
    assert "4 km" in downloader.config["resolution"]
    assert "AUST-04" in downloader.config["grid"]


# ----------------------------------
# Tests - Variable listing
# ----------------------------------
def test_list_variables_r2(tmp_path: Path) -> None:
    """Test variable listing for R2 model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path, model="R2", years=[2020], variables=["1.5m_temperature"]
    )
    vars_list = downloader.list_variables()
    assert isinstance(vars_list, list)
    assert len(vars_list) > 0
    assert all(isinstance(v, str) for v in vars_list)
    assert "1.5m_temperature" in vars_list


def test_list_variables_c2_has_more(tmp_path: Path) -> None:
    """Test that C2 has at least as many variables as R2.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_r2 = BarraDownloader(
        output_path=tmp_path, model="R2", years=[2020], variables=["1.5m_temperature"]
    )
    dl_c2 = BarraDownloader(
        output_path=tmp_path, model="C2", years=[2020], variables=["1.5m_temperature"]
    )
    assert len(dl_c2.available_variables) >= len(dl_r2.available_variables)


# ----------------------------------
# Tests - Temporal resolution
# ----------------------------------
def test_temporal_res_defaults_to_1hr(tmp_path: Path) -> None:
    """Test that temporal resolution defaults to 1hr for all models.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    for model in ["R2", "C2"]:
        downloader = BarraDownloader(
            output_path=tmp_path,
            model=model,
            years=[2020],
            variables=["1.5m_temperature"],
        )
        assert downloader.temporal_res == "1hr"


def test_temporal_res_20min_c2(tmp_path: Path) -> None:
    """Test that C2_20min model key sets 20min temporal resolution.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="C2_20min",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    assert downloader.temporal_res == "20min"


def test_temporal_res_20min_rejected_for_r2(tmp_path: Path) -> None:
    """Test that selecting C2_20min differs from R2 temporal resolution.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    assert downloader.temporal_res == "1hr"


def test_temporal_res_invalid(tmp_path: Path) -> None:
    """Test that an unrecognized model key is rejected.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with pytest.raises(ValueError, match="Unknown BARRA model"):
        BarraDownloader(
            output_path=tmp_path,
            model="C2_invalid",
            years=[2020],
            variables=["1.5m_temperature"],
        )


def test_temporal_res_in_file_path(tmp_path: Path) -> None:
    """Test that model key controls temporal resolution in file paths.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_1hr = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    dl_20min = BarraDownloader(
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
    dl_1hr = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    dl_20min = BarraDownloader(
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
# Tests - Dry run
# ----------------------------------
def test_dry_run_flag(tmp_path: Path) -> None:
    """Test dry_run flag setting.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_dry = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
        dry_run=True,
    )
    assert dl_dry.dry_run is True

    dl_normal = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
        dry_run=False,
    )
    assert dl_normal.dry_run is False


def test_dry_run_completes_without_error(tmp_path: Path) -> None:
    """Test that a dry run workflow completes without errors.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["1.5m_temperature", "total_precipitation"],
        dry_run=True,
    )
    downloader.download_data()


# ----------------------------------
# Tests - Download data
# ----------------------------------
def test_download_data_skips_completed(tmp_path: Path) -> None:
    """Test that download_data skips tasks already in checkpoint.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    # Save a fake checkpoint marking all tasks as done
    checkpoint = {
        (2020, "01", "1.5m_temperature"): 1,
        (2020, "01", "total_precipitation"): 1,
    }
    checkpoint_path = Path(tmp_path, "R2", "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["1.5m_temperature", "total_precipitation"],
        resume=True,
    )

    with patch.object(downloader, "_download_variable") as mock_dl:
        downloader.download_data()
        mock_dl.assert_not_called()


def test_download_data_calls_download_variable(tmp_path: Path) -> None:
    """Test that download_data calls _download_variable for pending tasks.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["1.5m_temperature"],
        resume=False,
    )

    with patch.object(downloader, "_download_variable", return_value=1) as mock_dl:
        downloader.download_data()
        mock_dl.assert_called_once_with(
            year=2020, month="01", variable="1.5m_temperature"
        )


# ----------------------------------
# Tests - Multiple models independent
# ----------------------------------
def test_multiple_models_independent(tmp_path: Path) -> None:
    """Test that downloaders for different models are independent.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_r2 = BarraDownloader(
        output_path=tmp_path / "r2",
        model="R2",
        years=[2020],
        variables=["1.5m_temperature"],
    )
    dl_c2 = BarraDownloader(
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
def test_download_variable_skips_when_file_exists(downloader: BarraDownloader) -> None:
    """Test that existing output file is treated as successful and skipped."""
    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    output_file.write_bytes(b"already here")

    result = downloader._download_variable(2020, "01", "1.5m_temperature")

    assert result == 1


def test_download_variable_success_writes_file(downloader: BarraDownloader) -> None:
    """Test successful streamed download path and file creation."""
    mock_response = MagicMock()
    mock_response.headers = {"content-length": "4"}
    mock_response.iter_content.return_value = [b"ab", b"cd"]
    mock_response.raise_for_status.return_value = None

    with patch(
        "rbc.weather.barra.downloader.requests.get", return_value=mock_response
    ), patch("rbc.weather.barra.downloader.tqdm") as mock_tqdm:
        progress = MagicMock()
        mock_tqdm.return_value = progress

        result = downloader._download_variable(2020, "01", "1.5m_temperature")

    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert result == 1
    assert output_file.exists()
    assert output_file.read_bytes() == b"abcd"
    assert progress.update.call_count == 2
    progress.close.assert_called_once()


def test_download_variable_request_exception_removes_partial(
    downloader: BarraDownloader,
) -> None:
    """Test RequestException path returns failure and leaves no output file."""
    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert not output_file.exists()

    with patch(
        "rbc.weather.barra.downloader.requests.get",
        side_effect=requests.exceptions.RequestException("boom"),
    ):
        result = downloader._download_variable(2020, "01", "1.5m_temperature")

    assert result == 0
    assert not output_file.exists()


def test_download_variable_generic_exception_removes_partial(
    downloader: BarraDownloader,
) -> None:
    """Test generic exception path removes partially written output file."""

    def _broken_chunks(chunk_size: int):
        del chunk_size
        yield b"ab"
        raise RuntimeError("stream error")

    mock_response = MagicMock()
    mock_response.headers = {"content-length": "4"}
    mock_response.iter_content.side_effect = _broken_chunks
    mock_response.raise_for_status.return_value = None

    with patch(
        "rbc.weather.barra.downloader.requests.get", return_value=mock_response
    ), patch("rbc.weather.barra.downloader.tqdm") as mock_tqdm:
        mock_tqdm.return_value = MagicMock()
        result = downloader._download_variable(2020, "01", "1.5m_temperature")

    output_file = downloader._construct_file_path(2020, "01", "1.5m_temperature")
    assert result == 0
    assert not output_file.exists()


# ----------------------------------
# Tests - Catalog printing
# ----------------------------------
def test_print_available_variables_for_all_models(
    capsys: pytest.CaptureFixture,
) -> None:
    """Test static variable printing for all models."""
    BarraDownloader.print_available_variables("all")
    output = capsys.readouterr().out

    assert "AVAILABLE BARRA-R2 VARIABLES" in output
    assert "AVAILABLE BARRA-C2 VARIABLES" in output
    assert "AVAILABLE BARRA-C2_20min VARIABLES" in output
    assert "USAGE EXAMPLES:" in output


def test_print_available_variables_invalid_model_raises() -> None:
    """Test static variable printer rejects unknown model keys."""
    with pytest.raises(ValueError, match="Unknown BARRA model"):
        BarraDownloader.print_available_variables("X2")
