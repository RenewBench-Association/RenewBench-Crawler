# tests/energy/ons/test_downloader.py
"""Tests for ONS energy data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.ons import OnsDownloader
from rbc.energy.ons.downloader import EXPECTED_COLS, URL_BASE
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
        "years": [2023],
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> OnsDownloader:
    """Provides an OnsDownloader instance with a mocked, positive return code response.

    Args:
        init_args (dict): Arguments used to initialize an OnsDownloader instance.

    Returns:
        OnsDownloader: OnsDownloader instance.
    """
    with patch("rbc.energy.ons.downloader.requests.head") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        return OnsDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize an OnsDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01")


def get_mock_df(spec_task: DownloadTask) -> pd.DataFrame:
    """Gets a mock dataframe for a specific task.

    Args:
        spec_task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

    Returns:
        pandas.DataFrame: Mock dataframe.
    """
    row: dict[str, object] = {c: ["A"] for c in EXPECTED_COLS}
    row.update(
        {
            c: f"{spec_task.date}-01 00:00:00"
            for c in EXPECTED_COLS
            if "din_instante" in c
        }
    )
    row.update({"val_geracao": 10.0})
    return pd.DataFrame(row, index=[0])


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: OnsDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the OnsDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        init_args (dict): Arguments used to initialize an OnsDownloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid URL.

    Args:
        init_args (dict): Arguments used to initialize an OnsDownloader instance.
    """
    with patch("rbc.energy.ons.downloader.requests.head") as mock_head:
        mock_head.return_value.raise_for_status.side_effect = exceptions.HTTPError(404)

        with pytest.raises(ConnectionError, match="API/URL access failed"):
            OnsDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    If all monthly tasks are already marked as done in the checkpoint, the
    downloader should not attempt any downloads.

    Args:
        init_args (dict): Arguments used to initialize an OnsDownloader instance.
    """
    args = init_args.copy()

    # save a fake checkpoint file
    checkpoint = {
        DownloadTask(date=d).identifier: 1
        for y in args["years"]
        for d in pd.date_range(start=f"{y}-01", end=f"{y}-12", freq="MS")
        .strftime("%Y-%m")
        .tolist()
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True

    with patch("rbc.energy.ons.downloader.requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        downloader = OnsDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: OnsDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task)

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task)
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["val_geracao"] == int(mock_df.iloc[0]["val_geracao"])


@pytest.mark.parametrize(
    "task, expect_old, expect_new",
    [
        (DownloadTask(date="2021-01"), 1, 0),  # last month routed to old source
        (DownloadTask(date="2022-01"), 0, 1),  # first month routed to new source
    ],
)
def test_get_task_data(
    downloader: OnsDownloader, task: DownloadTask, expect_old: int, expect_new: int
) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        expect_old (int): Expected call count for _get_from_yearly_csv.
        expect_new (int): Expected call count for _get_from_monthly_csv.
    """
    mock_df = get_mock_df(task)
    with patch.object(
        downloader, "_get_from_yearly_csv", return_value=mock_df
    ) as mock_old:
        with patch.object(
            downloader, "_get_from_monthly_csv", return_value=mock_df
        ) as mock_new:
            df = downloader._get_task_data(task)

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["din_instante"] == f"{task.date}-01 00:00:00"
    assert df.iloc[0]["nom_usina"] == "A"
    assert df.iloc[0]["val_geracao"] == 10.0
    assert mock_old.call_count == expect_old
    assert mock_new.call_count == expect_new


