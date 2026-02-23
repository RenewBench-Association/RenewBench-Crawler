"""Tests for ICON-DREAM reanalysis data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import requests

from rbc.weather.icon_dream import IconDreamDownloader


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def basic_args(tmp_path: Path) -> dict:
    """Creates a basic setup with a temporary directory.

    Args:
        tmp_path (Path): Path to the temporary directory.

    Returns:
        dict: Initialization arguments for IconDreamDownloader.
    """
    return {
        "output_path": tmp_path,
        "years": [2020],
        "months": ["01"],
        "variables": ["temperature"],
        "dry_run": False,
        "resume": False,
    }


@pytest.fixture
def downloader(basic_args: dict) -> IconDreamDownloader:
    """Returns an instantiated IconDreamDownloader with mocked requests.

    Args:
        basic_args (dict): Basic initialization arguments.

    Returns:
        IconDreamDownloader: Instance of IconDreamDownloader class.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        # Mock the directory listing for variable discovery
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a><a href="/hourly/U/">U</a>'
        mock_get.return_value = mock_response

        with patch("rbc.weather.icon_dream.downloader.requests.head"):
            dl = IconDreamDownloader(region="global", **basic_args)
    return dl


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(basic_args: dict) -> None:
    """Happy path for class initialization.

    Check that IconDreamDownloader sets up paths and checkpoint correctly.

    Args:
        basic_args (dict): Initialization arguments for IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(region="global", **basic_args)

        assert downloader.years == basic_args["years"]
        assert downloader.months == basic_args["months"]
        assert downloader.variables == basic_args["variables"]
        assert downloader.dry_run == basic_args["dry_run"]
        assert downloader.resume == basic_args["resume"]
        assert downloader.output_path == basic_args["output_path"]
        assert downloader.checkpoint_path == Path(
            basic_args["output_path"], "status.pickle"
        )


def test_downloader_initialization_default_months(tmp_path: Path) -> None:
    """Test default month initialization.

    Check that IconDreamDownloader uses all 12 months when no months are specified.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
        )

        assert len(downloader.months) == 12
        assert downloader.months[0] == "01"
        assert downloader.months[-1] == "12"


def test_downloader_initialization_custom_variables(tmp_path: Path) -> None:
    """Test custom variable initialization.

    Check that IconDreamDownloader correctly stores custom variables.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a><a href="/hourly/U/">U</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature", "u_component_of_wind"],
        )

        assert downloader.variables == ["temperature", "u_component_of_wind"]


# ----------------------------------
# Tests - Checkpoint handling
# ----------------------------------
def test_checkpoint_initialization_shape(basic_args: dict) -> None:
    """Test checkpoint structure upon initialization.

    Check that the checkpoint dict is initialized as empty on fresh start.

    Args:
        basic_args (dict): Initialization arguments for IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(region="global", **basic_args)

        # Should be a dict, initialized as empty (lazy population)
        assert isinstance(downloader.checkpoint, dict)
        # On fresh init with no checkpoint file, it should be empty
        assert downloader.checkpoint == {}


def test_checkpoint_resume(tmp_path: Path) -> None:
    """Happy path for checkpoint resume functionality.

    Check that IconDreamDownloader correctly loads an existing checkpoint file.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    # Save a fake checkpoint file
    checkpoint = np.ones((1, 1, 1))
    checkpoint_path = Path(tmp_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            resume=True,
        )

        np.testing.assert_array_equal(downloader.checkpoint, checkpoint)


def test_checkpoint_no_resume_fresh_start(tmp_path: Path) -> None:
    """Test fresh start when resume is disabled.

    Check that IconDreamDownloader creates a new checkpoint when resume=False,
    even if an old checkpoint file exists.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    # Save a checkpoint file (old dict format)
    old_checkpoint = {2019: {"12": {"old_var": 1}}}
    checkpoint_path = Path(tmp_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(old_checkpoint, f)

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            resume=False,  # Don't resume
        )

        # Should be fresh checkpoint (empty dict on fresh start)
        assert isinstance(downloader.checkpoint, dict)
        assert downloader.checkpoint == {}
        # Old data should definitely not be present
        assert 2019 not in downloader.checkpoint


# ----------------------------------
# Tests - Variable validation
# ----------------------------------
def test_validate_variables_valid(downloader: IconDreamDownloader) -> None:
    """Test validation of valid variables.

    Check that no exception is raised for valid variables.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    # Should not raise any exception
    downloader._validate_variables()


def test_validate_variables_invalid(tmp_path: Path) -> None:
    """Test validation raises error for invalid variables.

    Check that ValueError is raised when requesting non-existent variables.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with pytest.raises(ValueError, match="Invalid variables"):
        with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = '<a href="/hourly/T/">T</a>'
            mock_get.return_value = mock_response

            IconDreamDownloader(
                region="global",
                output_path=tmp_path,
                years=[2020],
                variables=["INVALID_VAR"],
            )


