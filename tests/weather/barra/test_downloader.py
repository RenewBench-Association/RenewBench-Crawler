# tests/weather/barra/test_downloader.py
"""Tests for BARRA reanalysis data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rbc.weather.barra import BarraDownloader
from rbc.weather.barra.mappings import (
    DEFAULT_VARIABLES_C2,
    DEFAULT_VARIABLES_R2_RE2,
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
        "variables": ["tas", "pr"],
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
    assert downloader.output_path == basic_args["output_path"]
    assert downloader.checkpoint_path == Path(
        basic_args["output_path"], "status.pickle"
    )


def test_downloader_initialization_re2(tmp_path: Path) -> None:
    """Happy path for initialization with RE2 model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="RE2",
        years=[2021],
        variables=["tas"],
    )
    assert downloader.model == "RE2"
    assert len(downloader.available_variables) > 0


def test_downloader_initialization_c2(tmp_path: Path) -> None:
    """Happy path for initialization with C2 model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2022],
        variables=["tas"],
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
            variables=["tas"],
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
        variables=["tas"],
    )
    assert output_path.exists()


def test_downloader_initialization_default_months(tmp_path: Path) -> None:
    """Test that all months are used by default.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["tas"],
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
    assert downloader.variables == DEFAULT_VARIABLES_R2_RE2


def test_downloader_initialization_default_variables_c2(tmp_path: Path) -> None:
    """Test that C2 uses correct default variables.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
    )
    assert downloader.variables == DEFAULT_VARIABLES_C2


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
        variables=["tas"],
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
    checkpoint = {(2020, "01", "tas"): 1}
    checkpoint_path = Path(tmp_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["tas"],
        resume=True,
    )
    assert downloader.checkpoint == checkpoint


def test_checkpoint_not_resumed_if_resume_false(tmp_path: Path) -> None:
    """Test that checkpoint is ignored when resume=False.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    # Save a fake checkpoint
    checkpoint = {(2020, "01", "tas"): 1}
    checkpoint_path = Path(tmp_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["tas"],
        resume=False,
    )
    assert downloader.checkpoint == {}


# ----------------------------------
# Tests - File path & URL construction
# ----------------------------------
def test_construct_file_path(downloader: BarraDownloader) -> None:
    """Test file path construction.

    Args:
        downloader (BarraDownloader): Instance of BarraDownloader class.
    """
    file_path = downloader._construct_file_path(2020, "01", "tas")
    assert file_path.parent == downloader.output_path
    assert "R2" in str(file_path)
    assert "202001" in str(file_path)
    assert "tas" in str(file_path)
    assert str(file_path).endswith(".nc")


def test_construct_file_path_different_vars(downloader: BarraDownloader) -> None:
    """Test file paths for different variables are distinct.

    Args:
        downloader (BarraDownloader): Instance of BarraDownloader class.
    """
    path1 = downloader._construct_file_path(2020, "01", "tas")
    path2 = downloader._construct_file_path(2020, "01", "pr")
    assert str(path1) != str(path2)
    assert "tas" in str(path1)
    assert "pr" in str(path2)


def test_build_opendap_url_r2(tmp_path: Path) -> None:
    """Test OPeNDAP URL construction for R2 model.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["tas"],
    )
    url = downloader._build_opendap_url(2020, "06", "tas")
    assert "thredds.nci.org.au" in url
    assert "202006" in url
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
        variables=["tas"],
    )
    dl_c2 = BarraDownloader(
        output_path=tmp_path,
        model="C2",
        years=[2020],
        variables=["tas"],
    )
    url_r2 = dl_r2._build_opendap_url(2020, "01", "tas")
    url_c2 = dl_c2._build_opendap_url(2020, "01", "tas")
    assert url_r2 != url_c2


# ----------------------------------
# Tests - Configuration
# ----------------------------------
def test_r2_config(tmp_path: Path) -> None:
    """Test R2 configuration.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path, model="R2", years=[2020], variables=["tas"]
    )
    assert "R2" in downloader.config["label"]
    assert "11 km" in downloader.config["resolution"]
    assert "AUS-11" in downloader.config["grid"]


