# tests/energy/epias/test_downloader.py
"""Tests for EPIAS energy data downloader."""

import pickle
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from rbc.energy.epias import EpiasDownloader
from rbc.energy.utils import DownloadTask, InvalidError, MissingDataError


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def init_args(tmp_path: Path) -> dict:
    """Creates a basic setup with a temporary directory.

    Args:
        tmp_path (Path): Path to the temporary directory.

    Returns:
        dict: Initialisation arguments.
    """
    return {
        "username": "fake_username",
        "password": "fake_password",
        "output_path": tmp_path,
        "years": [2020],
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> EpiasDownloader:
    """Provides an EpiasDownloader instance with a mocked API.

    Args:
        init_args (dict): Arguments used to initialize an EpiasDownloader instance.

    Returns:
        EpiasDownloader: EpiasDownloader instance.
    """
    with patch("rbc.energy.epias.downloader.EPTR2"):
        return EpiasDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task (date) as YYYY-MM-DD from the given year.

    Args:
        init_args (dict): Arguments used to initialize an EpiasDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01-01")


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the EpiasDownloader sets up paths and checkpoint correctly.

    Args:
        init_args (dict): Arguments used to initialize an EpiasDownloader instance.
    """
    args = init_args.copy()

    with patch("rbc.energy.epias.downloader.EPTR2") as mock_eptr2:
        downloader = EpiasDownloader(**args)

        mock_eptr2.assert_called_once_with(
            username=init_args["username"], password=init_args["password"]
        )

        assert downloader.years == args["years"]
        assert downloader.output_path == args["output_path"]
        assert downloader.checkpoint_path == Path(args["output_path"], "status.pickle")
        assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_credentials(init_args: dict) -> None:
    """Failure path for class initialization with invalid credentials.

    Args:
        init_args (dict): Arguments used to initialize an EpiasDownloader instance.
    """
    with patch("rbc.energy.epias.downloader.EPTR2") as mock_eptr2:
        mock_eptr2.side_effect = Exception("Login Failed")

        with pytest.raises(InvalidError, match="incorrect"):
            EpiasDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    Args:
        init_args (dict): Arguments used to initialize an EpiasDownloader instance.
    """
    args = init_args.copy()

    # save a fake checkpoint file
    y = args["years"][0]
    checkpoint = {
        DownloadTask(date=d).identifier: 1
        for d in pd.date_range(start=f"{y}-01-01", end=f"{y}-12-31")
        .strftime("%Y-%m-%d")
        .tolist()
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True

    with patch("rbc.energy.epias.downloader.EPTR2"):
        downloader = EpiasDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: EpiasDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_df = pd.DataFrame({"total": [16.2]})

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task)
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["total"] == 16.2


def test_get_task_data(downloader: EpiasDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_pp_data = pd.DataFrame(
        {
            "id": ["2336"],
            "name": ["3S KALE JES-40W000000012366M-2336"],
        }
    )
    mock_gen_data = pd.DataFrame(
        {
            "date": [task.date],
            "total": [16.2],
            "powerPlantName": ["3S KALE JES-40W000000012366M-2336"],
        }
    )

    def call_side_effect(endpoint, **kwargs):
        if endpoint == "pp-list-for-date-range":
            return mock_pp_data
        if endpoint == "rt-gen-bulk":
            return mock_gen_data
        return pd.DataFrame()

    downloader.eptr.call.side_effect = call_side_effect
    df = downloader._get_task_data(task)

    assert not df.empty
    assert df.iloc[0]["date"] == task.date
    assert df.iloc[0]["total"] == 16.2


def test_get_task_data_no_pp_data(
    downloader: EpiasDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no power plant data is available.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_pp_data = pd.DataFrame({})
    mock_gen_data = pd.DataFrame({})

    def call_side_effect(endpoint, **kwargs):
        if endpoint == "pp-list-for-date-range":
            return mock_pp_data
        if endpoint == "rt-gen-bulk":
            return mock_gen_data
        return pd.DataFrame()

    downloader.eptr.call.side_effect = call_side_effect

    with pytest.raises(MissingDataError, match="No power plant data"):
        downloader._get_task_data(task)


def test_get_task_data_no_generation_data(
    downloader: EpiasDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_pp_data = pd.DataFrame({"id": ["2336"]})
    mock_gen_data = pd.DataFrame({})

    def call_side_effect(endpoint, **kwargs):
        if endpoint == "pp-list-for-date-range":
            return mock_pp_data
        if endpoint == "rt-gen-bulk":
            return mock_gen_data
        return pd.DataFrame()

    downloader.eptr.call.side_effect = call_side_effect

    with pytest.raises(MissingDataError, match="No energy generation data available"):
        downloader._get_task_data(task)