# ----------------------------------
# Tests - Variable discovery
# ----------------------------------
def test_discover_available_variables(downloader: IconDreamDownloader) -> None:
    """Test variable discovery from DWD.

    Check that available variables are correctly discovered from the THREDDS catalog.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    assert "T" in downloader.available_variables
    assert "U" in downloader.available_variables


def test_discover_available_variables_fallback(tmp_path: Path) -> None:
    """Test variable discovery fallback when request fails.

    Check that default variables are used when DWD discovery fails.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_get.side_effect = Exception("Network error")

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            variables=["temperature"],
        )

        # Should fall back to default variables
        assert len(downloader.available_variables) > 0
        assert "T" in downloader.available_variables


# ----------------------------------
# Tests - Download functionality
# ----------------------------------
def test_download_variables_dry_run(downloader: IconDreamDownloader) -> None:
    """Test download in dry-run mode.

    Check that _download_variables returns success without making network requests.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    downloader.dry_run = True

    with patch("builtins.print"):
        status = downloader._download_variables(
            year=2020, month="01", variable="temperature"
        )

    assert status == 1
    # No actual network request should be made


def test_download_variables_already_exists(
    downloader: IconDreamDownloader,
) -> None:
    """Test download when file already exists.

    Check that _download_variables skips downloading if the file exists locally.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    # Create a dummy file
    dummy_file = Path(downloader.output_path, "ICON-DREAM-Global_202001_T_hourly.grb")
    dummy_file.write_text("dummy content")

    status = downloader._download_variables(
        year=2020, month="01", variable="temperature"
    )

    assert status == 1


def test_download_variables_success(downloader: IconDreamDownloader) -> None:
    """Happy path for successful data download.

    Check that _download_variables successfully downloads and saves a file.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        # Mock successful response
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "1000000"}
        mock_response.iter_content.return_value = [b"x" * 1000000]
        mock_get.return_value = mock_response

        status = downloader._download_variables(
            year=2020, month="01", variable="temperature"
        )

        assert status == 1
        # File should exist
        assert (
            Path(downloader.output_path, "ICON-DREAM-Global_202001_T_hourly.grb")
        ).exists()


def test_download_variables_network_error(
    downloader: IconDreamDownloader,
) -> None:
    """Test download error handling.

    Check that _download_variables returns 0 on network failure.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_get.side_effect = Exception("Network error")

        status = downloader._download_variables(
            year=2020, month="01", variable="temperature"
        )

        assert status == 0


# ----------------------------------
# Tests - Download data workflow
# ----------------------------------
def test_download_data_single_file(downloader: IconDreamDownloader) -> None:
    """Test download_data workflow with single file.

    Check that download_data correctly calls _download_variables.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    # Checkpoint starts empty, so download should be attempted
    with patch.object(downloader, "_download_variables") as mock_download:
        mock_download.return_value = 1

        downloader.download_data()

        # Should call _download_variables for each combination
        assert mock_download.called


def test_download_data_respects_checkpoint(
    downloader: IconDreamDownloader,
) -> None:
    """Test that download_data respects checkpoint.

    Check that already-downloaded files (marked in checkpoint) are skipped.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    # Mark first file as already downloaded using task tuple key
    task = (2020, "01", "temperature")
    downloader.checkpoint[task] = 1

    with patch.object(downloader, "_download_variables") as mock_download:
        downloader.download_data()

        # Should not call _download_variables since checkpoint is already 1
        assert not mock_download.called


def test_download_data_multiple_variables(tmp_path: Path) -> None:
    """Test download_data with multiple variables.

    Check that download_data processes each variable correctly.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a><a href="/hourly/U/">U</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature", "u_component_of_wind"],
        )

        # Checkpoint starts empty, so downloads should be attempted
        with patch.object(downloader, "_download_variables") as mock_download:
            mock_download.return_value = 1
            downloader.download_data()

            # Should be called twice (T and U)
            assert mock_download.call_count == 2


# ----------------------------------
# Tests - Utility methods
# ----------------------------------
def test_print_available_variables() -> None:
    """Test print_available_variables static method.

    Check that print_available_variables executes without errors.
    """
    with patch("builtins.print"):
        IconDreamDownloader.print_available_variables()
        # Should not raise any exception


def test_get_default_variables(tmp_path: Path) -> None:
    """Test that default variables are used when none specified.

    Check that IconDreamDownloader uses default variables on initialization.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
        )

        # Should use default variables (descriptive names, not codes)
        assert "temperature" in downloader.variables
        assert "2m_temperature" in downloader.variables


