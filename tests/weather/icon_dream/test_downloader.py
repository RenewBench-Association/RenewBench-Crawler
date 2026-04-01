"""Tests for ICON-DREAM reanalysis data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

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
            dl = IconDreamDownloader(model="global", **basic_args)
    return dl


# ----------------------------------
# Tests - Initialization & Configuration
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

        downloader = IconDreamDownloader(model="global", **basic_args)

        assert downloader.years == basic_args["years"]
        assert downloader.months == basic_args["months"]
        assert downloader.variables == basic_args["variables"]
        assert downloader.dry_run == basic_args["dry_run"]
        assert downloader.resume == basic_args["resume"]
        assert downloader.output_path == Path(basic_args["output_path"], "global")
        assert downloader.checkpoint_path == Path(
            basic_args["output_path"], "global", "status.pickle"
        )


def test_connectivity_check_failure(tmp_path: Path) -> None:
    """Test that ConnectionError is raised when the DWD server is unreachable.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError("unreachable")

        with pytest.raises(ConnectionError, match="DWD server unreachable"):
            IconDreamDownloader(
                model="global",
                output_path=tmp_path,
                years=[2020],
                variables=["temperature"],
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
            model="global",
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
            model="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature", "u_component_of_wind"],
        )

        assert downloader.variables == ["temperature", "u_component_of_wind"]


def test_normalize_model_europe(tmp_path: Path) -> None:
    """Test that 'europe' model is normalized to 'eu'.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            model="europe",
            output_path=tmp_path,
            years=[2020],
            variables=["temperature"],
        )

        # Should normalize to 'eu'
        assert downloader.model == "eu"


def test_invalid_model_error(tmp_path: Path) -> None:
    """Test that invalid model raises ValueError.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with pytest.raises(ValueError, match="Unknown model"):
        IconDreamDownloader(
            model="invalid_model",
            output_path=tmp_path,
            years=[2020],
            variables=["temperature"],
        )


def test_downloader_initialization_multiple_years(tmp_path: Path) -> None:
    """Test that downloader correctly stores multiple years.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            model="global",
            output_path=tmp_path,
            years=[2020, 2021],
            months=["01", "02"],
            variables=["temperature"],
        )

        assert downloader.years == [2020, 2021]
        assert downloader.months == ["01", "02"]
        assert "temperature" in downloader.variables


def test_downloader_initialization_multiple_months(tmp_path: Path) -> None:
    """Test that downloader correctly stores multiple months.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            model="global",
            output_path=tmp_path,
            years=[2020],
            months=["01", "02", "03"],
            variables=["temperature"],
        )

        assert downloader.years == [2020]
        assert downloader.months == ["01", "02", "03"]
        assert "temperature" in downloader.variables


# ----------------------------------
# Tests - Checkpoint Handling
# ----------------------------------
def test_checkpoint_initialization_shape(downloader: IconDreamDownloader) -> None:
    """Test checkpoint structure upon initialization.

    Check that the checkpoint dict is initialized as empty on fresh start.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
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
    checkpoint = {(2020, "01", "temperature"): 1}
    checkpoint_path = Path(tmp_path, "global", "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/hourly/T/">T</a>'
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            model="global",
            output_path=tmp_path,
            years=[2020],
            months=["01"],
            variables=["temperature"],
            resume=True,
        )

        assert downloader.checkpoint == checkpoint


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
            model="global",
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
# Tests - Variable Discovery & Validation
# ----------------------------------
def test_discover_available_variables(downloader: IconDreamDownloader) -> None:
    """Test variable discovery from DWD.

    Check that available variables are correctly discovered from the DWD data server.

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
            model="global",
            output_path=tmp_path,
            years=[2020],
            variables=["temperature"],
        )

        # Should fall back to default variables
        assert len(downloader.available_variables) > 0
        assert "T" in downloader.available_variables


