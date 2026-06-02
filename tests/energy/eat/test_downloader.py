# tests/energy/eat/test_downloader.py
"""Tests for EAT energy data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.eat import EatDownloader
from rbc.energy.eat.downloader import EXPECTED_COLS
from rbc.energy.utils import DataStructureError, DownloadTask, MissingDataError


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def init_args(tmp_path: Path) -> dict:
    """Creates a basic setup with a temporary directory.

    Args:
        tmp_path (Path): Path to the temporary directory.

    Returns:
        dict: initialization arguments.
    """
    return {
        "output_path": tmp_path,
        "years": [2020],
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> EatDownloader:
    """Provides an EatDownloader instance with a mocked, positive return code response.

    Args:
        init_args (dict): Arguments used to initialize an EatDownloader instance.

    Returns:
        EatDownloader: EatDownloader instance.
    """
    with patch("rbc.energy.eat.downloader.requests.head") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        return EatDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize an EatDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01", temporal_resolution="30min")


def get_mock_df(specific_task: DownloadTask) -> pd.DataFrame:
    """Gets a mock dataframe for a specific task.

    Args:
        specific_task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

    Returns:
        pandas.DataFrame: Mock dataframe.
    """
    data = {}

    for col in EXPECTED_COLS:
        if col == "trading_date":
            data[col] = specific_task.date
        elif col.startswith("tp"):
            data[col] = "10"
        else:
            data[col] = "mock_value"

    return pd.DataFrame(data, index=[0])[EXPECTED_COLS]  # ensure correct order


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: EatDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the EatDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (EatDownloader): Instance of EatDownloader class.
        init_args (dict): Arguments used to initialize an EatDownloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid URL.

    Args:
        init_args (dict): Arguments used to initialize an EatDownloader instance.
    """
    with patch("rbc.energy.eat.downloader.requests.head") as mock_head:
        mock_head.return_value.raise_for_status.side_effect = exceptions.HTTPError(404)

        with pytest.raises(ConnectionError, match="EAT API/URL access failed"):
            EatDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    If all monthly tasks are already marked as done in the checkpoint, the
    downloader should not attempt any downloads.

    Args:
        init_args (dict): Arguments used to initialize an EatDownloader instance.
    """
    args = init_args.copy()

    # save a fake checkpoint file
    checkpoint = {
        DownloadTask(date=d, temporal_resolution="30min").identifier: 1
        for y in args["years"]
        for d in pd.date_range(start=f"{y}-01", end=f"{y}-12", freq="MS")
        .strftime("%Y-%m")
        .tolist()
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True

    with patch("rbc.energy.eat.downloader.requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        downloader = EatDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: EatDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (EatDownloader): Instance of EatDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task)

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task).with_suffix(".csv")
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["tp1"] == int(mock_df.iloc[0]["tp1"])


def test_get_task_data(downloader: EatDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (EatDownloader): Instance of EatDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task)
    with patch(
        "rbc.energy.eat.downloader.load_df_from_file", return_value=mock_df
    ) as mock_load:
        df = downloader._get_task_data(task)

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["trading_date"] == f"{task.date}"
    assert df.iloc[0]["site_code"] == "mock_value"
    assert df.iloc[0]["tp1"] == "10"
    assert mock_load.call_count == 1


def test_get_task_data_no_generation_data(
    downloader: EatDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (EatDownloader): Instance of EatDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = pd.DataFrame(columns=EXPECTED_COLS)

    with patch("rbc.energy.eat.downloader.load_df_from_file", return_value=mock_df):
        with pytest.raises(MissingDataError, match="No energy data available"):
            downloader._get_task_data(task)


def test_get_task_data_structure_changed(
    downloader: EatDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when dataframe doesn't have all columns.

    Args:
        downloader (EatDownloader): Instance of EatDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task).drop(columns="trading_date")

    with patch("rbc.energy.eat.downloader.load_df_from_file", return_value=mock_df):
        with pytest.raises(DataStructureError, match="Missing columns"):
            downloader._get_task_data(task)
