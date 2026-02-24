# tests/energy/test_utils.py
"""Tests for energy utility functions and classes."""

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from rbc.energy.utils import DailyDownloader, DataStructureError, write_df_to_csv


# ----------------------------------
# Fixtures
# ----------------------------------
class MockDownloader(DailyDownloader):
    """A dummy child class to test DailyDownloader logic directly."""

    def _get_task_data(self, task: str | tuple[str, str]):
        """Dummy method to test DailyDownloader._get_task_data function.

        Args:
            task (str | tuple[str, str]): Task for downloading.
        """
        pass


@pytest.fixture
def downloader(tmp_path) -> MockDownloader:
    """Fixture to create an instance of DailyDownloader.

    Args:
        tmp_path (Path): Path to temporary directory.

    Returns:
        MockDownloader: Instance of the mock DailyDownloader child class.
    """
    return MockDownloader(output_path=tmp_path, years=[2020])


# ----------------------------------
# Tests - DailyDownloader
# ----------------------------------
@pytest.mark.parametrize(
    "task, use_self_ckpt",
    [
        ("2020-01-01", True),  # Example for EIA/EPIAS
        (("ZONE_A", "2020-01-01"), False),  # Example for Entso-E
    ],
)
def test_threading_wrapper_error_catching(
    downloader: MockDownloader,
    tmp_path: Path,
    task: str | tuple[str, str],
    use_self_ckpt: bool,
) -> None:
    """Failure path suite for _threading_wrapper to check that different errors are caught.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        tmp_path (Path): Path to temporary directory.
        task (str | tuple[str, str]): Task for downloading.
        use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.
    """

    def get_state():
        # Define which state to use
        if use_self_ckpt:
            downloader.checkpoint_path = Path(tmp_path, "status.pickle")
            downloader.checkpoint = {}
            return downloader.checkpoint, downloader.checkpoint_path
        else:
            nested_path = Path(tmp_path, task[0], "status.pickle")
            nested_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure dir exists
            local_checkpoint = {}
            return local_checkpoint, nested_path

    # 1. Test missing data (ValueError -> status 1)
    checkpoint, checkpoint_path = get_state()
    with patch.object(downloader, "_get_task_data", side_effect=ValueError):
        downloader._threading_wrapper(task, checkpoint, checkpoint_path)
        assert checkpoint[task] == 1

    # 2. Test connection issues (ConnectionError -> status 0)
    checkpoint, checkpoint_path = get_state()
    with patch.object(downloader, "_get_task_data", side_effect=ConnectionError):
        with patch("rbc.energy.utils.time.sleep"):
            with patch.object(downloader, "_save_checkpoint") as mock_save:
                downloader._threading_wrapper(task, checkpoint, checkpoint_path)
                assert checkpoint[task] == 0
                mock_save.assert_called_once_with(checkpoint, checkpoint_path)

    # 3. Test data structure changes (DataStructureError -> exit)
    checkpoint, checkpoint_path = get_state()
    with patch("os._exit", side_effect=SystemExit) as mock_exit:
        with patch.object(downloader, "_get_task_data", side_effect=DataStructureError):
            with pytest.raises(SystemExit):
                downloader._threading_wrapper(task, checkpoint, checkpoint_path)
    # the assert needs to be outside the with-block to be sure it executes properly
    mock_exit.assert_called_once_with(1)


# ----------------------------------
# Tests - DailyDownloader helper methods
# ----------------------------------
@pytest.mark.parametrize(
    "valid_input, expected_csv",
    [("str", Path("str.csv")), (("str1", "str2"), Path("str1", "str2.csv"))],
)
def test_get_csv_path(
    downloader: MockDownloader, valid_input: str | tuple[str, str], expected_csv: Path
) -> None:
    """Happy path for _get_csv_path when valid inputs are provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        valid_input (str | tuple[str, str]): Valid input for _get_csv_path.
        expected_csv (str): Expected csv path name.
    """
    path = downloader._get_csv_path(valid_input)
    assert str(expected_csv) in str(path)


@pytest.mark.parametrize("invalid_input", [12345, ("first", "second", "third")])
def test_get_csv_path_invalid_task(
    downloader: MockDownloader, invalid_input: Any
) -> None:
    """Failure path for _get_csv_path when invalid task is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        invalid_input (Any): Invalid input for _get_csv_path.
    """
    with pytest.raises(ValueError, match="Unsupported task format"):
        downloader._get_csv_path(invalid_input)


def test_load_checkpoint_corrupted(downloader: MockDownloader) -> None:
    """Failure path for _load_checkpoint when status.pickle is corrupted.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    path = Path(downloader.output_path, "status.pickle")
    path.write_text("corrupted data")

    result = downloader._load_checkpoint(path)
    assert result == {}


def test_get_date_list_current_year(downloader: MockDownloader) -> None:
    """Happy path for _get_date_list when current year is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    fake_today = pd.Timestamp("2025-02-01")

    with patch("pandas.Timestamp.now", return_value=fake_today):
        downloader.years = [2025]
        dates = downloader._get_date_list()

        assert len(dates) == 31
        assert dates[-1] == "2025-01-31"


def test_get_date_list_future_years(downloader: MockDownloader) -> None:
    """Happy path for _get_date_list when future years are provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    downloader.years = [datetime.now().year + 1]

    with pytest.raises(ValueError, match="lie in the future"):
        downloader._get_date_list()


# ----------------------------------
# Tests - Other utils
# ----------------------------------
def test_write_df_to_csv_no_csv(tmp_path: Path) -> None:
    """Happy path for _write_df_to_csv when provided non-csv file is converted for usage.

    Args:
        tmp_path (Path): Path to temporary directory.
    """
    non_csv_path = Path(tmp_path, "invalid")
    mock_df = pd.DataFrame({"total": [16.2]})

    write_df_to_csv(mock_df, non_csv_path)
    assert not non_csv_path.exists()

    csv_path = Path(tmp_path, "invalid.csv")
    assert csv_path.is_file()

    read_df = pd.read_csv(csv_path)
    pd.testing.assert_frame_equal(read_df, mock_df)
