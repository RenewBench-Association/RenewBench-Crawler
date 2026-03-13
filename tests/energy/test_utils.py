# tests/energy/test_utils.py
"""Tests for energy utility functions and classes."""

import pickle
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
    DownloadKey,
    EnergyDownloader,
    InvalidError,
    load_df_from_file,
    write_df_to_csv,
)

# ----------------------------------
# Fixtures
# ----------------------------------
TASK_DAY = DownloadKey(date="2020-01-01")
TASK_YESTERDAY = DownloadKey(
    date=(pd.Timestamp.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
)


class MockDownloader(EnergyDownloader):
    """A dummy child class to test EnergyDownloader logic directly."""

    def _get_task_data(self, task: DownloadKey):
        """Dummy method to test EnergyDownloader._get_task_data function.

        Args:
            task (DownloadKey): The metadata for a task to download data for.
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

    def _setup(task: DownloadKey, use_self_ckpt: bool) -> tuple[dict, Path]:
        """Function that defines checkpoint setup for specific task.

        Args:
            task (DownloadKey): The metadata for a task to download data for.
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
            nested_path = downloader._build_checkpoint_path(
                DownloadKey(
                    temporal_resolution=task.temporal_resolution,
                    bidding_zone=task.bidding_zone,
                )
            )
            nested_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure dir exists
            return {}, nested_path

    return _setup


# ----------------------------------
# Tests - EnergyDownloader
# ----------------------------------
@pytest.mark.parametrize(
    "task, use_self_ckpt",
    [
        (TASK_DAY, True),  # EIA/EPIAS
        (TASK_DAY.update(bidding_zone="ZONE_A"), False),  # Entso-E
    ],
)
def test_threading_wrapper(
    downloader: MockDownloader,
    ckpt_setup: Callable,
    task: DownloadKey,
    use_self_ckpt: bool,
) -> None:
    """Happy path for _threading_wrapper (and, inherently, _download_task_data).

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        ckpt_setup (Callable): Function that defined checkpoint setup for specific task.
        task (DownloadKey): The metadata for a task to download data for.
        use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.
    """
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    ckpt_key = downloader._turn_task_into_checkpoint_key(task)

    with patch.object(downloader, "_get_task_data"):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task, checkpoint, checkpoint_path)

            assert checkpoint[ckpt_key] == 1
            mock_save.assert_called_once_with(checkpoint, checkpoint_path)