def test_get_task_data_no_generation_data(
    downloader: OnsDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = pd.DataFrame(columns=EXPECTED_COLS)

    with patch.object(downloader, "_get_from_yearly_csv", return_value=mock_df):
        with patch.object(downloader, "_get_from_monthly_csv", return_value=mock_df):
            with pytest.raises(MissingDataError, match="No energy data available"):
                downloader._get_task_data(task)


def test_get_task_data_structure_changed(
    downloader: OnsDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when dataframe doesn't have all columns.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task).drop(columns="val_geracao")

    with patch.object(downloader, "_get_from_yearly_csv", return_value=mock_df):
        with patch.object(downloader, "_get_from_monthly_csv", return_value=mock_df):
            with pytest.raises(DataStructureError, match="Missing columns"):
                downloader._get_task_data(task)


# ----------------------------------
# Tests - Data crawling helper methods
# ----------------------------------
def test_get_from_monthly_csv(downloader: OnsDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_from_monthly_csv" method, ensuring correct URL.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task)

    with patch(
        "rbc.energy.ons.downloader.load_df_from_file", return_value=mock_df
    ) as mock_load:
        df = downloader._get_from_monthly_csv(task=task)

        # check correct URL was created
        expected_url = (
            f"{URL_BASE}GERACAO_USINA-2_{task.year}_{str(task.month).zfill(2)}.csv"
        )
        mock_load.assert_called_with(expected_url, delimiter=";")

        # check all columns were loaded
        assert "val_geracao" in df.columns


def test_get_from_yearly_csv(downloader: OnsDownloader) -> None:
    """Happy path for "_get_from_yearly_csv" method, ensuring correct URL and month filter.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
    """
    task = DownloadTask(date="2021-01")
    mock_df = pd.DataFrame(
        {
            "din_instante": pd.to_datetime(
                [
                    f"{task.date}-01 00:00:00",
                    f"{task.year}-{task.month + 1:02d}-01 00:00:00",
                ]
            )
        }
    )

    with patch.object(downloader, "_load_yearly_csv", return_value=mock_df) as mock_f:
        df = downloader._get_from_yearly_csv(task=task)

        # check correct URL was created
        expected_url = f"{URL_BASE}GERACAO_USINA-2_{task.year}.csv"
        mock_f.assert_called_with(expected_url)

        # check all except current month were filtered out
        assert len(df) == 1
        assert df["din_instante"].dt.month.iloc[0] == task.month


def test_lru_cache_works(downloader: OnsDownloader, task: DownloadTask) -> None:
    """Happy path for @lru_cache decorator for _load_yearly_csv method.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = pd.DataFrame(
        {
            "din_instante": pd.to_datetime(f"{task.date}-01 00:00:00"),
            "generation_MWmed": [10],
        }
    )

    downloader._load_yearly_csv.cache_clear()

    with patch("rbc.energy.ons.downloader.load_df_from_file") as mock_load:
        mock_load.return_value = mock_df

        downloader._get_from_yearly_csv(task=task)
        downloader._get_from_yearly_csv(task=task)
        downloader._get_from_yearly_csv(task=task)

        assert mock_load.call_count == 1


def test_load_yearly_csv(downloader: OnsDownloader, task: DownloadTask) -> None:
    """Happy path for "_load_yearly_csv" method.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    downloader._load_yearly_csv.cache_clear()

    with patch("rbc.energy.ons.downloader.load_df_from_file") as mock_load:
        mock_load.return_value = get_mock_df(task)

        df = downloader._load_yearly_csv(url="http://fake.csv")

        assert mock_load.call_count == 1
        assert df["din_instante"].iloc[0] == pd.Timestamp(f"{task.date}-01")


@pytest.mark.parametrize(
    "mock_df_dict, expected_match",
    [
        ({"din_instante": ["fake_date"]}, "no longer datetimelike"),  # catch ValueError
        ({"val_geracao": [10]}, "Missing datetime column"),  # catch KeyError
    ],
)
def test_load_yearly_csv_structure_changed(
    downloader: OnsDownloader,
    task: DownloadTask,
    mock_df_dict: dict,
    expected_match: str,
) -> None:
    """Failure path for "_load_yearly_csv" method when the dates aren't datetime-like.

    Args:
        downloader (OnsDownloader): Instance of OnsDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        mock_df_dict (dict): Dictionary of mock dataframe columns.
        expected_match (str): Expected match string.
    """
    downloader._load_yearly_csv.cache_clear()

    with patch("rbc.energy.ons.downloader.load_df_from_file") as mock_load:
        mock_load.return_value = pd.DataFrame(mock_df_dict)

        with pytest.raises(DataStructureError, match=expected_match):
            downloader._load_yearly_csv(url="http://fake.csv")
