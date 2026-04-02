# tests/energy/aeso/test_downloader.py
"""Tests for AESO energy data downloader."""

import io
import pickle
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from requests import exceptions

from rbc.energy.aeso import AesoDownloader
from rbc.energy.aeso.downloader import EXPECTED_COLS
from rbc.energy.utils import (
    DataStructureError,
    DownloadTask,
    InvalidError,
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
        "temporal_resolutions": ["1h", "5min"],
        "resume": False,
    }


@pytest.fixture
def mock_lookup(init_args: dict) -> dict:
    """Creates a mocked lookup of source files 'available' to download.

    Args:
        init_args (dict): Arguments used to initialize an AesoDownloader instance.

    Returns:
        dict: Mock lookup dictionary of source files.
    """
    y = init_args["years"][0]
    tasks = pd.date_range(f"{y}-01", f"{y}-12", freq="MS").strftime("%Y-%m").tolist()
    source_dict = {t: {"id": "fake_id", "name": "fake_name"} for t in tasks}
    return {"1h": source_dict, "5min": source_dict}


@pytest.fixture
def downloader(init_args: dict, mock_lookup: dict) -> AesoDownloader:
    """Provides an AesoDownloader instance with a mocked, positive return code response.

    Args:
        init_args (dict): Arguments used to initialize an AesoDownloader instance.
        mock_lookup (dict): Dictionary of mocked source files to download.

    Returns:
        AesoDownloader: AesoDownloader instance.
    """
    with patch("rbc.energy.aeso.downloader.requests.get") as mock_get:
        with patch("rbc.energy.aeso.downloader.BoxClient"):
            with patch.object(AesoDownloader, "_build_source_lookup") as mock_build:
                mock_get.return_value = MagicMock(status_code=200)
                mock_build.return_value = mock_lookup
                return AesoDownloader(**init_args)


