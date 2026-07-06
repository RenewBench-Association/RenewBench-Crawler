# tests/energy/eia/test_downloader.py
"""Tests for EIA energy data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.eia import EiaDownloader
from rbc.energy.utils import (
    MAX_RETRIES,
    DataStructureError,
    DownloadTask,
    MissingDataError,
)


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
        "token": "fake_token",
        "output_path": tmp_path,
        "years": [2020],
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> EiaDownloader:
    """Provides an EiaDownloader instance with a mocked, positive return code response.

    Args:
        init_args (dict): Arguments used to initialize an EiaDownloader instance.

    Returns:
        EiaDownloader: EiaDownloader instance.
    """
    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        return EiaDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM-DD' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize an EiaDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01-01")


def get_mock_eia_json(
    date: str | None = None, data: list | None = None, total: int | None = None
) -> dict:
    """Helper to generate an argument-dependant EIA response body.

    Args:
        date (str): The task date (YYYY-MM-DD)
        data (list): Data list of EIA response body.
        total (int): Total number of data that should exist.

    Returns:
        dict: Dictionary with EIA response body.
    """
    if date is not None:
        if data is None:
            data = [
                {
                    "period": f"{date}T00",
                    "respondent": "A",
                    "respondent-name": "Company A",
                    "fueltype": "NG",
                    "type-name": "Natural Gas",
                    "value": "10",
                    "value-units": "megawatthours",
                }
            ]
    else:
        data = []

    return {
        "response": {
            "total": str(total if total is not None else len(data)),
            "data": data,
        }
    }


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: EiaDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the EiaDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        init_args (dict): Arguments used to initialize an EiaDownloader instance.
    """
    assert downloader.token == init_args["token"]
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid token.

    Args:
        init_args (dict): Arguments used to initialize an EiaDownloader instance.
    """
    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = exceptions.HTTPError(404)

        with pytest.raises(ConnectionError, match="EIA API/URL access failed"):
            EiaDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    If all daily tasks are already marked as done in the checkpoint, the
    downloader should not attempt any downloads.

    Args:
        init_args (dict): Arguments used to initialize an EiaDownloader instance.
    """
    args = init_args.copy()

    # save a fake checkpoint file
    checkpoint = {
        DownloadTask(date=d).identifier: 1
        for y in args["years"]
        for d in pd.date_range(start=f"{y}-01-01", end=f"{y}-12-31")
        .strftime("%Y-%m-%d")
        .tolist()
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True

    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        downloader = EiaDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: EiaDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_df = pd.DataFrame({"total": [16.2]})

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task).with_suffix(".csv")
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["total"] == 16.2


def test_get_task_data(downloader: EiaDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = get_mock_eia_json(task.date)

    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = mock_response
        df = downloader._get_task_data(task)

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["period"] == f"{task.date}T00"
    assert df.iloc[0]["value"] == "10"
    assert mock_get.call_count == 1


def test_get_task_data_request_failed(
    downloader: EiaDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the request fails directly.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.side_effect = exceptions.ConnectionError

        with pytest.raises(exceptions.ConnectionError, match="request failed"):
            downloader._get_task_data(task)

        mock_get.side_effect = exceptions.Timeout

        with pytest.raises(exceptions.Timeout, match="request failed"):
            downloader._get_task_data(task)


def test_get_task_data_fail_return_code(
    downloader: EiaDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the return code is unsuccessful.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=500)

        with pytest.raises(exceptions.HTTPError, match="request failed"):
            downloader._get_task_data(task)


def test_get_task_data_rate_limit_fail(
    downloader: EiaDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the rate limit is reached (code 429).

    Checks that the warning message is logged when the return code is 429 on a first
    try. To prevent endless looping, the second run is changed to a valid return code.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    with (
        patch("rbc.energy.eia.downloader.requests.get") as mock_get,
        patch("rbc.energy.eia.downloader.time.sleep") as mock_sleep,
    ):
        mock_get.side_effect = [MagicMock(status_code=429)] * (MAX_RETRIES + 1)

        with pytest.raises(exceptions.HTTPError, match="EIA API rate limit"):
            downloader._get_task_data(task)

        assert mock_get.call_count == MAX_RETRIES + 1
        assert mock_sleep.call_count == MAX_RETRIES


@pytest.mark.parametrize("return_val", [{}, {"response": {}}])
def test_get_task_data_failed_response_parsing(
    downloader: EiaDownloader, task: DownloadTask, return_val: dict
) -> None:
    """Failure path for "_get_task_data" method when the parsed response is incomplete.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
        return_val (dict): Incomplete return values from parsing.
    """
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = return_val

    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = mock_response

        with pytest.raises(DataStructureError, match="Failed parsing"):
            downloader._get_task_data(task)


def test_get_task_data_incomplete_download(
    downloader: EiaDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the download isn't complete.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = get_mock_eia_json(total=1)

    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = mock_response

        with pytest.raises(ConnectionError, match="Incomplete download"):
            downloader._get_task_data(task)


def test_get_task_data_no_generation_data(
    downloader: EiaDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = get_mock_eia_json()

    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = mock_response

        with pytest.raises(MissingDataError, match="No energy data available"):
            downloader._get_task_data(task)


def test_get_task_data_structure_changed(
    downloader: EiaDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when dataframe doesn't have all columns.

    Args:
        downloader (EiaDownloader): Instance of EiaDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = get_mock_eia_json(
        date="2020-01-01", data=[{"period": f"{task.date}T00"}]
    )

    with patch("rbc.energy.eia.downloader.requests.get") as mock_get:
        mock_get.return_value = mock_response

        with pytest.raises(DataStructureError, match="Missing columns"):
            downloader._get_task_data(task)
