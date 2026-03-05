# tests/energy/test_utils.py
"""Tests for energy utility functions and classes."""

import pickle
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, cast
from unittest.mock import patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.utils import (
    MAX_RETRIES,
    DataStructureError,
    EnergyDownloader,
    InvalidError,
    load_df_from_file,
    write_df_to_csv,
)


# ----------------------------------
# Fixtures
# ----------------------------------
class MockDownloader(EnergyDownloader):
    """A dummy child class to test EnergyDownloader logic directly."""

    def _get_task_data(self, task: str | tuple[str, str]):
        """Dummy method to test EnergyDownloader._get_task_data function.

        Args:
            task (str | tuple[str, str]): Task for downloading.
        """
        pass


@pytest.fixture
def downloader(tmp_path: Path) -> MockDownloader:
    """Fixture to create an instance of EnergyDownloader.

    Args:
        tmp_path (Path): Path to temporary directory.

    Returns:
        MockDownloader: Instance of the mock EnergyDownloader child class.
    """
    return MockDownloader(output_path=tmp_path, years=[2020])


@pytest.fixture
def ckpt_setup(downloader: MockDownloader, tmp_path: Path) -> Callable:
    """Fixture to define a setup function for setting up the checkpoint file and path.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        tmp_path (Path): Path to temporary directory.

    Returns:
        Callable: Function that defines checkpoint setup for specific task.
    """

    def _setup(task: str | tuple[str, str], use_self_ckpt: bool) -> tuple[dict, Path]:
        """Function that defines checkpoint setup for specific task.

        Args:
            task (str | tuple[str, str]): Task for downloading.
            use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.

        Returns:
            tuple[dict, Path]: Checkpoint dictionary and checkpoint path.
        """
        if use_self_ckpt:
            d = cast(Any, downloader)  # prevents mypy complaining about missing attribs
            d.checkpoint_path = Path(tmp_path, "status.pickle")
            d.checkpoint = {}
            return d.checkpoint, d.checkpoint_path
        else:
            nested_path = Path(tmp_path, task[0], "status.pickle")
            nested_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure dir exists
            return {}, nested_path

    return _setup


# ----------------------------------
# Tests - EnergyDownloader
# ----------------------------------
@pytest.mark.parametrize(
    "task, use_self_ckpt",
    [("2020-01-01", True), (("ZONE_A", "2020-01-01"), False)],  # EIA/EPIAS, Entso-E
)
def test_threading_wrapper(
    downloader: MockDownloader,
    ckpt_setup: Callable,
    task: str | tuple[str, str],
    use_self_ckpt: bool,
) -> None:
    """Happy path for _threading_wrapper (and, inherently, _download_task_data).

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        ckpt_setup (Callable): Function that defined checkpoint setup for specific task.
        task (str | tuple[str, str]): Task for downloading.
        use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.
    """
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)

    with patch.object(downloader, "_get_task_data"):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task, checkpoint, checkpoint_path)

            assert checkpoint[task] == 1
            mock_save.assert_called_once_with(checkpoint, checkpoint_path)


@pytest.mark.parametrize(
    "task, use_self_ckpt",
    [("2020-01-01", True), (("ZONE_A", "2020-01-01"), False)],  # EIA/EPIAS, Entso-E
)
@pytest.mark.parametrize(
    "code, expected_status, expected_sleep_calls",
    [
        (None, 0, MAX_RETRIES - 1),
        (300, 0, MAX_RETRIES - 1),
        (404, 1, 0),
        (400, 1, 0),
    ],
)
def test_threading_error_catching(
    downloader: MockDownloader,
    ckpt_setup: Callable,
    task: str | tuple[str, str],
    use_self_ckpt: bool,
    code: int | None,
    expected_status: int,
    expected_sleep_calls: int,
) -> None:
    """Failure path suite for _threading_wrapper (and, inherently, _download_task_data).

    This test suite ensures that the various different errors that can be raised by
    _get_task_data and caught in _download_task_data are propagated correctly to
    _threading_wrapper and result in the correct resume logic.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        ckpt_setup (Callable): Function that defined checkpoint setup for specific task.
        task (str | tuple[str, str]): Task for downloading.
        use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.
        code (int | None): Status code for HTTPError logic.
        expected_status (int): Expected status for resuming logic.
        expected_sleep_calls (int): Expected number of times sleep is called.
    """
    # 1. Test error requiring immediate exit (DataStructureError / RateLimitError -> exit)
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    with patch("os._exit", side_effect=SystemExit) as mock_exit:
        with patch.object(downloader, "_get_task_data", side_effect=DataStructureError):
            with pytest.raises(SystemExit):
                downloader._threading_wrapper(task, checkpoint, checkpoint_path)

    mock_exit.assert_called_once_with(1)  # assert outside "with"-block for correct exec

    # 2. Test missing data (ValueError -> status 1)
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    with patch.object(downloader, "_get_task_data", side_effect=ValueError):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task, checkpoint, checkpoint_path)

            assert checkpoint[task] == 1
            mock_save.assert_called_once_with(checkpoint, checkpoint_path)

    # 3. Test HTTPError - no code: (->0), retry: code=300 (->0), missing: code=404 (->1), client: code=400 (->1)
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    with patch.object(
        downloader, "_get_task_data", side_effect=exceptions.HTTPError("")
    ):
        with patch.object(downloader, "_get_status_code", return_value=code):
            with patch("rbc.energy.utils.time.sleep") as mock_sleep:
                with patch.object(downloader, "_save_checkpoint") as mock_save:
                    downloader._threading_wrapper(task, checkpoint, checkpoint_path)

                    assert checkpoint[task] == expected_status
                    assert mock_sleep.call_count == expected_sleep_calls
                    mock_save.assert_called_once_with(checkpoint, checkpoint_path)

    # 4. Test other errors (that are not specifically handled in _download_task_data)
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    with patch.object(downloader, "_get_task_data", side_effect=Exception):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task, checkpoint, checkpoint_path)

            assert checkpoint[task] == 0
            mock_save.assert_called_once_with(checkpoint, checkpoint_path)