@pytest.mark.parametrize(
    "task, use_self_ckpt, expected_valueerror_status",
    [
        (TASK_DAY, True, 1),  # for EIA/EPIAS/...
        (TASK_YESTERDAY, True, 0),
        (TASK_DAY.update(bidding_zone="ZONE_A"), False, 1),  # for Entso-E
        (TASK_YESTERDAY.update(bidding_zone="ZONE_A"), False, 0),
    ],
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
    task: DownloadKey,
    use_self_ckpt: bool,
    expected_valueerror_status: int,
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
        task (DownloadKey): The metadata for a task to download data for.
        use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.
        expected_valueerror_status (int): Expected ValueError status.
        code (int | None): Status code for HTTPError logic.
        expected_status (int): Expected status for resuming logic.
        expected_sleep_calls (int): Expected number of times sleep is called.
    """
    ckpt_key = downloader._turn_task_into_checkpoint_key(task)

    # 1. Test error requiring immediate exit (DataStructureError / RateLimitError -> exit)
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    with patch("os._exit", side_effect=SystemExit) as mock_exit:
        with patch.object(downloader, "_get_task_data", side_effect=DataStructureError):
            with pytest.raises(SystemExit):
                downloader._threading_wrapper(task, checkpoint, checkpoint_path)

    mock_exit.assert_called_once_with(1)  # assert outside "with"-block for correct exec

    # 2. Test missing data (ValueError -> status 0 = current year, status 1 = prior year)
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    with patch.object(downloader, "_get_task_data", side_effect=ValueError):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task, checkpoint, checkpoint_path)

            assert checkpoint[ckpt_key] == expected_valueerror_status
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

                    assert checkpoint[ckpt_key] == expected_status
                    assert mock_sleep.call_count == expected_sleep_calls
                    mock_save.assert_called_once_with(checkpoint, checkpoint_path)

    # 4. Test other errors (that are not specifically handled in _download_task_data)
    checkpoint, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    with patch.object(downloader, "_get_task_data", side_effect=Exception):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task, checkpoint, checkpoint_path)

            assert checkpoint[ckpt_key] == 0
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
    "task, expected_csv",
    [
        (TASK_DAY, Path("1h", "2020-01-01.csv")),
        (TASK_DAY.update(bidding_zone="A"), Path("1h", "A", "2020-01-01.csv")),
        (TASK_DAY.update(temporal_resolution="5min"), Path("5min", "2020-01-01.csv")),
    ],
)
def test_build_task_path(
    downloader: MockDownloader, task: DownloadKey, expected_csv: Path
) -> None:
    """Happy path for _build_task_path when valid inputs are provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        task (DownloadKey): Valid DownloadKey for _build_task_path.
        expected_csv (str): Expected csv path name.
    """
    path = downloader._build_task_path(task)
    assert str(expected_csv) in str(path)


def test_build_task_path_invalid_task(downloader: MockDownloader) -> None:
    """Failure path for _build_task_path when invalid task is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    invalid_task = DownloadKey()
    with pytest.raises(AttributeError, match="Required attribute 'date'"):
        downloader._build_task_path(invalid_task)


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
    [
        (TASK_DAY, True),  # EIA/EPIAS
        (TASK_DAY.update(bidding_zone="ZONE_A"), False),  # Entso-E
    ],
)
def test_save_checkpoint(
    downloader: MockDownloader,
    ckpt_setup: Callable,
    task: DownloadKey,
    use_self_ckpt: bool,
) -> None:
    """Happy path for _save_checkpoint with valid checkpoint setups.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        ckpt_setup (Callable): Function that defined checkpoint setup for specific task.
        task (DownloadKey): The metadata for a task to download data for.
        use_self_ckpt (bool): Whether to use class attribute (self.) for checkpointing.
    """
    _, checkpoint_path = ckpt_setup(task, use_self_ckpt)
    checkpoint = {downloader._turn_task_into_checkpoint_key(task): 1}
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
    downloader.years = [pd.Timestamp.now().year + 1]

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
    """Happy path for _write_df_to_csv, ensuring writing a dataframe to a csv works.

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


@pytest.mark.parametrize("file_name", ["valid.csv", "valid.xlsx"])
def test_load_df_from_file(tmp_path: Path, file_name) -> None:
    """Happy path for _load_df_from_file, ensuring reading a df from a csv / excel works.

    Args:
        tmp_path (Path): Path to temporary directory.
        file_name (str): Name of file.
    """
    file_path = Path(tmp_path, file_name)
    mock_df = pd.DataFrame({"total": [16.2]})

    if file_path.suffix == ".csv":
        mock_df.to_csv(file_path, index=False)
    else:
        pytest.importorskip("openpyxl")
        mock_df.to_excel(file_path, index=False)
    assert file_path.is_file()

    read_df = load_df_from_file(file_path)
    pd.testing.assert_frame_equal(read_df, mock_df)


def test_load_df_from_file_invalid_extension() -> None:
    """Failure path for "load_df_from_file" when file has unsupported extensions."""
    with pytest.raises(InvalidError, match="Invalid extension"):
        load_df_from_file("test.txt")


def test_load_df_from_file_not_found() -> None:
    """Failure path for "load_df_from_file" when file is missing."""
    with pytest.raises(InvalidError, match="Invalid path"):
        load_df_from_file("non_existent_file.csv")


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