def test_variable_discovery_no_variables_found(tmp_path: Path) -> None:
    """Test fallback when no variables are found in DWD directory.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        # Return empty response (no variables found)
        mock_response = MagicMock()
        mock_response.text = "<html><body>No variables</body></html>"
        mock_get.return_value = mock_response

        downloader = IconDreamDownloader(
            model="global",
            output_path=tmp_path,
            years=[2020],
            variables=["temperature"],
        )

        # Should fall back to default variables
        assert len(downloader.available_variables) > 0


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
                model="global",
                output_path=tmp_path,
                years=[2020],
                variables=["INVALID_VAR"],
            )


def test_validate_variables_invalid_variable(tmp_path: Path) -> None:
    """Test that unavailable variables (not on DWD server) raise ValueError.

    Test that variables exist in our mapping but are not
    available on the DWD server should raise an error.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_response = MagicMock()
        # Mock server response with some variables, but NOT T_2M (which 2m_temperature maps to)
        mock_response.text = (
            '<a href="T/">T/</a>\n'
            '<a href="U/">U/</a>\n'
            '<a href="V/">V/</a>\n'
            '<a href="P/">P/</a>\n'
        )
        mock_get.return_value = mock_response

        with pytest.raises(ValueError, match="Variables not available on DWD server"):
            IconDreamDownloader(
                model="global",
                output_path=tmp_path,
                years=[2020],
                variables=[
                    "2m_temperature"
                ],  # Maps to T_2M, which is NOT in server response
            )


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
            model="global",
            output_path=tmp_path,
            years=[2020],
        )

        # Should use default variables (descriptive names, not codes)
        assert "temperature" in downloader.variables
        assert "2m_temperature" in downloader.variables


def test_get_dwd_param_fallback(downloader: IconDreamDownloader) -> None:
    """Test _get_dwd_param fallback for unmapped variables.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    result = downloader._get_dwd_param("unmapped_variable")
    assert result == "unmapped_variable"


# ----------------------------------
# Tests - Variable Download (Single File)
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


def test_download_variables_request_exception(downloader: IconDreamDownloader) -> None:
    """Test that request exceptions are handled properly.

    Check that _download_variables returns 0 when a RequestException occurs.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException("Network error")
        status = downloader._download_variables(
            year=2020, month="01", variable="temperature"
        )

    assert status == 0


def test_download_variables_general_exception(downloader: IconDreamDownloader) -> None:
    """Test that general exceptions are handled properly.

    Check that _download_variables returns 0 when a general exception occurs.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_get.side_effect = Exception("Unexpected error")
        status = downloader._download_variables(
            year=2020, month="01", variable="temperature"
        )

    assert status == 0


# ----------------------------------
# Tests - Data Download Workflow (Batch)
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
            model="global",
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
# Tests - Metadata Download
# ----------------------------------
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


def test_download_metadata_creates_directory(downloader: IconDreamDownloader) -> None:
    """Test that metadata download creates the metadata directory.

    Check that download_metadata creates the metadata subdirectory.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    metadata_dir = Path(downloader.output_path, "metadata")
    assert not metadata_dir.exists()

    downloader.download_metadata(dry_run=True)

    assert metadata_dir.exists()


def test_download_metadata_success(downloader: IconDreamDownloader) -> None:
    """Happy path for metadata file download.

    Check that download_metadata successfully downloads and saves metadata files.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    metadata_response = MagicMock()
    metadata_response.headers = {"content-length": "1000000"}
    metadata_response.iter_content = lambda chunk_size: iter([b"x" * 1000000])

    with patch(
        "rbc.weather.icon_dream.downloader.requests.get", return_value=metadata_response
    ):
        downloader.download_metadata(dry_run=False)

    metadata_dir = Path(downloader.output_path, "metadata")
    assert (metadata_dir / "icon_grid_0026_R03B07_G.nc").exists()
    assert (metadata_dir / "icon_grid_0026_R03B07_G-grfinfo.nc").exists()


def test_download_metadata_inherits_dry_run(downloader: IconDreamDownloader) -> None:
    """Test that download_metadata uses downloader's dry_run when not specified.

    Check that download_metadata respects the downloader's dry_run flag when not explicitly provided.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    downloader.dry_run = True

    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        # Call without dry_run argument - should inherit from downloader
        downloader.download_metadata(dry_run=None)

    mock_get.assert_not_called()


