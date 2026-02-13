"""Tests for ICON-DREAM reanalysis data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rbc.weather.icon_dream import IconDreamDownloader


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def tmp_output_path(tmp_path: Path) -> Path:
    """Temporary output directory."""
    return tmp_path


@pytest.fixture
def basic_args(tmp_output_path: Path) -> dict:
    """Basic initialization arguments."""
    return {
        "output_path": tmp_output_path,
        "years": [2020],
        "months": ["01"],
        "variables": ["temperature"],
        "dry_run": False,
        "resume": False,
    }


@pytest.fixture
def downloader(basic_args: dict) -> IconDreamDownloader:
    """Initialize IconDreamDownloader with mocked requests."""
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
    """Test basic initialization."""
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


def test_downloader_initialization_default_months(tmp_output_path: Path) -> None:
    """Test initialization with default months (all 12)."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
        )

        assert len(downloader.months) == 12
        assert downloader.months[0] == "01"
        assert downloader.months[-1] == "12"


def test_downloader_initialization_custom_variables(tmp_output_path: Path) -> None:
    """Test initialization with custom variables."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a><a href="/hourly/U/">U</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
            months=["01"],
            variables=["temperature", "u_component_of_wind"],
        )

        assert downloader.variables == ["temperature", "u_component_of_wind"]


# ----------------------------------
# Tests - Checkpoint handling
# ----------------------------------
def test_checkpoint_initialization_shape(basic_args: dict) -> None:
    """Test checkpoint has correct shape."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(region="global", **basic_args)

        # Shape should be (years, months, variables)
        expected_shape = (
            len(basic_args["years"]),
            len(basic_args["months"]),
            len(basic_args["variables"]),
        )
        assert downloader.checkpoint.shape == expected_shape


def test_checkpoint_resume(tmp_output_path: Path) -> None:
    """Test checkpoint resume functionality."""
    # Save a fake checkpoint file
    checkpoint = np.ones((1, 1, 1))
    checkpoint_path = Path(tmp_output_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            resume=True,
        )

        np.testing.assert_array_equal(downloader.checkpoint, checkpoint)


def test_checkpoint_no_resume_fresh_start(tmp_output_path: Path) -> None:
    """Test that checkpoint is reset when resume=False."""
    # Save a checkpoint file
    old_checkpoint = np.ones((2, 2, 2))
    checkpoint_path = Path(tmp_output_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(old_checkpoint, f)

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            resume=False,  # Don't resume
        )

        # Should be fresh zeros, not the old checkpoint
        assert downloader.checkpoint.shape == (1, 1, 1)
        np.testing.assert_array_equal(downloader.checkpoint, np.zeros((1, 1, 1)))


# ----------------------------------
# Tests - Variable validation
# ----------------------------------
def test_validate_variables_valid(downloader: IconDreamDownloader) -> None:
    """Test validation of valid variables."""
    # Should not raise any exception
    downloader._validate_variables()


def test_validate_variables_invalid(tmp_output_path: Path) -> None:
    """Test validation with invalid variable."""
    with pytest.raises(ValueError, match="Invalid variables"):
        with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = '<a href="/hourly/T/">T</a>'
            mock_get.return_value = mock_response

            IconDreamDownloader(
                region="global",
                output_path=tmp_output_path,
                years=[2020],
                variables=["INVALID_VAR"],
            )


# ----------------------------------
# Tests - Variable discovery
# ----------------------------------
def test_discover_available_variables(downloader: IconDreamDownloader) -> None:
    """Test variable discovery from DWD."""
    assert "T" in downloader.available_variables
    assert "U" in downloader.available_variables


