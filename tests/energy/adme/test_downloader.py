"""Tests for ADME energy data downloader."""

import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.adme import AdmeDownloader
from rbc.energy.adme.downloader import (
    EXPECTED_COLS,
    EXPECTED_OLD_SHEETS,
    TIME_COL,
    URL_BASE_NEW,
    URL_BASE_OLD,
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
        dict: initialization arguments.
    """
    return {
        "output_path": tmp_path,
        "years": [2020],
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> AdmeDownloader:
    """Provides an AdmeDownloader instance with mocked connectivity checks.

    Args:
        init_args (dict): Arguments used to initialize an AdmeDownloader instance.

    Returns:
        AdmeDownloader: AdmeDownloader instance.
    """
    with patch("rbc.energy.adme.downloader.requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        return AdmeDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a monthly task as 'date=YYYY-MM' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize an AdmeDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01")


def get_mock_df(
    spec_task: DownloadTask,
    columns: list[tuple[str, str]] | None = None,
    n_rows: int = 1,
) -> pd.DataFrame:
    """Gets a mock dataframe (with MultiIndex column headers) for a specific task.

    Args:
        spec_task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        columns (list[tuple[str, str]], optional): The dataframe columns as tuples.
            Defaults to None, in which case all required columns are used.
        n_rows (int, optional): The number of dataframe rows. Defaults to 1.

    Returns:
        pandas.DataFrame: Mock dataframe.
    """
    if columns is None:
        columns = [TIME_COL] + [(c, "A") for c in EXPECTED_COLS if c != "/"]

    idx = pd.MultiIndex.from_tuples(columns)
    data: dict[tuple[str, str], list] = {c: list(range(1, n_rows + 1)) for c in idx}

    # check if columns contain datetime elements, redefine data values
    for col in columns:
        if col == TIME_COL:
            n_rows = n_rows if n_rows <= 23 else 23  # can't exceed 24 hours of the day
            dates = [
                f"01-{str(spec_task.month).zfill(2)}-{spec_task.year} {str(i).zfill(2)}:00"
                for i in range(1, n_rows + 1)
            ]
            data[col] = dates

    return pd.DataFrame(data)


@pytest.fixture(autouse=True)
def clear_cache() -> Generator[None, None, None]:
    """Clear lru_cache after each test to avoid cache pollution."""
    yield
    AdmeDownloader._load_yearly_excel.cache_clear()


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: AdmeDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the AdmeDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
        init_args (dict): Arguments used to initialize an AdmeDownloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid URL(s).

    Args:
        init_args (dict): Arguments used to initialize an AdmeDownloader instance.
    """
    with patch("rbc.energy.adme.downloader.requests.head") as mock_head:
        mock_head.return_value.raise_for_status.side_effect = exceptions.HTTPError(404)

        with pytest.raises(ConnectionError, match="API/URL access failed"):
            AdmeDownloader(**init_args)

        assert mock_head.call_count == 1


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" when resuming from checkpoint.

    If all monthly tasks are already marked as done in the checkpoint, the
    downloader should not attempt any downloads.

    Args:
        init_args (dict): Arguments used to initialize an AdmeDownloader instance.
    """
    args = init_args.copy()

    # create a fake checkpoint with all months of the year completed
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

    with patch("rbc.energy.adme.downloader.requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        downloader = AdmeDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: AdmeDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task)

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

    assert status == 1
    expected_file = downloader._build_task_path(task).with_suffix(".csv")
    assert expected_file.is_file(), f"The CSV {expected_file} was not created!"


@pytest.mark.parametrize(
    "task, expect_old, expect_new",
    [
        (DownloadTask(date="2018-01"), 1, 0),  # routed to old source
        (DownloadTask(date="2019-01"), 0, 1),  # routed to new source
    ],
)
def test_get_task_data(
    downloader: AdmeDownloader,
    task: DownloadTask,
    expect_old: int,
    expect_new: int,
) -> None:
    """Happy path for "_get_task_data", with different handling of old/new sources.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
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
    assert isinstance(df.columns, pd.MultiIndex)

    top_level_cols = set(df.columns.get_level_values(0))
    for c in EXPECTED_COLS:
        assert c in top_level_cols

    assert mock_old.call_count == expect_old
    assert mock_new.call_count == expect_new


def test_get_task_data_no_generation_data(
    downloader: AdmeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" when the dataframe is empty.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    empty_df = pd.DataFrame()

    with patch.object(downloader, "_get_from_old_source", return_value=empty_df):
        with patch.object(downloader, "_get_from_new_source", return_value=empty_df):
            with pytest.raises(MissingDataError, match="No energy data available"):
                downloader._get_task_data(task)


def test_get_task_data_structure_changed_missing_columns(
    downloader: AdmeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" when expected columns are missing.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task, [TIME_COL])  # only time column!

    with patch.object(downloader, "_get_from_old_source", return_value=mock_df):
        with patch.object(downloader, "_get_from_new_source", return_value=mock_df):
            with pytest.raises(DataStructureError, match="Missing columns"):
                downloader._get_task_data(task)


# ----------------------------------
# Tests - Data crawling helper methods
# ----------------------------------
def test_get_from_new_source(downloader: AdmeDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_from_new_source" method, ensuring correct URL.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    # mock_df with an extra column to be cut off
    cols = [TIME_COL] + [(c, "A") for c in EXPECTED_COLS if c != "/"] + [("Extra", "X")]
    mock_df = get_mock_df(task, cols)

    with patch(
        "rbc.energy.adme.downloader.load_df_from_file", return_value=mock_df
    ) as mock_load:
        df = downloader._get_from_new_source(task=task)

    expected_url = f"{URL_BASE_NEW}anod={task.year}&mesd={task.month:02d}&periodo=1&fuente=0&tipo=1"
    mock_load.assert_called_with(expected_url, ".csv", delimiter=";", header=[0, 1])

    assert len(df) == 1
    assert list(df.columns.get_level_values(0)) == EXPECTED_COLS
    assert "Extra" not in df.columns.get_level_values(0)


def test_get_from_new_source_missing_time_column(
    downloader: AdmeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_from_new_source" when relevant column(s) are missing.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_df = get_mock_df(task, [TIME_COL])  # only time column!

    with patch("rbc.energy.adme.downloader.load_df_from_file", return_value=mock_df):
        with pytest.raises(DataStructureError, match="Relevant columns are missing"):
            downloader._get_from_new_source(task=task)


def test_get_from_old_source(downloader: AdmeDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_from_old_source" method, ensuring correct URL and month filter.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    # mock_df with standard columns and extra column to be cut off
    mock_df = get_mock_df(
        task, [TIME_COL, ("Hidráulico", "A"), ("Extra", "X")], n_rows=3
    )

    # make second and third rows the next months' day 1 hour 0 and 1
    mock_df.loc[1, TIME_COL] = f"01-{str(task.month + 1).zfill(2)}-{task.year} 00:00"
    mock_df.loc[2, TIME_COL] = f"01-{str(task.month + 1).zfill(2)}-{task.year} 01:00"
    # convert TIME_COL to datetime, as _load_yearly_excel would
    mock_df[TIME_COL] = pd.to_datetime(mock_df[TIME_COL], dayfirst=True)

    with patch.object(
        downloader, "_load_yearly_excel", return_value=mock_df
    ) as mock_load:
        df = downloader._get_from_old_source(task=task)

    expected_url = f"{URL_BASE_OLD}gpf_{task.year}.xlsx"
    mock_load.assert_called_with(expected_url)

    assert len(df) == 2  # month filter means hour 1 of next month's day 1 is cut
    assert pd.to_datetime(df.loc[0, TIME_COL], dayfirst=True).month == task.month
    assert pd.to_datetime(df.loc[1, TIME_COL], dayfirst=True).month == task.month + 1
    assert pd.api.types.is_string_dtype(df[TIME_COL])  # check TIME_COL are str again


def test_load_yearly_excel(downloader: AdmeDownloader) -> None:
    """Happy path for "_load_yearly_excel" method, ensuring correct Excel sheet handling.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
    """
    # mock df with single column headers and similar setup as what GPF sheet returns
    mock_xls = MagicMock(spec=pd.ExcelFile, sheet_names=list(EXPECTED_OLD_SHEETS))
    mock_df = pd.DataFrame(
        {"Fecha": ["01-01-2010 01:00"], "Hydro A": [100.0], "Eólica": [10.0]}
    )

    with (
        patch("rbc.energy.adme.downloader.load_excel_from_file", return_value=mock_xls),
        patch("rbc.energy.adme.downloader.pd.read_excel", return_value=mock_df),
    ):
        df = downloader._load_yearly_excel("https://fake.url/gpf_2010.xlsx")

    assert isinstance(df.columns, pd.MultiIndex)
    assert TIME_COL in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df[TIME_COL])


def test_load_yearly_excel_missing_sheets(downloader: AdmeDownloader) -> None:
    """Failure path for "_load_yearly_excel" method when required sheets are missing.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
    """
    mock_xl = MagicMock(spec=pd.ExcelFile, sheet_names=["GPF"])

    with patch("rbc.energy.adme.downloader.load_excel_from_file", return_value=mock_xl):
        with pytest.raises(DataStructureError, match="Not all required sheets"):
            downloader._load_yearly_excel("https://fake.url/gpf_2010.xlsx")


def test_load_yearly_excel_bad_content(downloader: AdmeDownloader) -> None:
    """Failure path for "_load_yearly_excel" method when sheet has unparsable content.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
    """
    mock_xls = MagicMock(spec=pd.ExcelFile, sheet_names=list(EXPECTED_OLD_SHEETS))

    with (
        patch("rbc.energy.adme.downloader.load_excel_from_file", return_value=mock_xls),
        patch("rbc.energy.adme.downloader.pd.read_excel", side_effect=ValueError),
    ):
        with pytest.raises(DataStructureError, match="does not contain loadable data"):
            downloader._load_yearly_excel("https://fake.url/gpf_2010.xlsx")


def test_load_yearly_excel_not_datetimelike(downloader: AdmeDownloader) -> None:
    """Failure path for "_load_yearly_excel" method when 'fecha' column is not datetimelike.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
    """
    mock_xls = MagicMock(spec=pd.ExcelFile, sheet_names=list(EXPECTED_OLD_SHEETS))
    mock_df = pd.DataFrame({"Fecha": ["not-a-date"], "Hydro Plant A": [100.0]})

    with (
        patch("rbc.energy.adme.downloader.load_excel_from_file", return_value=mock_xls),
        patch("rbc.energy.adme.downloader.pd.read_excel", return_value=mock_df),
    ):
        with pytest.raises(DataStructureError, match="no longer datetimelike"):
            downloader._load_yearly_excel("https://fake.url/gpf_2010.xlsx")


# ------------------------------------
# Tests - Locking with _download_lock
# ------------------------------------
def test_get_task_data_concurrent_tasks_single_call(downloader: AdmeDownloader) -> None:
    """Happy path for "_get_task_data" that concurrent tasks share the same yearly Excel.

    This runs several tasks using the same yearly Excel file in parallel to assert that the
    underlying HTTP request is made only once, thereby ensuring the combination of
    "_download_lock" and "@lru_cache" with "_load_yearly_excel" work.

    Args:
        downloader (AdmeDownloader): Instance of AdmeDownloader class.
    """
    # define two tasks (months using same old Excel) and example excel & extracted df
    tasks = [DownloadTask(date="2018-04"), DownloadTask(date="2018-05")]

    mock_xls = MagicMock(spec=pd.ExcelFile, sheet_names=list(EXPECTED_OLD_SHEETS))
    dates = [f"01-{t.month}-{t.year} 01:00" for t in tasks]
    mock_df = pd.DataFrame(
        {"Fecha": dates, "Hydro A": [100.0, 200.0], "Eólica": [10.0, 20.0]}
    )

    with (
        patch("rbc.energy.adme.downloader.load_excel_from_file") as mock_load,
        patch("rbc.energy.adme.downloader.pd.read_excel", return_value=mock_df),
    ):
        mock_load.return_value = mock_xls
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(downloader._get_task_data, tasks))

    assert len(results) == len(tasks)  # all tasks should return one result
    assert mock_load.call_count == 1  # only one HTTP request since CSV is shared