@pytest.fixture(params=["1h", "5min"])
def task(request: pytest.FixtureRequest, init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM, temporal_resolution=1h' from the init arguments.

    Args:
        request (FixtureRequest): Special pytest fixture used to access 'params' values.
        init_args (dict): Arguments used to initialize an AesoDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM)
    """
    return DownloadTask(
        date=f"{init_args['years'][0]}-01",
        temporal_resolution=request.param,
    )


def get_mock_df(spec_task: DownloadTask) -> pd.DataFrame:
    """Gets a mock dataframe for a specific task.

    Args:
        spec_task (DownloadTask): The metadata of a download task, here: date (YYYY-MM), t_res

    Returns:
        pandas.DataFrame: Mock dataframe.
    """
    row: dict[str, object] = {c: ["A"] for c in EXPECTED_COLS}
    row.update(
        {c: f"{spec_task.date}-01 00:00:00" for c in EXPECTED_COLS if "Date" in c}
    )
    row.update(
        {
            "Volume": 10.0,
            "Maximum Capability": 20.0,
            "System Capability": 10.0,
            "Planning Area": 10,
        }
    )
    return pd.DataFrame(row, index=[0])


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(
    downloader: AesoDownloader, init_args: dict, mock_lookup: dict
) -> None:
    """Happy path for class initialization.

    Check that the AesoDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        init_args (dict): Arguments used to initialize an AesoDownloader instance.
        mock_lookup (dict): Dictionary of mocked source files to download.
    """
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}
    assert downloader._source_lookup == mock_lookup


def test_downloader_initialization_invalid_tres(init_args: dict) -> None:
    """Failure path for class initialization with invalid temporal resolution.

    Args:
        init_args (dict): Arguments used to initialize an AesoDownloader instance.
    """
    args = init_args.copy()
    args["temporal_resolutions"] = ["invalid"]

    with pytest.raises(InvalidError, match="Invalid temporal resolution"):
        AesoDownloader(**args)


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid request.

    Args:
        init_args (dict): Arguments used to initialize an AesoDownloader instance.
    """
    with patch("rbc.energy.aeso.downloader.requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = exceptions.HTTPError(404)

        with pytest.raises(ConnectionError, match="AESO API/URL access failed"):
            AesoDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    Args:
        init_args (dict): Arguments used to initialize an AesoDownloader instance.
    """
    args = init_args.copy()

    # save a fake checkpoint file
    y = args["years"][0]
    checkpoint = {
        DownloadTask(date=d, temporal_resolution=t_res).identifier: 1
        for t_res in args["temporal_resolutions"]
        for d in pd.date_range(start=f"{y}-01", end=f"{y}-12", freq="MS").strftime(
            "%Y-%m"
        )
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True

    with patch("rbc.energy.aeso.downloader.requests.get") as mock_get:
        with patch("rbc.energy.aeso.downloader.BoxClient"):
            with patch.object(AesoDownloader, "_build_source_lookup", return_value={}):
                mock_get.return_value = MagicMock(status_code=200)
                downloader = AesoDownloader(**args)

                with patch.object(downloader, "_download_task_data") as mock_dump:
                    mock_dump.return_value = 1
                    downloader.download_data()

                    assert mock_dump.call_count == 0
                    assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: AesoDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (IesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    mock_df = pd.DataFrame({"Volume": [16.2]})

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task)
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["Volume"] == 16.2


def test_get_task_data(downloader: AesoDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    mock_df = get_mock_df(task)
    with patch.object(downloader, "_load_zip", return_value=mock_df) as mock_load:
        df = downloader._get_task_data(task)

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["Date (MST)"] == f"{task.date}-01 00:00:00"
    assert df.iloc[0]["Asset Name"] == "A"
    assert df.iloc[0]["Volume"] == 10.0
    assert mock_load.call_count == 1


def test_get_task_data_no_lookup_match(init_args: dict, task: DownloadTask) -> None:
    """Failure path for "_get_task_data" method when no matching file in lookup exists.

    Args:
        init_args (dict): Arguments used to initialize an AesoDownloader instance.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    with patch("rbc.energy.aeso.downloader.requests.get") as mock_get:
        with patch("rbc.energy.aeso.downloader.BoxClient"):
            with patch.object(AesoDownloader, "_build_source_lookup") as mock_build:
                mock_get.return_value = MagicMock(status_code=200)
                mock_build.return_value = {}
                downloader = AesoDownloader(**init_args)

                with patch.object(downloader, "_load_zip"):
                    with pytest.raises(
                        MissingDataError, match="No AESO data that matches"
                    ):
                        downloader._get_task_data(task)


def test_get_task_data_no_generation_data(
    downloader: AesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    mock_df = pd.DataFrame(columns=EXPECTED_COLS)

    with patch.object(downloader, "_load_zip", return_value=mock_df):
        with pytest.raises(MissingDataError, match="No energy data available"):
            downloader._get_task_data(task)


def test_get_task_data_structure_changed(
    downloader: AesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when dataframe doesn't have all columns.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    mock_df = get_mock_df(task).drop(columns="Asset Name")

    with patch.object(downloader, "_load_zip", return_value=mock_df):
        with pytest.raises(DataStructureError, match="Missing columns"):
            downloader._get_task_data(task)


def test_get_task_data_date_unparsable(
    downloader: AesoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when dataframe doesn't have parsable dates.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    mock_df = get_mock_df(task)
    mock_df["Date (MPT)"] = "invalid_date"

    with patch.object(downloader, "_load_zip", return_value=mock_df):
        with pytest.raises(DataStructureError, match="contains unparsable"):
            downloader._get_task_data(task)


def test_get_task_data_no_generation_data_after_month_filter(
    downloader: AesoDownloader, task: DownloadTask
) -> None:
    """Failure path for _get_task_data when month filter removes all rows.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    other_month = "2020-02" if task.date != "2020-02" else "2020-03"
    mock_df = get_mock_df(task)
    mock_df["Date (MPT)"] = f"{other_month}-01 00:00:00"
    mock_df["Date (MST)"] = f"{other_month}-01 00:00:00"

    with patch.object(downloader, "_load_zip", return_value=mock_df):
        with pytest.raises(MissingDataError, match="after month filter"):
            downloader._get_task_data(task)


# ----------------------------------
# Tests - Data crawling helper methods
# ----------------------------------
def test_load_zip(downloader: AesoDownloader, task: DownloadTask) -> None:
    """Happy path for _load_zip method.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    # store the mocked df as bytes to buffer
    mock_df = get_mock_df(task)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test.csv", mock_df.to_csv(index=False))

    mock_stream = MagicMock()
    mock_stream.read.return_value = buffer.getvalue()

    with patch.object(downloader.client.downloads, "download_file") as mock_download:
        mock_download.return_value = mock_stream
        df = downloader._load_zip(item_id="fake_id", item_name="fake_name")

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["Asset Name"] == "A"
    mock_download.assert_called_once()


def test_load_zip_lru_cache_works(
    downloader: AesoDownloader, task: DownloadTask
) -> None:
    """Happy path for @lru_cache decorator for _load_zip method.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM), t_res
    """
    mock_df = get_mock_df(task)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test.csv", mock_df.to_csv(index=False))

    mock_stream = MagicMock()
    mock_stream.read.return_value = buffer.getvalue()

    downloader._load_zip.cache_clear()

    with patch.object(downloader.client.downloads, "download_file") as mock_download:
        mock_download.return_value = mock_stream
        df1 = downloader._load_zip(item_id="fake_id", item_name="fake_name")
        df2 = downloader._load_zip(item_id="fake_id", item_name="fake_name")
        df3 = downloader._load_zip(item_id="fake_id", item_name="fake_name")

    assert mock_download.call_count == 1
    assert not df1.empty
    assert df1.equals(df2)
    assert df2.equals(df3)


@pytest.mark.parametrize(
    "filenames, contents, error_msg",
    [
        (["test.txt"], ["hello"], "expected CSV"),
        (["a.csv", "b.csv"], ["x\n1\n", "x\n2\n"], "expected exactly one file"),
    ],
)
def test_load_zip_structure_change(
    downloader: AesoDownloader, filenames: list, contents: list, error_msg: str
) -> None:
    """Failure path for _load_zip when structure has changed (non-CSV or multiple file(s)).

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        filenames (list): List of filenames.
        contents (list): List of file contents.
        error_msg (str): Error message.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f, c in zip(filenames, contents):
            zf.writestr(f, c)

    mock_stream = MagicMock()
    mock_stream.read.return_value = buffer.getvalue()

    with patch.object(downloader.client.downloads, "download_file") as mock_download:
        mock_download.return_value = mock_stream
        with pytest.raises(DataStructureError, match=error_msg):
            downloader._load_zip(item_id="fake_id", item_name="fake_name")


# ---------------- HELPER FUNCTION ------------------
def get_item(name: str, item_id: str = "fake_id") -> MagicMock:
    """Create a fake Box item entry.

    Args:
        name (str): Name of the box.
        item_id (str): Identifier of the box.

    Returns:
        MagicMock: Box item entry.
    """
    item = MagicMock()
    item.name = name
    item.id = item_id
    item.type = "file"
    return item


def test_build_source_lookup(downloader: AesoDownloader) -> None:
    """Happy path for _build_source_lookup with one- and two-date filenames.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
    """
    page_1h = MagicMock()
    page_1h.entries = [
        get_item("(hourly) - 2020-01.zip", "1h_01"),
        get_item("(hourly) - 2020-06 - 2020-12.zip", "1h_06"),
    ]
    page_1h.total_count = len(page_1h.entries)

    page_5min = MagicMock()
    page_5min.entries = [get_item("(5-min) - 2020-01.zip", "5m_01")]
    page_5min.total_count = len(page_5min.entries)

    with patch.object(downloader.client.folders, "get_folder_items") as mock_items:
        mock_items.side_effect = [page_1h, page_5min]
        lookup = downloader._build_source_lookup()

    # check single file items
    assert lookup["1h"]["2020-01"] == {"id": "1h_01", "name": "(hourly) - 2020-01.zip"}
    assert lookup["5min"]["2020-01"] == {"id": "5m_01", "name": "(5-min) - 2020-01.zip"}
    # check two-file item (range between items)
    for i in range(6, 12):
        assert lookup["1h"][f"2020-{i:02d}"] == {
            "id": "1h_06",
            "name": "(hourly) - 2020-06 - 2020-12.zip",
        }


@pytest.mark.parametrize(
    "entries_1h, entries_5min, error_msg",
    [
        (
            [get_item("badname.zip", "bad")],
            [get_item("2020-01.zip", "ok")],
            "Naming convention",
        ),
        (
            [],
            [get_item("2020-01.zip", "ok")],
            "No data for temporal",
        ),
    ],
)
def test_build_source_lookup_structure_changed(
    downloader: AesoDownloader,
    entries_1h: list[MagicMock],
    entries_5min: list[MagicMock],
    error_msg: str,
) -> None:
    """Failure paths for _build_source_lookup when the structure has changed.

    Args:
        downloader (AesoDownloader): Instance of AesoDownloader class.
        entries_1h (list[MagicMock]): Mocked Box entries for the 1h folder.
        entries_5min (list[MagicMock]): Mocked Box entries for the 5min folder.
        error_msg (str): Expected error message.
    """
    page_1h = MagicMock()
    page_1h.entries = entries_1h
    page_1h.total_count = len(entries_1h)

    page_5min = MagicMock()
    page_5min.entries = entries_5min
    page_5min.total_count = len(entries_5min)

    with patch.object(downloader.client.folders, "get_folder_items") as mock_items:
        mock_items.side_effect = [page_1h, page_5min]
        with pytest.raises(DataStructureError, match=error_msg):
            downloader._build_source_lookup()