def test_re2_config(tmp_path: Path) -> None:
    """Test RE2 configuration.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path, model="RE2", years=[2020], variables=["tas"]
    )
    assert "RE2" in downloader.config["label"]
    assert "22 km" in downloader.config["resolution"]
    assert "AUS-22" in downloader.config["grid"]


def test_c2_config(tmp_path: Path) -> None:
    """Test C2 configuration.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    downloader = BarraDownloader(
        output_path=tmp_path, model="C2", years=[2020], variables=["tas"]
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
        output_path=tmp_path, model="R2", years=[2020], variables=["tas"]
    )
    vars_list = downloader.list_variables()
    assert isinstance(vars_list, list)
    assert len(vars_list) > 0
    assert all(isinstance(v, str) for v in vars_list)
    assert "tas" in vars_list


def test_list_variables_c2_has_more(tmp_path: Path) -> None:
    """Test that C2 has at least as many variables as R2.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_r2 = BarraDownloader(
        output_path=tmp_path, model="R2", years=[2020], variables=["tas"]
    )
    dl_c2 = BarraDownloader(
        output_path=tmp_path, model="C2", years=[2020], variables=["tas"]
    )
    assert len(dl_c2.available_variables) >= len(dl_r2.available_variables)


# ----------------------------------
# Tests - Temporal frequency
# ----------------------------------
def test_temporal_frequency_always_1hr(tmp_path: Path) -> None:
    """Test that temporal frequency is fixed to 1hr for all models.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    for model in ["R2", "RE2", "C2"]:
        downloader = BarraDownloader(
            output_path=tmp_path, model=model, years=[2020], variables=["tas"]
        )
        assert downloader.temporal_res == "1hr"


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
        variables=["tas"],
        dry_run=True,
    )
    assert dl_dry.dry_run is True

    dl_normal = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        variables=["tas"],
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
        variables=["tas", "pr"],
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
    checkpoint = {(2020, "01", "tas"): 1, (2020, "01", "pr"): 1}
    checkpoint_path = Path(tmp_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    downloader = BarraDownloader(
        output_path=tmp_path,
        model="R2",
        years=[2020],
        months=["01"],
        variables=["tas", "pr"],
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
        variables=["tas"],
        resume=False,
    )

    with patch.object(downloader, "_download_variable", return_value=1) as mock_dl:
        downloader.download_data()
        mock_dl.assert_called_once_with(year=2020, month="01", variable="tas")


# ----------------------------------
# Tests - Discovery
# ----------------------------------
def test_discover_variables_returns_dict(downloader: BarraDownloader) -> None:
    """Test that discover_variables returns a dictionary.

    Args:
        downloader (BarraDownloader): Instance of BarraDownloader class.
    """
    with patch("rbc.weather.barra.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = "BARRA_R2_202001_tas.nc BARRA_R2_202001_pr.nc"
        mock_get.return_value = mock_response

        result = downloader.discover_variables()
        assert isinstance(result, dict)


def test_discover_variables_handles_error(downloader: BarraDownloader) -> None:
    """Test error handling in discover_variables.

    Args:
        downloader (BarraDownloader): Instance of BarraDownloader class.
    """
    with patch("rbc.weather.barra.downloader.requests.get") as mock_get:
        mock_get.side_effect = Exception("Connection error")
        result = downloader.discover_variables()
        assert result == {}


# ----------------------------------
# Tests - Multiple models independent
# ----------------------------------
def test_multiple_models_independent(tmp_path: Path) -> None:
    """Test that downloaders for different models are independent.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    dl_r2 = BarraDownloader(
        output_path=tmp_path / "r2", model="R2", years=[2020], variables=["tas"]
    )
    dl_re2 = BarraDownloader(
        output_path=tmp_path / "re2", model="RE2", years=[2020], variables=["tas"]
    )
    assert dl_r2.model == "R2"
    assert dl_re2.model == "RE2"
    assert dl_r2.output_path != dl_re2.output_path