# ----------------------------------
# Tests - EnergyDownloader helper methods
# ----------------------------------
@pytest.mark.parametrize(
    "error, expected_return",
    [
        (SimpleNamespace(response=SimpleNamespace(status_code=404)), 404),  # requests
        (SimpleNamespace(code=503), 503),  # urllib
        (Exception("No attributes"), None),
    ],
)
def test_get_status_code(error: Exception, expected_return: str | None) -> None:
    """Happy path for _get_status_code with different inputs.

    Args:
        error (Exception): Exception from which to get the status code (if it exists).
        expected_return (str | None): Expected status code (None if error has no attributes).
    """
    assert MockDownloader._get_status_code(error) == expected_return


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


@pytest.mark.parametrize(
    "task, use_self_ckpt",
    [("2020-01-01", True), (("ZONE_A", "2020-01-01"), False)],  # EIA/EPIAS, Entso-E
)
def test_save_checkpoint(
    downloader: MockDownloader,
    ckpt_setup: Callable,
    task: str | tuple[str, str],
    use_self_ckpt: bool,
) -> None:
    """Happy path for _save_checkpoint with valid checkpoint setups.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        ckpt_setup (Callable): Function that defined checkpoint setup for specific task.
        task (str | tuple[str, str]): Task for downloading.
        use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.
    """
    _, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    checkpoint = {task: 1}
    downloader._save_checkpoint(checkpoint, checkpoint_path)

    assert checkpoint_path.is_file()
    with open(checkpoint_path, "rb") as f:
        assert pickle.load(f) == checkpoint


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


def test_get_month_list_current_year(downloader: MockDownloader) -> None:
    """Happy path for _get_month_list when current year is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    fake_today = pd.Timestamp("2025-02-01")

    with patch("pandas.Timestamp.now", return_value=fake_today):
        downloader.years = [2025]
        months = downloader._get_month_list()

        assert len(months) == 1
        assert months[-1] == "2025-01"


def test_get_year_list_current_year(downloader: MockDownloader) -> None:
    """Happy path for _get_year_list when current year is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    fake_today = pd.Timestamp("2025-02-01")

    with patch("pandas.Timestamp.now", return_value=fake_today):
        downloader.years = [2025]
        years = downloader._get_year_list()

        assert len(years) == 1
        assert years[-1] == "2025"


# ----------------------------------
# Tests - Other utils
# ----------------------------------
def test_write_df_to_csv_and_load_df_from_file(tmp_path: Path) -> None:
    """Happy path for _write_df_to_csv, ensuring writing / reading a dataframe to / from csv.

    Args:
        tmp_path (Path): Path to temporary directory.
    """
    non_csv_path = Path(tmp_path, "invalid.txt")
    csv_path = Path(tmp_path, "invalid.csv")
    mock_df = pd.DataFrame({"total": [16.2]})

    # check that writing df to csv works, with conversion to csv if incorrect suffix is given
    write_df_to_csv(mock_df, non_csv_path)
    assert not non_csv_path.exists()
    assert csv_path.is_file()

    # check that reading df from csv works
    read_df = load_df_from_file(csv_path)
    pd.testing.assert_frame_equal(read_df, mock_df)


def test_load_df_from_file_invalid_extension() -> None:
    """Failure path for "load_df_from_file" when file has unsupported extensions."""
    with pytest.raises(InvalidError, match="Invalid extension"):
        load_df_from_file("test.txt")


def test_load_df_from_file_not_found() -> None:
    """Failure path for "load_df_from_file" when file is missing."""
    with pytest.raises(InvalidError, match="Invalid path"):
        load_df_from_file("non_existent_file.csv")
        load_df_from_file("non_existent_file.xlsx")


def test_load_df_from_file_bad_args() -> None:
    """Failure path for "load_df_from_file" when pandas arguments are invalid (TypeError)."""
    with pytest.raises(InvalidError, match="Invalid argument"):
        load_df_from_file("test.csv", sheet_name="Sheet1")


def test_load_df_from_file_inaccessible_url() -> None:
    """Failure path for "load_df_from_file" when an inaccessible url is provided."""
    with patch(
        "rbc.energy.utils.pd.read_csv", side_effect=ConnectionError
    ) as mock_read_csv:
        with pytest.raises(ConnectionError):
            load_df_from_file("https://www.website.com/test.csv")

            mock_read_csv.assert_called_once()