# ----------------------------------
# Tests - Multi-year/month scenarios
# ----------------------------------
def test_multi_year_download(tmp_path: Path) -> None:
    """Test download with multiple years.

    Check that downloader correctly initializes with multiple years.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020, 2021],
            months=["01", "02"],
            variables=["temperature"],
        )

        # Checkpoint should be an empty dict initially (lazy initialization)
        assert isinstance(downloader.checkpoint, dict)
        # Verify the downloader has correct parameters stored
        assert downloader.years == [2020, 2021]
        assert downloader.months == ["01", "02"]
        assert "temperature" in downloader.variables


def test_multi_month_download(tmp_path: Path) -> None:
    """Test download with multiple months.

    Check that downloader correctly initializes with multiple months.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            months=["01", "02", "03"],
            variables=["temperature"],
        )

        # Checkpoint should be an empty dict initially (lazy initialization)
        assert isinstance(downloader.checkpoint, dict)
        # Verify the downloader has correct parameters stored
        assert downloader.years == [2020]
        assert downloader.months == ["01", "02", "03"]
        assert "temperature" in downloader.variables


def test_download_metadata_dry_run(downloader: IconDreamDownloader) -> None:
    """Test metadata download in dry-run mode.

    Check that download_metadata does not make requests in dry-run mode.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        downloader.download_metadata(dry_run=True)
        # No actual requests should be made in dry-run mode
        mock_get.assert_not_called()


def test_download_metadata_creates_directory(tmp_path: Path) -> None:
    """Test that metadata download creates the metadata directory.

    Check that download_metadata creates the metadata subdirectory.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            dry_run=False,
        )

        # Metadata directory should not exist yet
        metadata_dir = Path(tmp_path, "metadata")
        assert not metadata_dir.exists()

        # Run metadata download in dry-run to avoid actual downloads
        downloader.download_metadata(dry_run=True)

        # Directory should be created
        assert metadata_dir.exists()


def test_download_metadata_success(tmp_path: Path) -> None:
    """Happy path for metadata file download.

    Check that download_metadata successfully downloads and saves metadata files.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        # Mock variable discovery
        discovery_response = MagicMock()
        discovery_response.text = '<a href="/hourly/T/">T</a>'

        # Mock metadata file download
        metadata_response = MagicMock()
        metadata_response.headers = {"content-length": "1000000"}
        metadata_response.iter_content = lambda chunk_size: iter([b"x" * 1000000])

        mock_get.side_effect = [
            discovery_response,
            metadata_response,
            metadata_response,
        ]

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            dry_run=False,
        )

        # Download metadata
        downloader.download_metadata(dry_run=False)

        # Verify metadata files were created
        metadata_dir = Path(tmp_path, "metadata")
        assert (Path(metadata_dir, "icon_grid_0026_R03B07_G.nc")).exists()
        assert (Path(metadata_dir, "icon_grid_0026_R03B07_G-grfinfo.nc")).exists()


def test_download_metadata_file_exists(tmp_path: Path) -> None:
    """Test that existing metadata files are skipped.

    Check that download_metadata skips files that already exist with matching size.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    # Create metadata directory and a file
    metadata_dir = Path(tmp_path, "metadata")
    metadata_dir.mkdir()
    existing_file = Path(metadata_dir, "icon_grid_0026_R03B07_G.nc")
    existing_content = "existing content"
    existing_file.write_text(existing_content)

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        with patch("rbc.weather.icon_dream.downloader.requests.head") as mock_head:
            discovery_response = MagicMock()
            discovery_response.text = '<a href="/hourly/T/">T</a>'
            mock_get.return_value = discovery_response

            # Mock HEAD request to return matching content-length
            head_response = MagicMock()
            head_response.headers = {"content-length": str(len(existing_content))}
            mock_head.return_value = head_response

            downloader = IconDreamDownloader(
                region="global",
                output_path=tmp_path,
                years=[2020],
                months=["01"],
                variables=["temperature"],
                dry_run=False,
            )

            # Download metadata
            downloader.download_metadata(dry_run=False)

            # Existing file should not be modified
            assert existing_file.read_text() == existing_content


def test_download_metadata_head_failure_keeps_file(tmp_path: Path) -> None:
    """Test that files are preserved when HEAD verification fails.

    Check that download_metadata keeps existing files if size verification fails.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    metadata_dir = Path(tmp_path, "metadata")
    metadata_dir.mkdir()
    existing_file = Path(metadata_dir, "icon_grid_0026_R03B07_G.nc")
    existing_content = "existing content"
    existing_file.write_text(existing_content)

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        with patch("rbc.weather.icon_dream.downloader.requests.head") as mock_head:
            discovery_response = MagicMock()
            discovery_response.text = '<a href="/hourly/T/">T</a>'
            mock_get.return_value = discovery_response
            mock_head.side_effect = requests.exceptions.RequestException("HEAD failed")

            downloader = IconDreamDownloader(
                region="global",
                output_path=tmp_path,
                years=[2020],
                months=["01"],
                variables=["temperature"],
                dry_run=False,
            )

            downloader.download_metadata(dry_run=False)

            assert existing_file.read_text() == existing_content
            assert any(
                call.args[0].endswith("icon_grid_0026_R03B07_G-grfinfo.nc")
                for call in mock_get.call_args_list
            )
