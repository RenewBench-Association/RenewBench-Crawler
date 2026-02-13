# tests/energy/epias/test_downloader.py
import pickle
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from rbc.energy.epias import EpiasDownloader


# ----------------------------------
# Specific fixtures
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
        init_args (dict): Arguments used to initialise an EpiasDownloader instance.

    Returns:
        EpiasDownloader: EpiasDownloader instance.
    """
    with patch("rbc.energy.epias.downloader.EPTR2"):
        return EpiasDownloader(**init_args)


@pytest.fixture
def date(init_args: dict) -> str:
    """Gets a date from the given year.

    Args:
        init_args (dict): Arguments used to initialise an EpiasDownloader instance.

    Returns:
        str: Single date to download.
    """
    year = init_args["years"][0]
    return f"{year}-01-01"


# ----------------------------------
# Tests
# ----------------------------------
def test_downloader_initialization(init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the EpiasDownloader sets up paths and checkpoint correctly.

    Args:
        init_args (dict): Arguments used to initialise an EpiasDownloader instance.
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


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    Args:
        init_args (dict): Arguments used to initialise an EpiasDownloader instance.
    """
    # save a fake checkpoint file
    y = init_args["years"][0]
    checkpoint = {
        d: 1
        for d in pd.date_range(start=f"{y}-01-01", end=f"{y}-12-31")
        .strftime("%Y-%m-%d")
        .tolist()
    }
    checkpoint_path = Path(init_args["output_path"], "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    init_args["resume"] = True
    with patch("rbc.energy.epias.downloader.EPTR2"):
        downloader = EpiasDownloader(**init_args)

        with patch.object(downloader, "_download_day_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


def test_threading_wrapper_missing_data(downloader: EpiasDownloader, date: str) -> None:
    """Happy path for "_threading_wrapper" function when no data is available.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        date (str): Date to download.
    """
    with patch.object(downloader, "_get_day_data", side_effect=ValueError):
        downloader._threading_wrapper(date)

        assert downloader.checkpoint[date] == 1


def test_threading_wrapper_service_unavailable(
    downloader: EpiasDownloader, date: str
) -> None:
    """Failure path for "_threading_wrapper" function when connection error occurs.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        date (str): Date to download.
    """
    with patch.object(downloader, "_get_day_data", side_effect=ConnectionError):
        with patch("rbc.energy.epias.downloader.time.sleep"):
            downloader._threading_wrapper(date)

        assert downloader.checkpoint[date] == 0


def test_download_day_data(downloader: EpiasDownloader, date: str) -> None:
    """Happy path for "_download_day_data" method when resuming from checkpoint.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        date (str): Date to download.
    """
    mock_df = pd.DataFrame({"total": [16.2]})

    with patch.object(downloader, "_get_day_data", return_value=mock_df):
        status = downloader._download_day_data(date)

        assert status == 1
        expected_file = Path(downloader.output_path, f"{date}.csv")
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["total"] == 16.2


def test_get_day_data(downloader: EpiasDownloader, date: str) -> None:
    """Happy path for "_get_day_data" method.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        date (str): Date to download.
    """
    mock_pp_data = pd.DataFrame(
        {
            "id": ["2336"],
            "name": ["3S KALE JES-40W000000012366M-2336"],
        }
    )
    mock_gen_data = pd.DataFrame(
        {
            "date": [date],
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
    df = downloader._get_day_data(date)

    assert not df.empty
    assert df.iloc[0]["date"] == date
    assert df.iloc[0]["total"] == 16.2


def test_get_day_data_no_pp_data(downloader: EpiasDownloader, date: str) -> None:
    """Failure path for "_get_day_data" method when no power plant data is available.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        date (str): Date to download.
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

    with pytest.raises(ValueError, match="No power plant data"):
        downloader._get_day_data(date)


def test_get_day_data_no_gen_data(downloader: EpiasDownloader, date: str) -> None:
    """Failure path for "_get_day_data" method when no generation data is available.

    Args:
        downloader (EpiasDownloader): Instance of EpiasDownloader class.
        date (str): Date to download.
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

    with pytest.raises(ValueError, match="No generation data"):
        downloader._get_day_data(date)
