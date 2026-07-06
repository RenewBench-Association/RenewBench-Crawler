"""Tests for CEN energy data downloader."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from loguru import logger
from requests import exceptions

from rbc.energy.cen import CenDownloader
from rbc.energy.cen.downloader import EXPECTED_COLS
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
def downloader(init_args: dict) -> CenDownloader:
    """Provides a CenDownloader instance with a mocked connectivity check.

    Args:
        init_args (dict): Arguments used to initialize a CenDownloader instance.

    Returns:
        CenDownloader: CenDownloader instance.
    """
    with patch("rbc.energy.cen.downloader.requests.get") as mock_get:
        # Used in __init__ for _check_connection
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        return CenDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM-DD' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize a CenDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    year = init_args["years"][0]
    return DownloadTask(date=f"{year}-01-01")


def get_mock_cen_json(
    date: str | None = None,
    data: list | None = None,
    total_pages: int = 1,
    page: int = 1,
) -> dict:
    """Helper to generate an argument-dependent CEN response body.

    Args:
        date (str | None): The task date (YYYY-MM-DD).
        data (list | None): Data list of CEN response body.
        total_pages (int): Total number of pages.
        page (int): Current page number.

    Returns:
        dict: Dictionary with CEN response body.
    """
    if date is not None and data is None:
        data = [
            {
                "id_opreal": 1,
                "llave_opreal": "L1",
                "id_central": 10,
                "central": "Plant A",
                "gen_real_mw": 100.0,
                "fecha_hora": f"{date}T00:00:00",
                "hora": 0,
                "potencia_maxima": 120.0,
                "id_propietario": 5,
                "propietario": "Owner A",
                "id_coordinado": 7,
                "coordinado": "Coord A",
                "tipo_tecnologia": "Solar",
                "subtipo_tecnologia": "PV",
                "factor_ernc": 1.0,
                "alcance": "Some",
                "valor_ernc": 100.0,
            }
        ]
    if data is None:
        data = []

    return {
        "data": data,
        "totalPages": total_pages,
        "page": page,
    }


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: CenDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the CenDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        init_args (dict): Arguments used to initialize a CenDownloader instance.
    """
    assert downloader.token == init_args["token"]
    assert downloader.years == init_args["years"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid token / access.

    Args:
        init_args (dict): Arguments used to initialize a CenDownloader instance.
    """
    with patch("rbc.energy.cen.downloader.requests.get") as mock_get:
        mock_resp = MagicMock(status_code=401)
        mock_resp.raise_for_status.side_effect = exceptions.HTTPError(401)
        mock_get.return_value = mock_resp

        with pytest.raises(ConnectionError, match="CEN API/URL access failed"):
            CenDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    If all daily tasks are already marked as done in the checkpoint, the
    downloader should not attempt any downloads.

    Args:
        init_args (dict): Arguments used to initialize a CenDownloader instance.
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

    with patch("rbc.energy.cen.downloader.requests.get") as mock_get:
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        downloader = CenDownloader(**args)

        with patch.object(downloader, "_download_task_data") as mock_dump:
            mock_dump.return_value = 1
            downloader.download_data()

            assert mock_dump.call_count == 0
            assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: CenDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_df = pd.DataFrame({"gen_real_mw": [16.2]})

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task).with_suffix(".csv")
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["gen_real_mw"] == 16.2


def test_get_task_data(downloader: CenDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_body = get_mock_cen_json(task.date)
    response = MagicMock(status_code=200)
    response.json.return_value = mock_body

    with patch(
        "rbc.energy.cen.downloader.requests.get", return_value=response
    ) as mock_get:
        df = downloader._get_task_data(task)

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["fecha_hora"].startswith(task.date)
    assert df.iloc[0]["gen_real_mw"] == 100.0
    assert mock_get.call_count >= 1


def test_get_task_data_multiple_pages(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Happy path for "_get_task_data" ensuring pagination is handled correctly.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD).
    """
    body_page1 = get_mock_cen_json(date=task.date, total_pages=2, page=1)
    body_page2 = get_mock_cen_json(date=task.date, total_pages=2, page=2)

    resp1 = MagicMock(status_code=200)
    resp1.json.return_value = body_page1
    resp2 = MagicMock(status_code=200)
    resp2.json.return_value = body_page2

    with patch("rbc.energy.cen.downloader.requests.get") as mock_get:
        mock_get.side_effect = [resp1, resp2]
        df = downloader._get_task_data(task)

    assert len(df) == 2
    assert set(df["fecha_hora"]) == {f"{task.date}T00:00:00"}
    assert mock_get.call_count == 2


def test_get_task_data_network_retry(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" when transient network errors occur.

    Ensures that network issues (RequestException) are retried rather than raised.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = get_mock_cen_json(task.date)

    captured_logs = []
    sink_id = logger.add(lambda msg: captured_logs.append(msg.record), level="WARNING")

    try:
        with (
            patch("rbc.energy.cen.downloader.requests.get") as mock_get,
            patch("rbc.energy.cen.downloader.time.sleep") as mock_sleep,
        ):
            mock_get.side_effect = [exceptions.ConnectionError(), mock_resp]

            df = downloader._get_task_data(task)

            assert not df.empty
            assert mock_get.call_count == 2
            mock_sleep.assert_called_once()
            assert any(
                "Retrying page request" in log["message"] for log in captured_logs
            )
    finally:
        logger.remove(sink_id)


def test_get_task_data_network_fail(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the network error limit is reached.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    with (
        patch("rbc.energy.cen.downloader.requests.get") as mock_get,
        patch("rbc.energy.cen.downloader.time.sleep") as mock_sleep,
    ):
        mock_get.side_effect = [exceptions.HTTPError] * (MAX_RETRIES + 1)

        with pytest.raises(exceptions.HTTPError, match="Network retries exceeded"):
            downloader._get_task_data(task)

        assert mock_get.call_count == MAX_RETRIES + 1
        assert mock_sleep.call_count == MAX_RETRIES


def test_download_task_data_retry_exhaustion(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the TOTAL network error limit is reached.

    Not just of the CenDownloader, but in "_download_task_data" of EnergyDownloader as well!
    This tests its "4. everything else (500s/timeout/connection) -> classic retry" path.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    with (
        patch("rbc.energy.cen.downloader.requests.get") as mock_get,
        patch("rbc.energy.cen.downloader.time.sleep") as mock_sleep,
    ):
        mock_get.side_effect = [exceptions.HTTPError("Connection dropped")] * (
            (1 + MAX_RETRIES) * (1 + MAX_RETRIES)
        )

        status = downloader._download_task_data(task)

        # task (run through child) -> C: 4 attempts, P: (1st + 3 reruns) => 4 * 4 = 16
        assert mock_get.call_count == 16
        # sleep (in child & parent) -> C: 3 retries, P: (1st + 3 reruns) + 3 direct call => 15
        assert mock_sleep.call_count == 15
        assert status == 0  # parent will have to give up and define as unfulfilled (0)


def test_get_task_data_rate_limit_fail(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the rate limit is reached (429).

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)
    """
    with (
        patch("rbc.energy.cen.downloader.requests.get") as mock_get,
        patch("rbc.energy.cen.downloader.time.sleep") as mock_sleep,
    ):
        resp_429 = MagicMock(status_code=429)
        mock_get.side_effect = [resp_429] * (MAX_RETRIES + 1)

        with pytest.raises(exceptions.HTTPError, match="CEN API rate limit"):
            downloader._get_task_data(task)

        assert mock_get.call_count == MAX_RETRIES + 1
        assert mock_sleep.call_count == MAX_RETRIES


def test_get_task_data_server_overload(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" when server overload persists (500).

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD).
    """
    with (
        patch("rbc.energy.cen.downloader.requests.get") as mock_get,
        patch("rbc.energy.cen.downloader.time.sleep"),
    ):
        # three retries with 500, then one final 500 that should raise HTTPError
        resp_500 = MagicMock(status_code=500, text="server error")
        mock_get.side_effect = [resp_500] * 4

        with pytest.raises(exceptions.HTTPError, match="despite page size reduction"):
            downloader._get_task_data(task)

        assert mock_get.call_count == 4
        # check that the pageSize parameter decreases across calls
        page_sizes = [
            call.kwargs["params"]["pageSize"] for call in mock_get.call_args_list
        ]
        assert page_sizes == sorted(page_sizes, reverse=True)


def test_get_task_data_http_error_other_code(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" when a non-200/-429/-500 code is returned.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD).
    """
    resp_400 = MagicMock(status_code=400, text="bad request")

    with patch("rbc.energy.cen.downloader.requests.get", return_value=resp_400):
        with pytest.raises(exceptions.HTTPError, match="API request failed: 400"):
            downloader._get_task_data(task)


@pytest.mark.parametrize("return_val", [{}, {"data": []}])
def test_get_task_data_failed_response_parsing(
    downloader: CenDownloader, task: DownloadTask, return_val: dict
) -> None:
    """Failure path for "_get_task_data" when the parsed response is incomplete.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD).
        return_val (dict): Return value from _get_task_data.
    """
    response = MagicMock(status_code=200)
    response.json.return_value = return_val

    with patch("rbc.energy.cen.downloader.requests.get", return_value=response):
        with pytest.raises(DataStructureError, match="Failed parsing"):
            downloader._get_task_data(task)


@pytest.mark.parametrize("total_pages", [0, 1])
def test_get_task_data_missing_data(
    downloader: CenDownloader,
    task: DownloadTask,
    total_pages: int,
) -> None:
    """Failure path for '_get_task_data' when generation data is completely empty.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD).
        total_pages (int): Total number of pages to fetch.
    """
    mock_body = get_mock_cen_json(date=None, data=[], total_pages=total_pages, page=1)
    response = MagicMock(status_code=200)
    response.json.return_value = mock_body

    with patch("rbc.energy.cen.downloader.requests.get", return_value=response):
        with pytest.raises(MissingDataError, match="No energy data available"):
            downloader._get_task_data(task)


def test_get_task_data_structure_changed(
    downloader: CenDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" when dataframe doesn't have all columns.

    Args:
        downloader (CenDownloader): Instance of CenDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD).
    """
    # create body with one EXPECTED_COLS missing
    body = get_mock_cen_json(date=task.date)
    for row in body["data"]:
        row.pop(EXPECTED_COLS[-1])

    response = MagicMock(status_code=200)
    response.json.return_value = body

    with patch("rbc.energy.cen.downloader.requests.get", return_value=response):
        with pytest.raises(DataStructureError, match="Missing columns"):
            downloader._get_task_data(task)
