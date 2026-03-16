# tests/energy/test_utils.py
"""Tests for energy utility functions and classes."""

import pickle
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.utils import (
    MAX_RETRIES,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    InvalidError,
    MissingDataError,
    load_df_from_file,
    write_df_to_csv,
)

# ----------------------------------
# Fixtures
# ----------------------------------
TASK_DAY = DownloadTask(date="2020-01-01")
TASK_YESTERDAY = DownloadTask(
    date=(pd.Timestamp.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
)


class MockDownloader(EnergyDownloader):
    """A dummy child class to test EnergyDownloader logic directly."""

    def _get_task_data(self, task: DownloadTask) -> None:
        """Dummy method to test EnergyDownloader._get_task_data function.

        Args:
            task (DownloadTask): The metadata for a task to download data for.
        """
        pass


@pytest.fixture
def init_args(tmp_path: Path) -> dict:
    """Creates a basic setup with a temporary directory.

    Args:
        tmp_path (Path): Path to the temporary directory.

    Returns:
        dict: Initialisation arguments.
    """
    return {
        "output_path": tmp_path,
        "years": [2020],
    }


@pytest.fixture
def downloader(init_args: dict) -> EnergyDownloader:
    """Fixture to create an instance of EnergyDownloader.

    Args:
        init_args (dict): Arguments used to initialize an EnergyDownloader instance.

    Returns:
        EnergyDownloader: Instance of the mock EnergyDownloader child class.
    """
    return MockDownloader(
        output_path=init_args["output_path"], years=init_args["years"]
    )


# ----------------------------------
# Tests - EnergyDownloader
# ----------------------------------
def test_initialization(downloader: EnergyDownloader, init_args: dict) -> None:
    """Happy path for EnergyDownloader initialization.

    Args:
        downloader (EnergyDownloader): Instance of EnergyDownloader class.
        init_args (dict): Arguments used to initialize an EnergyDownloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


@pytest.mark.parametrize(
    "task",
    [TASK_DAY, TASK_DAY.update(bidding_zone="ZONE_A")],
)
def test_threading_wrapper(downloader: MockDownloader, task: DownloadTask) -> None:
    """Happy path for _threading_wrapper (and, inherently, _download_task_data).

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        task (DownloadTask): The metadata for a task to download data for.
    """
    with patch.object(downloader, "_download_task_data", return_value=1) as mock_dl:
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task)

            assert downloader.checkpoint[task.identifier] == 1
            mock_dl.assert_called_once_with(task=task)
            mock_save.assert_called_once()


def test_threading_wrapper_skip_existing_task(downloader: MockDownloader) -> None:
    """Happy path for _threading_wrapper when task exists from previous run and is skipped.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    downloader.checkpoint = {TASK_DAY.identifier: 1}

    with patch.object(downloader, "_download_task_data") as mock_dl:
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(TASK_DAY)

            mock_dl.assert_not_called()
            mock_save.assert_not_called()


@pytest.mark.parametrize(
    "task, expected_error_status",
    [
        (TASK_DAY, 1),  # for EIA/EPIAS/...
        (TASK_YESTERDAY, 0),
        (TASK_DAY.update(bidding_zone="ZONE_A"), 1),  # for Entso-E
        (TASK_YESTERDAY.update(bidding_zone="ZONE_A"), 0),
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
    task: DownloadTask,
    expected_error_status: int,
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
        task (DownloadTask): The metadata for a task to download data for.
        expected_error_status (int): Expected MissingDataError status.
        code (int | None): Status code for HTTPError logic.
        expected_status (int): Expected status for resuming logic.
        expected_sleep_calls (int): Expected number of times sleep is called.
    """
    downloader.checkpoint = {}

    # 1. Test error requiring immediate exit (DataStructureError / RateLimitError -> exit)
    with patch("os._exit", side_effect=SystemExit) as mock_exit:
        with patch.object(downloader, "_get_task_data", side_effect=DataStructureError):
            with pytest.raises(SystemExit):
                downloader._threading_wrapper(task)

    mock_exit.assert_called_once_with(1)  # assert outside "with"-block for correct exec

    # 2. Test missing data (MissingDataError -> status 0 = current year, status 1 = prior)
    downloader.checkpoint = {}
    with patch.object(downloader, "_get_task_data", side_effect=MissingDataError):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task)

            assert downloader.checkpoint[task.identifier] == expected_error_status
            mock_save.assert_called_once()

    # 3. Test HTTPError - no code: (->0), retry: code=300 (->0), missing: code=404 (->1), client: code=400 (->1)
    downloader.checkpoint = {}
    with patch.object(
        downloader, "_get_task_data", side_effect=exceptions.HTTPError("")
    ):
        with patch.object(downloader, "_get_status_code", return_value=code):
            with patch("rbc.energy.utils.time.sleep") as mock_sleep:
                with patch.object(downloader, "_save_checkpoint") as mock_save:
                    downloader._threading_wrapper(task)

                    assert downloader.checkpoint[task.identifier] == expected_status
                    assert mock_sleep.call_count == expected_sleep_calls
                    mock_save.assert_called_once()

    # 4. Test other errors (that are not specifically handled in _download_task_data)
    downloader.checkpoint = {}
    with patch.object(downloader, "_get_task_data", side_effect=Exception):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task)

            assert downloader.checkpoint[task.identifier] == 0
            mock_save.assert_called_once()


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
    downloader: MockDownloader, task: DownloadTask, expected_csv: Path
) -> None:
    """Happy path for _build_task_path when valid inputs are provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        task (DownloadTask): Valid DownloadTask for _build_task_path.
        expected_csv (str): Expected csv path name.
    """
    path = downloader._build_task_path(task)
    assert str(expected_csv) in str(path)


@pytest.mark.parametrize(
    "task",
    [TASK_DAY, TASK_DAY.update(bidding_zone="ZONE_A")],
)
def test_save_checkpoint(
    downloader: MockDownloader,
    task: DownloadTask,
) -> None:
    """Happy path for _save_checkpoint with valid checkpoint setups.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
        task (DownloadTask): The metadata for a task to download data for.
    """
    downloader.checkpoint = {task.identifier: 1}
    downloader._save_checkpoint()

    assert downloader.checkpoint_path.is_file()
    with open(downloader.checkpoint_path, "rb") as f:
        assert pickle.load(f) == downloader.checkpoint


def test_load_checkpoint(downloader: MockDownloader) -> None:
    """Happy path for _load_checkpoint.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    assert downloader.resume is True
    downloader.checkpoint = {"test": 1}
    downloader._save_checkpoint()

    result = downloader._load_checkpoint()
    assert result == {"test": 1}


def test_load_checkpoint_corrupted(downloader: MockDownloader) -> None:
    """Failure path for _load_checkpoint when status.pickle is corrupted.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    path = Path(downloader.output_path, "status.pickle")
    path.write_text("corrupted data")

    result = downloader._load_checkpoint()
    assert result == {}


def test_get_date_list_current_year(downloader: MockDownloader) -> None:
    """Happy path for _get_date_list when current year is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    with patch("pandas.Timestamp.now", return_value=pd.Timestamp("2025-02-01")):
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

    with pytest.raises(InvalidError, match="lie in the future"):
        downloader._get_date_list()


def test_get_month_list_current_year(downloader: MockDownloader) -> None:
    """Happy path for _get_month_list when current year is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    with patch("pandas.Timestamp.now", return_value=pd.Timestamp("2025-02-01")):
        downloader.years = [2025]
        months = downloader._get_month_list()

        assert len(months) == 1
        assert months[-1] == "2025-01"


def test_get_year_list_current_year(downloader: MockDownloader) -> None:
    """Happy path for _get_year_list when current year is provided.

    Args:
        downloader (MockDownloader): Instance of the MockDownloader class.
    """
    with patch("pandas.Timestamp.now", return_value=pd.Timestamp("2025-02-01")):
        downloader.years = [2025]
        years = downloader._get_year_list()

        assert len(years) == 1
        assert years[-1] == "2025"


# ----------------------------------
# Tests - DownloadTask class
# ----------------------------------
@pytest.mark.parametrize(
    "tres, bz",
    [(None, None), ("5min", None), (None, "ZONE_A"), ("5min", "ZONE_A")],
)
def test_downloadtask_initialise(tres: str | None, bz: str | None) -> None:
    """Happy path for initialising a DownloadTask instance.

    Args:
        tres (str): Valid temporal resolution.
        bz (str): Valid bidding zone.
    """
    date = "2020-01-01"
    all_args = {"date": date, "temporal_resolution": tres, "bidding_zone": bz}
    args = {k: v for k, v in all_args.items() if v is not None}
    task = DownloadTask(**args)

    exp_tres = tres if tres is not None else "1h"
    exp_bz = bz if bz is not None else None

    assert task.date == date
    assert task.temporal_resolution == exp_tres
    assert task.bidding_zone == exp_bz

    if bz is not None:
        assert (
            task.identifier
            == f"date={date}|temporal_resolution={exp_tres}|bidding_zone={bz}"
        )
    else:
        assert task.identifier == f"date={date}|temporal_resolution={exp_tres}"


@pytest.mark.parametrize("invalid_date", ["20200101", "invalid", ""])
def test_downloadtask_initialise_with_invalid_date(invalid_date: str) -> None:
    """Failure path for initialising a DownloadTask instance.

    Args:
        invalid_date (str): Invalid date.
    """
    with pytest.raises(ValueError, match="Invalid date / date format"):
        DownloadTask(date=invalid_date)


@pytest.mark.parametrize("invalid_tres", ["5days", "invalid", ""])
def test_downloadtask_initialise_with_invalid_tres(invalid_tres: str) -> None:
    """Failure path for initialising a DownloadTask instance.

    Args:
        invalid_tres (str): Invalid temporal resolution.
    """
    with pytest.raises(ValueError, match="Invalid temporal resolution"):
        DownloadTask(date="2020-01-01", temporal_resolution=invalid_tres)


def test_downloadtask_update() -> None:
    """Happy path for DownloadTask method "update"."""
    date = "2020-01-01"
    task = DownloadTask(date=date)

    new_date = "2020-02-01"
    new_task = task.update(
        date=new_date, temporal_resolution="10h", bidding_zone="ZONE_A"
    )

    assert task is not new_task
    assert task.date != new_date
    assert task.bidding_zone is None
    assert new_task.date == new_date
    assert new_task.temporal_resolution == "10h"
    assert new_task.bidding_zone == "ZONE_A"


def test_downloadtask_validate_required_fields() -> None:
    """Happy path for DownloadTask's "validate_required_fields"."""
    task = DownloadTask(date="2020-01-01", bidding_zone="ZONE_A")
    task.validate_required_fields("date", "temporal_resolution", "bidding_zone")


def test_downloadtask_validate_required_fields_value_missing() -> None:
    """Failure path for DownloadTask's "validate_required_fields" when value is missing."""
    task = DownloadTask(date="2020-01-01")
    with pytest.raises(ValueError, match="Required attribute 'bidding_zone' missing"):
        task.validate_required_fields("bidding_zone")


@pytest.mark.parametrize("empty_bz", [None, "", "   "])
def test_downloadtask_validate_required_fields_value_empty(
    empty_bz: None | str,
) -> None:
    """Failure path for DownloadTask's "validate_required_fields" when exists but is empty.

    Args:
        empty_bz (str): Empty definition of attribute 'bidding_zone'.
    """
    task = DownloadTask(date="2020-01-01", bidding_zone=empty_bz)
    with pytest.raises(ValueError, match="Required attribute 'bidding_zone' missing"):
        task.validate_required_fields("bidding_zone")


def test_downloadtask_validate_required_fields_field_not_an_attribute() -> None:
    """Failure path for DownloadTask's "validate_required_fields" for non-existent attribute."""
    task = DownloadTask(date="2020-01-01")
    with pytest.raises(AttributeError):
        task.validate_required_fields("invalid")


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
