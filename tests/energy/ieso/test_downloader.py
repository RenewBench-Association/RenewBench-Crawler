# tests/energy/ieso/test_downloader.py
"""Tests for IESO energy data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.ieso import IesoDownloader
from rbc.energy.ieso.downloader import (
    EXPECTED_COLS,
    MIN_YEAR,
    URL_NEW_BASE,
    URL_OLD_BASE,
)
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
        dict: Initialisation arguments.
    """
    return {
        "output_path": tmp_path,
        "years": [2020],
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> IesoDownloader:
    """Provides an IesoDownloader instance with a mocked, positive return code response.

    Args:
        init_args (dict): Arguments used to initialize an IesoDownloader instance.

    Returns:
        IesoDownloader: IesoDownloader instance.
    """
    with patch("rbc.energy.ieso.downloader.requests.head") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        return IesoDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize an IesoDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01")


def get_mock_df(specific_task: DownloadTask) -> pd.DataFrame:
    """Gets a mock dataframe for a specific task.

    Args:
        specific_task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

    Returns:
        pandas.DataFrame: Mock dataframe.
    """
    return pd.DataFrame(
        {
            **{
                "Delivery Date": f"{specific_task.date}-01",
                "Generator": "A",
                "Fuel Type": None,
                "Measurement": "Output",
            },
            **{f"Hour {i}": "10" for i in range(1, 25)},
        },
        index=[0],
    )


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: IesoDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the IesoDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        init_args (dict): Arguments used to initialize an IesoDownloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_url(init_args: dict) -> None:
    """Failure path for class initialization with invalid URL.

    Args:
        init_args (dict): Arguments used to initialize an IesoDownloader instance.
    """
    with patch("rbc.energy.ieso.downloader.requests.head") as mock_head:
        mock_head.return_value.raise_for_status.side_effect = exceptions.HTTPError(
            "404"
        )

        with pytest.raises(ConnectionError, match="One or more IESO endpoints"):
            IesoDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    Args:
        init_args (dict): Arguments used to initialize an IesoDownloader instance.
    """
    args = init_args.copy()
    y = args["years"][0]

    # save a fake checkpoint file
    checkpoint = {
        DownloadTask(date=d).identifier: 1
        for d in pd.date_range(start=f"{y}-01", end=f"{y}-12", freq="MS")
        .strftime("%Y-%m")
        .tolist()
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True

    with patch("rbc.energy.ieso.downloader.requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        downloader = IesoDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: IesoDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task)

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task)
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["Hour 1"] == int(mock_df.iloc[0]["Hour 1"])


@pytest.mark.parametrize(
    "task, expect_old, expect_new",
    [
        (DownloadTask(date="2019-04"), 1, 0),  # last month routed to old source
        (DownloadTask(date="2019-05"), 0, 1),  # first month routed to new source
    ],
)
def test_get_task_data(
    downloader: IesoDownloader, task: DownloadTask, expect_old: int, expect_new: int
) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        expect_old (int): Expected call count for _get_from_old_source.
        expect_new (int): Expected call count for _get_from_new_source.
    """
    mock_df = get_mock_df(task)
    with patch.object(
        downloader, "_get_from_old_source", return_value=mock_df
    ) as mock_old:
        with patch.object(
            downloader, "_get_from_new_source", return_value=mock_df
        ) as mock_new:
            df = downloader._get_task_data(task)

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["Delivery Date"] == f"{task.date}-01"
    assert df.iloc[0]["Generator"] == "A"
    assert df.iloc[0]["Hour 1"] == "10"
    assert mock_old.call_count == expect_old
    assert mock_new.call_count == expect_new


def test_get_task_data_no_data_for_old_year(downloader: IesoDownloader) -> None:
    """Failure path for "_get_task_data" method when a task before MIN_YEAR is provided.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
    """
    old_year_task = DownloadTask(date=f"{MIN_YEAR - 1}-01")
    mock_df = pd.DataFrame(columns=EXPECTED_COLS)

    with patch.object(downloader, "_get_from_old_source", return_value=mock_df):
        with patch.object(downloader, "_get_from_new_source", return_value=mock_df):
            with pytest.raises(MissingDataError, match="No energy data for year"):
                downloader._get_task_data(old_year_task)


def test_get_task_data_no_generation_data(
    downloader: IesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = pd.DataFrame(columns=EXPECTED_COLS)

    with patch.object(downloader, "_get_from_old_source", return_value=mock_df):
        with patch.object(downloader, "_get_from_new_source", return_value=mock_df):
            with pytest.raises(MissingDataError, match="No energy data available"):
                downloader._get_task_data(task)


def test_get_task_data_structure_changed(
    downloader: IesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when dataframe doesn't have all columns.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task).drop(columns="Generator")

    with patch.object(downloader, "_get_from_old_source", return_value=mock_df):
        with patch.object(downloader, "_get_from_new_source", return_value=mock_df):
            with pytest.raises(DataStructureError, match="Missing columns"):
                downloader._get_task_data(task)


# ----------------------------------
# Tests - Data crawling helper methods
# ----------------------------------
def test_get_from_new_source(downloader: IesoDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_from_new_source" method, ensuring correct URL and no 'Forecast'.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = pd.DataFrame(
        {"Measurement": ["Output", "Forecast", "Capability"], "Value": [10, 20, 30]}
    )

    with patch(
        "rbc.energy.ieso.downloader.load_df_from_file", return_value=mock_df
    ) as mock_load:
        df = downloader._get_from_new_source(task=task)

        # check correct URL was created
        expected_url = f"{URL_NEW_BASE}/PUB_GenOutputCapabilityMonth_{task.year}{task.month:02d}.csv"
        mock_load.assert_called_with(expected_url, header=3, index_col=False)

        # check forecast data was filtered out
        assert "Forecast" not in df["Measurement"].values
        assert len(df) == 2


def test_get_from_new_source_missing_measurement(
    downloader: IesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_from_new_source" method when the 'Measurement' column is missing.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task).drop(columns="Measurement")

    with patch("rbc.energy.ieso.downloader.load_df_from_file", return_value=mock_df):
        with pytest.raises(DataStructureError, match="'Measurement' column is missing"):
            downloader._get_from_new_source(task=task)


@pytest.mark.parametrize(
    "task, suffix",
    [
        (DownloadTask(date="2018-01"), "2018.xlsx"),
        (DownloadTask(date="2019-01"), "2019-Jan-April.xlsx"),  # edge case
    ],
)
def test_get_from_old_source(
    downloader: IesoDownloader, task: DownloadTask, suffix: str
) -> None:
    """Happy path for "_get_from_old_source" method, ensuring correct URL and month filter.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        suffix (str): Expected suffix of URL.
    """
    mock_df = pd.DataFrame(
        {
            "Delivery Date": pd.to_datetime(
                [f"{task.date}-01", f"{task.year}-{task.month + 1:02d}-01"]
            )
        }
    )

    with patch.object(downloader, "_load_yearly_excel", return_value=mock_df) as mock_f:
        df = downloader._get_from_old_source(task=task)

        # check correct URL was created
        expected_url = (
            f"{URL_OLD_BASE}/-/media/Files/IESO/Power-Data/data-directory/GOC-{suffix}"
        )
        mock_f.assert_called_with(expected_url)

        # check all except current month were filtered out
        assert len(df) == 1
        assert df["Delivery Date"].dt.month.iloc[0] == task.month


def test_lru_cache_works(downloader: IesoDownloader, task: DownloadTask) -> None:
    """Happy path for @lru_cache decorator for _load_yearly_excel method.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = pd.DataFrame(
        {"DATE": pd.to_datetime(f"{task.date}-01"), "HOUR": [1], "GEN_A": [10]}
    )

    downloader._load_yearly_excel.cache_clear()

    with patch("rbc.energy.ieso.downloader.load_df_from_file") as mock_load:
        mock_load.side_effect = [mock_df, mock_df]

        downloader._get_from_old_source(task=task)
        downloader._get_from_old_source(task=task)
        downloader._get_from_old_source(task=task)

        # check method called 2x - both in _load_yearly_excel call in 1st _get_from_old_source
        assert mock_load.call_count == 2


def test_get_from_old_source_structure_changed(
    downloader: IesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_from_new_source" method when the URL is unavailable.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    with patch.object(downloader, "_load_yearly_excel") as mock_load:
        mock_load.return_value = pd.DataFrame({"Delivery Date": [f"{task.date}-01"]})

        with pytest.raises(DataStructureError, match="no longer datetimelike"):
            downloader._get_from_old_source(task=task)


def test_load_yearly_excel(downloader: IesoDownloader, task: DownloadTask) -> None:
    """Happy path for "_load_yearly_excel" method, with concatenation and capacity finding.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df_out = pd.DataFrame(
        {"DATE": [f"{task.date}-01"], "HOUR": [1], "GEN_A": [10]}
    )
    mock_df_cap = pd.DataFrame(
        {"DATE": [f"{task.date}-01"], "HOUR": [1], "GEN_A": [100]}
    )

    with patch("rbc.energy.ieso.downloader.load_df_from_file") as mock_load:
        mock_load.side_effect = [mock_df_out, ValueError, mock_df_cap]

        df = downloader._load_yearly_excel(url="http://fake.xlsx")

        # check that returned df has correct new structure (up to 'HOUR 2')
        assert all(
            col in df.columns for col in ["Delivery Date", "Generator", "Measurement"]
        )
        assert len(df) == 2
        assert df["Hour 1"].iloc[0] == 100  # 'Capability' measurement
        assert df["Hour 1"].iloc[1] == 10  # 'Output' measurement

        # assert that mocked function was called correctly
        assert mock_load.call_count == 3
        sheet_name_1 = mock_load.call_args_list[1].kwargs["sheet_name"]
        assert sheet_name_1 == "Available Capacities"
        sheet_name_2 = mock_load.call_args_list[2].kwargs["sheet_name"]
        assert sheet_name_2 == "Capability - see Notes"


def test_load_yearly_excel_missing_capacity(
    downloader: IesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_load_yearly_excel" method when no suitable capacity sheets exist.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df_out = pd.DataFrame(
        {"DATE": [f"{task.date}-01"], "HOUR": [1], "GEN_A": [10]}
    )

    with patch("rbc.energy.ieso.downloader.load_df_from_file") as mock_load:
        mock_load.side_effect = [mock_df_out, ValueError, ValueError, ValueError]

        with pytest.raises(DataStructureError, match="No valid capacity sheets"):
            downloader._load_yearly_excel(url="http://fake.xlsx")


def test_standardize_old_data(downloader: IesoDownloader, task: DownloadTask) -> None:
    """Happy path for "_standardize_old_data" method, ensuring transformations work.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = pd.DataFrame(
        {
            "DATE": [f"{task.date}-01", f"{task.date}-01"],
            "HOUR": [1, 2],
            "GEN_A": [10, 11],
            "GEN_B": [20, 21],
        }
    )
    result = downloader.standardize_old_data(mock_df, "Output")

    assert len(result) == 2
    assert "Hour 1" in result.columns
    assert "Hour 2" in result.columns
    assert result.loc[result["Generator"] == "GEN_A", "Hour 1"].iloc[0] == 10
    assert result["Measurement"].unique()[0] == "Output"


def test_standardize_old_data_missing_columns(downloader: IesoDownloader) -> None:
    """Failure path for "_standardize_old_data" method when relevant columns are missing.

    Args:
        downloader (IesoDownloader): Instance of IesoDownloader class.
    """
    mock_df = pd.DataFrame({"HOUR": [1], "Generator 1": [10]})

    with pytest.raises(DataStructureError, match="Relevant columns are missing"):
        downloader.standardize_old_data(mock_df, measurement_type="Output")