def test_discover_available_variables_fallback(tmp_output_path: Path) -> None:
    """Test variable discovery fallback when request fails."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_get.side_effect = Exception("Network error")

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
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
    """Test _download_variables in dry-run mode."""
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
    """Test _download_variables when file already exists."""
    # Create a dummy file
    dummy_file = downloader.output_path / "ICON-DREAM-Global_202001_T_hourly.grb"
    dummy_file.write_text("dummy content")

    status = downloader._download_variables(
        year=2020, month="01", variable="temperature"
    )

    assert status == 1


def test_download_variables_success(downloader: IconDreamDownloader) -> None:
    """Test _download_variables with successful download."""
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
            downloader.output_path / "ICON-DREAM-Global_202001_T_hourly.grb"
        ).exists()


def test_download_variables_network_error(
    downloader: IconDreamDownloader,
) -> None:
    """Test _download_variables with network error."""
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
    """Test download_data with single file."""
    with patch.object(downloader, "_download_variables") as mock_download:
        mock_download.return_value = 1

        downloader.download_data()

        # Should call _download_variables for each combination
        assert mock_download.called


def test_download_data_respects_checkpoint(
    downloader: IconDreamDownloader,
) -> None:
    """Test that download_data respects checkpoint."""
    # Mark first file as already downloaded
    downloader.checkpoint[0, 0, 0] = 1

    with patch.object(downloader, "_download_variables") as mock_download:
        downloader.download_data()

        # Should not call _download_variables since checkpoint is already 1
        assert not mock_download.called


def test_download_data_multiple_variables(tmp_output_path: Path) -> None:
    """Test download_data with multiple variables."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a><a href="/hourly/U/">U</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
            months=["01"],
            variables=["temperature", "u_component_of_wind"],
        )

        with patch.object(downloader, "_download_variables") as mock_download:
            mock_download.return_value = 1
            downloader.download_data()

            # Should be called twice (T and U)
            assert mock_download.call_count == 2


# ----------------------------------
# Tests - Checkpoint saving
# ----------------------------------
def test_checkpoint_saved_to_disk(downloader: IconDreamDownloader) -> None:
    """Test that checkpoint is saved to disk."""
    downloader._save_checkpoint()

    assert downloader.checkpoint_path.exists()

    # Load and verify
    with open(downloader.checkpoint_path, "rb") as f:
        loaded = pickle.load(f)
    np.testing.assert_array_equal(loaded, downloader.checkpoint)


# ----------------------------------
# Tests - Utility methods
# ----------------------------------
def test_print_available_variables() -> None:
    """Test print_available_variables method."""
    with patch("builtins.print"):
        IconDreamDownloader.print_available_variables()
        # Should not raise any exception


def test_get_default_variables(tmp_output_path: Path) -> None:
    """Test _get_default_variables returns default."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
        )

        # Should use default variables (descriptive names, not codes)
        assert "temperature" in downloader.variables
        assert "2m_temperature" in downloader.variables


# ----------------------------------
# Tests - Multi-year/month scenarios
# ----------------------------------
def test_multi_year_download(tmp_output_path: Path) -> None:
    """Test download with multiple years."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020, 2021],
            months=["01", "02"],
            variables=["temperature"],
        )

        # Checkpoint should have 2 years x 2 months x 1 variable
        assert downloader.checkpoint.shape == (2, 2, 1)


def test_multi_month_download(tmp_output_path: Path) -> None:
    """Test download with multiple months."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
            months=["01", "02", "03"],
            variables=["temperature"],
        )

        # Checkpoint should have 1 year x 3 months x 1 variable
        assert downloader.checkpoint.shape == (1, 3, 1)


def test_download_metadata_dry_run(downloader: IconDreamDownloader) -> None:
    """Test metadata download in dry-run mode."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        downloader.download_metadata(dry_run=True)
        # No actual requests should be made in dry-run mode
        mock_get.assert_not_called()


def test_download_metadata_creates_directory(tmp_output_path: Path) -> None:
    """Test that metadata download creates the metadata directory."""
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            region="global",
            output_path=tmp_output_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            dry_run=False,
        )

        # Metadata directory should not exist yet
        metadata_dir = tmp_output_path / "metadata"
        assert not metadata_dir.exists()

        # Run metadata download in dry-run to avoid actual downloads
        downloader.download_metadata(dry_run=True)

        # Directory should be created
        assert metadata_dir.exists()


def test_download_metadata_success(tmp_output_path: Path) -> None:
    """Test successful metadata file download."""
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
            output_path=tmp_output_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            dry_run=False,
        )

        # Download metadata
        downloader.download_metadata(dry_run=False)

        # Verify metadata files were created
        metadata_dir = tmp_output_path / "metadata"
        assert (metadata_dir / "icon_grid_0026_R03B07_G.nc").exists()
        assert (metadata_dir / "icon_grid_0026_R03B07_G-grfinfo.nc").exists()


def test_download_metadata_file_exists(tmp_output_path: Path) -> None:
    """Test that existing metadata files are skipped."""
    # Create metadata directory and a file
    metadata_dir = tmp_output_path / "metadata"
    metadata_dir.mkdir()
    existing_file = metadata_dir / "icon_grid_0026_R03B07_G.nc"
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
                output_path=tmp_output_path,
                years=[2020],
                months=["01"],
                variables=["temperature"],
                dry_run=False,
            )

            # Download metadata
            downloader.download_metadata(dry_run=False)

            # Existing file should not be modified
            assert existing_file.read_text() == existing_content
