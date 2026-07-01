"""Tests for REI energy data downloader."""

import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests
from loguru import logger
from requests import exceptions

from rbc.energy.rei import ReiDownloader
from rbc.energy.rei.downloader import (
    EXPECTED_KEYS,
    EXPECTED_REGIONS,
    MIN_YEAR,
    TIMEZONE,
    URL_BASE,
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
def downloader(init_args: dict) -> ReiDownloader:
    """Provides a ReiDownloader instance with a mocked, positive return code response.

    Args:
        init_args (dict): Arguments used to initialize a ReiDownloader instance.

    Returns:
        ReiDownloader: ReiDownloader instance.
    """
    with patch("rbc.energy.rei.downloader.requests.head") as mock_head:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_head.return_value = mock_resp
        return ReiDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize an EiaDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01")


def get_mock_yearly_json(
    spec_task: DownloadTask, num_epochs: int = 4, freq: str = "h"
) -> tuple[dict, pd.DatetimeIndex]:
    """Helper to generate a structurally valid REI yearly JSON.

    Args:
        spec_task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        num_epochs (int): Number of timestamps / data points. Defaults to 4.
        freq (str): Frequency of data points. Defaults to "h" = 1h.

    Returns:
        dict: Mock yearly JSON dict structure.
        pd.DatetimeIndex: Mock timestamps.
    """
    # hourly epochs depending on provided num_points
    mock_ts = pd.date_range(
        start=datetime(spec_task.year, spec_task.month, 1, 0, 0),
        periods=num_epochs,
        freq=freq,
        tz=TIMEZONE,
    )
    epochs = [int(t.timestamp()) for t in mock_ts.tz_convert("UTC")]

    mock_dict: dict = {"epochs": epochs}
    for region in EXPECTED_REGIONS:
        mock_dict[region] = {
            "thermal": [1.0] * num_epochs,
            "solar": [2.0] * num_epochs,
        }

    return mock_dict, mock_ts


@pytest.fixture(autouse=True)
def clear_cache() -> Generator[None, None, None]:
    """Clear lru_cache after each test to avoid cache pollution."""
    yield
    ReiDownloader._load_yearly_json.cache_clear()


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: ReiDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the ReiDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        init_args (dict): Arguments used to initialize a ReiDownloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid request.

    Args:
        init_args (dict): Arguments used to initialize a ReiDownloader instance.
    """
    with patch("rbc.energy.rei.downloader.requests.head") as mock_head:
        mock_head.return_value.raise_for_status.side_effect = exceptions.HTTPError(404)

        with pytest.raises(ConnectionError, match="REI API/URL access failed"):
            ReiDownloader(**init_args)

            assert mock_head.call_count == 1


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    If all monthly tasks are already marked as done in the checkpoint, the
    downloader should not attempt any downloads.

    Args:
        init_args (dict): Arguments used to initialize an ReiDownloader instance.
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

    with patch("rbc.energy.rei.downloader.requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        downloader = ReiDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: ReiDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_dict, _ = get_mock_yearly_json(task, num_epochs=4)

    with patch.object(downloader, "_get_task_data", return_value=mock_dict):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task).with_suffix(".json")
        assert expected_file.is_file(), f"The JSON {expected_file} was not created!"

        with open(expected_file, "r") as f:
            saved_dict = json.load(f)

        assert sorted(saved_dict.keys()) == sorted(EXPECTED_KEYS)
        assert "solar" in saved_dict[EXPECTED_REGIONS[0]].keys()


def test_get_task_data(downloader: ReiDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data".

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    epochs = 4
    mock_dict, mock_ts = get_mock_yearly_json(task, num_epochs=epochs)

    with patch.object(
        downloader, "_load_yearly_json", return_value=(mock_dict, mock_ts)
    ):
        data_dict = downloader._get_task_data(task)

    assert isinstance(data_dict, dict)
    assert set(EXPECTED_KEYS) == set(data_dict.keys())
    assert len(data_dict["epochs"]) == epochs

    for region in EXPECTED_REGIONS:
        assert region in data_dict.keys()
        for values in data_dict[region].values():
            assert len(values) == epochs


@pytest.mark.parametrize(
    "task_date, expected_json_year",
    [
        ("2020-01", 2019),
        ("2020-03", 2019),
        ("2020-04", 2020),
        ("2020-12", 2020),
    ],
)
def test_get_task_data_year_mapping(
    downloader: ReiDownloader, task_date: str, expected_json_year: int
) -> None:
    """Happy path for "_get_task_data" verifying correct yearly JSON is requested.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task_date (str): Date string for the task.
        expected_json_year (int): Expected year in the JSON URL.
    """
    task = DownloadTask(date=task_date)
    mock_out = get_mock_yearly_json(task, num_epochs=4)
    expected_url = f"{URL_BASE}data/{expected_json_year}/power-data.json"

    with patch.object(
        downloader, "_load_yearly_json", return_value=mock_out
    ) as mock_load:
        downloader._get_task_data(task)
        mock_load.assert_called_once_with(expected_url)


@pytest.mark.parametrize(
    "task_date",
    [f"{MIN_YEAR - 1}-05", f"{MIN_YEAR}-01"],
)
def test_get_task_data_before_min_date(
    downloader: ReiDownloader, task_date: str
) -> None:
    """Failure path for "_get_task_data" when requesting a month before MIN_YEAR.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task_date (str): Date string for the task.
    """
    task = DownloadTask(date=task_date)
    with pytest.raises(MissingDataError, match="No energy data available"):
        downloader._get_task_data(task)


def test_get_task_data_missing_month_data(downloader: ReiDownloader) -> None:
    """Failure path for "_get_task_data" when no timestamps match the requested month.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
    """
    task_jan = DownloadTask(date="2020-01")
    mock_dict, mock_ts = get_mock_yearly_json(task_jan, num_epochs=4)

    task_feb = DownloadTask(date="2020-02")

    with patch.object(
        downloader, "_load_yearly_json", return_value=(mock_dict, mock_ts)
    ):
        with pytest.raises(MissingDataError, match="No energy data found for month"):
            downloader._get_task_data(task_feb)


# ------------------------------------
# Tests - Locking with _download_lock
# ------------------------------------
def test_get_task_data_concurrent_tasks_single_call(downloader: ReiDownloader) -> None:
    """Happy path for "_get_task_data" that concurrent tasks share the same yearly JSON.

    This runs several tasks using the same yearly JSON file in parallel to assert that the
    underlying HTTP request is made only once, thereby ensuring the combination of
    "_download_lock" and "@lru_cache" with "_load_yearly_json" work.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
    """
    # define two tasks (months using same JSON) and example JSON for the year
    tasks = [DownloadTask(date="2020-04"), DownloadTask(date="2020-05")]

    mock_dict_t1, _ = get_mock_yearly_json(tasks[0], num_epochs=4)
    mock_dict_t2, _ = get_mock_yearly_json(tasks[1], num_epochs=4)
    mock_dict = {
        "epochs": mock_dict_t1["epochs"] + mock_dict_t2["epochs"],
        **{
            region: {
                source: mock_dict_t1[region][source] + mock_dict_t2[region][source]
                for source in ["thermal", "solar"]
            }
            for region in EXPECTED_REGIONS
        },
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_dict

    with patch("rbc.energy.rei.downloader.requests.get") as mock_get:
        mock_get.return_value = mock_resp
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            results = list(executor.map(downloader._get_task_data, tasks))

    assert len(results) == len(tasks)  # all tasks should return valid dicts
    for result in results:
        assert set(result.keys()) == set(EXPECTED_KEYS)

    assert mock_get.call_count == 1  # only one HTTP request since JSON is shared


# ----------------------------------
# Tests - Data crawling helper methods
# ----------------------------------
def test_load_yearly_json(downloader: ReiDownloader, task: DownloadTask) -> None:
    """Happy path for "_load_yearly_json" static helper.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_dict, _ = get_mock_yearly_json(task, num_epochs=3)

    with patch("rbc.energy.rei.downloader.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_dict
        mock_get.return_value = mock_resp

        data, ts = downloader._load_yearly_json("dummy-url")

    # ensure only EXPECTED_KEYS are present
    assert set(data.keys()) == set(EXPECTED_KEYS)
    assert isinstance(ts, pd.DatetimeIndex)
    assert len(ts) == len(mock_dict["epochs"])
    assert ts.tz == TIMEZONE


def test_load_yearly_json_caching(
    downloader: ReiDownloader, task: DownloadTask
) -> None:
    """Happy path for "_load_yearly_json", verifying lru_cache prevents redundant HTTP calls.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    mock_dict, _ = get_mock_yearly_json(task, num_epochs=3)

    with patch("rbc.energy.rei.downloader.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_dict
        mock_get.return_value = mock_resp

        downloader._load_yearly_json("cached-url")
        downloader._load_yearly_json("cached-url")

        mock_get.assert_called_once()


def test_load_yearly_json_warning_chronological_gap(
    downloader: ReiDownloader, task: DownloadTask
) -> None:
    """Happy path for "_load_yearly_json" to check that warning is logged if hours are missing.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    gap_dict, mock_ts = get_mock_yearly_json(task, num_epochs=10)

    # delete the middle timestamp to create a gap (in both the dict and list of timestamps)
    gap_ts = mock_ts.delete(5)
    gap_dict["epochs"].pop(5)
    for region in EXPECTED_REGIONS:
        gap_dict[region] = {
            "thermal": [1.0] * len(gap_ts),
            "solar": [2.0] * len(gap_ts),
        }

    captured_logs = []
    sink_id = logger.add(lambda msg: captured_logs.append(msg.record), level="WARNING")

    try:
        with patch("rbc.energy.rei.downloader.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = gap_dict
            mock_get.return_value = mock_response

            downloader._load_yearly_json("http://mock-url.json")

        assert len(captured_logs) == 1
        assert "timestamp continuity issue detected" in captured_logs[0]["message"]
        assert "Temporal resolution is not constant" in captured_logs[0]["message"]
    finally:
        logger.remove(sink_id)


def test_load_yearly_json_http_error(downloader: ReiDownloader) -> None:
    """Failure path for "_load_yearly_json", ensuring HTTP errors propagate for retry logic.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
    """
    with patch("rbc.energy.rei.downloader.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = exceptions.HTTPError("500")
        mock_get.return_value = mock_resp

        with pytest.raises(exceptions.HTTPError):
            downloader._load_yearly_json("dummy-url")


def test_load_yearly_json_invalid_json(downloader: ReiDownloader) -> None:
    """Failure path for "_load_yearly_json" when response body is not JSON.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
    """
    with patch("rbc.energy.rei.downloader.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.side_effect = requests.exceptions.JSONDecodeError("", "", 0)
        mock_get.return_value = mock_resp

        with pytest.raises(DataStructureError, match="json-serializable"):
            ReiDownloader._load_yearly_json("dummy-url")


@pytest.mark.parametrize(
    "modifier_func, expected_error_msg",
    [
        # 1. an expected/required key is missing from the loaded JSON dict
        (lambda d: d.pop(EXPECTED_KEYS[0]), "Missing expected JSON dict key"),
        # 2. "epochs" list does not contain datetimelike values
        (lambda d: d.update({"epochs": ["invalid"]}), "'epochs' is no longer datetime"),
        # 3. region data is not a dict
        (lambda d: d.update({EXPECTED_REGIONS[0]: [1, 2]}), "data is no longer a dict"),
        # 4. fuel type array lengths differ
        (
            lambda d: d[EXPECTED_REGIONS[0]].update(
                {list(d[EXPECTED_REGIONS[0]].keys())[0]: [1.0, 2.0]}
            ),
            "entries, but there are",
        ),
    ],
    ids=["missing_key", "invalid_epochs", "region_not_dict", "mismatching_lengths"],
)
def test_load_yearly_json_structural_failures(
    downloader: ReiDownloader,
    task: DownloadTask,
    modifier_func: Callable,
    expected_error_msg: str,
) -> None:
    """Failure paths for structural data changes in the downloaded yearly JSON.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task: DownloadTask: The metadata of a downloading task, here: date (YYYY-MM)
        modifier_func: Callable[[dict], dict]: A function that modifies the mock dictionary
        expected_error_msg: str: The expected error message for said motifier
    """
    mock_dict, _ = get_mock_yearly_json(task, num_epochs=3)
    modifier_func(mock_dict)  # execute the modifier function to mutate the dictionary

    with patch("rbc.energy.rei.downloader.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_dict
        mock_get.return_value = mock_resp

        with pytest.raises(DataStructureError, match=expected_error_msg):
            downloader._load_yearly_json("dummy-url")


# ----------------------------------
# Tests - General helper methods
# ----------------------------------
@pytest.mark.parametrize("freq", ["1h", "30min"])
def test_determine_temporal_resolution(
    downloader: ReiDownloader, task: DownloadTask, freq: str
) -> None:
    """Happy path for _determine_temporal_resolution method.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        freq (str): The frequency / intervals of the epochs.
    """
    _, mock_ts = get_mock_yearly_json(task, num_epochs=3, freq=freq)

    t_res = downloader._determine_temporal_resolution(mock_ts, context="dummy-url")
    assert t_res == freq


@pytest.mark.parametrize(
    "num_epochs, freq, expected_error_msg",
    [
        (1, "1h", "Less than 2 timestamps"),
        (3, "5.5min", "not a whole number"),
        (3, "61min", "greater than 1h"),
    ],
    ids=["too_few_timestamps", "no_whole_number", "coarser_than_hourly"],
)
def test_determine_temporal_resolution_data_structure_errors(
    downloader: ReiDownloader,
    task: DownloadTask,
    num_epochs: int,
    freq: str,
    expected_error_msg: str,
) -> None:
    """Failure paths for _determine_temporal_resolution when DataStructureErrors are raised.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
        num_epochs (int | None): The number of epochs.
        freq (str): The frequency / intervals of the epochs.
        expected_error_msg (str): The expected error message.
    """
    _, mock_ts = get_mock_yearly_json(task, num_epochs=num_epochs, freq=freq)

    with pytest.raises(DataStructureError, match=expected_error_msg):
        downloader._determine_temporal_resolution(mock_ts, context="dummy-url")


def test_determine_temporal_resolution_data_structure_error_not_monotonic(
    downloader: ReiDownloader, task: DownloadTask
) -> None:
    """Failure path for _determine_temporal_resolution when DataStructureError is raised.

    Specifically, this is for the case where the timestamps are not monotonically increasing.

    Args:
        downloader (ReiDownloader): Instance of ReiDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)
    """
    _, mock_ts = get_mock_yearly_json(task)
    corrupted_ts = pd.DatetimeIndex([mock_ts[1], mock_ts[0], mock_ts[2]])

    with pytest.raises(DataStructureError, match="not monotonically increasing"):
        downloader._determine_temporal_resolution(corrupted_ts, context="dummy-url")