def test_download_metadata_size_mismatch_redownload(
    downloader: IconDreamDownloader,
) -> None:
    """Test that metadata files are re-downloaded when size differs.

    Check that download_metadata detects size mismatches and re-downloads files when needed.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    metadata_dir = Path(downloader.output_path, "metadata")
    metadata_dir.mkdir(parents=True)
    existing_file = metadata_dir / "icon_grid_0026_R03B07_G.nc"
    existing_content = "small"
    existing_file.write_text(existing_content)

    download_response = MagicMock()
    download_response.headers = {"content-length": "999999"}
    download_response.iter_content = lambda chunk_size: iter([b"x" * 999999])

    with patch(
        "rbc.weather.icon_dream.downloader.requests.get", return_value=download_response
    ):
        with patch("rbc.weather.icon_dream.downloader.requests.head") as mock_head:
            head_response = MagicMock()
            head_response.headers = {
                "content-length": "999999"
            }  # Different from actual file
            mock_head.return_value = head_response

            downloader.download_metadata(dry_run=False)

    assert existing_file.stat().st_size > len(existing_content)


def test_download_metadata_download_exception(downloader: IconDreamDownloader) -> None:
    """Test that download_metadata handles exceptions during download.

    Check that download_metadata gracefully handles exceptions without raising errors.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    with patch("rbc.weather.icon_dream.downloader.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException("Download failed")
        # Should not raise, just log error
        downloader.download_metadata(dry_run=False)


def test_download_metadata_existing_file_matching_size_is_skipped(
    downloader: IconDreamDownloader,
) -> None:
    """Test that an existing metadata file with matching remote size is skipped.

    Both metadata files are pre-created in the correct directory
    (downloader.output_path/metadata). The HEAD response returns a content-length
    matching the local file size, so the skip branch is exercised.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    metadata_dir = Path(downloader.output_path, "metadata")
    metadata_dir.mkdir(parents=True)
    existing_content = b"test_metadata_content"
    file1 = metadata_dir / "icon_grid_0026_R03B07_G.nc"
    file2 = metadata_dir / "icon_grid_0026_R03B07_G-grfinfo.nc"
    file1.write_bytes(existing_content)
    file2.write_bytes(existing_content)

    with patch("rbc.weather.icon_dream.downloader.requests.head") as mock_head:
        head_response = MagicMock()
        head_response.raise_for_status.return_value = None
        head_response.headers = {"content-length": str(len(existing_content))}
        mock_head.return_value = head_response

        with patch("rbc.weather.icon_dream.downloader.logger.info") as mock_log:
            downloader.download_metadata(dry_run=False)

    assert file1.read_bytes() == existing_content
    assert file2.read_bytes() == existing_content
    logged = " ".join(str(c.args[0]) for c in mock_log.call_args_list)
    assert "already exists with matching size" in logged


def test_download_metadata_head_request_exception_preserves_existing_file(
    downloader: IconDreamDownloader,
) -> None:
    """Test that a RequestException during HEAD verification keeps the existing file intact.

    Both metadata files are pre-created in downloader.output_path/metadata. The HEAD
    request raises a RequestException for each file, triggering the except branch
    that logs a warning and skips (continue) without re-downloading.

    Args:
        downloader (IconDreamDownloader): Instance of IconDreamDownloader.
    """
    metadata_dir = Path(downloader.output_path, "metadata")
    metadata_dir.mkdir(parents=True)
    existing_content = b"preserved_content"
    file1 = metadata_dir / "icon_grid_0026_R03B07_G.nc"
    file2 = metadata_dir / "icon_grid_0026_R03B07_G-grfinfo.nc"
    file1.write_bytes(existing_content)
    file2.write_bytes(existing_content)

    with patch("rbc.weather.icon_dream.downloader.requests.head") as mock_head:
        mock_head.side_effect = requests.exceptions.RequestException("HEAD failed")
        downloader.download_metadata(dry_run=False)

    assert file1.read_bytes() == existing_content
    assert file2.read_bytes() == existing_content


# ----------------------------------
# Tests - Utility & Display Functions
# ----------------------------------
def test_print_available_variables() -> None:
    """Test print_available_variables static method.

    Check that print_available_variables executes without errors.
    """
    with patch("rbc.weather.icon_dream.downloader.logger.info"):
        IconDreamDownloader.print_available_variables()
        # Should not raise any exception


def test_print_available_variables_all_models() -> None:
    """Test print_available_variables with 'all' models.

    Check that print_available_variables prints variables for all models.
    """
    with patch("rbc.weather.icon_dream.downloader.logger.info") as mock_log:
        IconDreamDownloader.print_available_variables(model="all")
        # Should log one block for global, one for eu, and one usage block
        assert mock_log.call_count == 3
