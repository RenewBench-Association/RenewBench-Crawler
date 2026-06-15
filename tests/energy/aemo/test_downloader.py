# tests/energy/aemo/test_downloader.py
"""Tests for AEMO energy data downloader."""

import asyncio
import pickle
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from openelectricity.client import APIError
from requests import exceptions

from rbc.energy.aemo import AemoDownloader
from rbc.energy.aemo.downloader import (
    EXPECTED_COLS,
    MIN_YEAR,
    VALID_NETWORKS,
    _get_start_date,
)
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


@pytest.fixture(params=["1h", "5min"])
def task(request: pytest.FixtureRequest, init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM-DD'/'YYYY-MM' depending on param from the init arguments.

    Args:
        request (FixtureRequest): Special pytest fixture used to access 'params' values.
        init_args (dict): Arguments used to initialize an AemoDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM-DD / YYYY-MM)
    """
    t_res = request.param
    year = init_args["years"][0]
    date = f"{year}-01" if t_res == "1h" else f"{year}-01-01"
    return DownloadTask(date=date, temporal_resolution=t_res)


def get_mock_df(spec_task: DownloadTask, rows: int = 1) -> pd.DataFrame:
    """Gets a mock dataframe for a specific task.

    Args:
        spec_task (DownloadTask): Metadata of a download task, here: date (YYYY-MM/-DD), t_res
        rows (int, optional): Number of rows to mock. Defaults to 1.

    Returns:
        pd.DataFrame: Mock dataframe.
    """
    tz = VALID_NETWORKS["NEM"]
    year = spec_task.year
    month = spec_task.month

    rows_list = []
    hour = 0
    for r in range(rows):
        if r % 2 == 0:
            name = "A"
            hour += 1
        else:
            name = "B"

        row: dict[str, object] = {c: name for c in EXPECTED_COLS}
        row.update(
            {
                "timestamp": datetime(year, month, 1, hour, tzinfo=tz),
                "network_id": list(VALID_NETWORKS.keys())[0],
                "unit_data_first_seen": datetime(year - 2, 1, 1, tzinfo=tz),
                "unit_data_last_seen": datetime(year + 1, 1, 1, tzinfo=tz),
                "unit_commencement_date": datetime(year - 1, 1, 1, tzinfo=tz),
                "value": 16.0,
            }
        )
        rows_list.append(row)

    return pd.DataFrame(rows_list)


def get_mock_fu(spec_task: DownloadTask, rows: int = 1) -> tuple[pd.DataFrame, dict]:
    """Get facilities/units df and lookup table (one row per unique unit).

    Args:
        spec_task (DownloadTask): Metadata of a download task, here: date (YYYY-MM/-DD), t_res
        rows (int, optional): Number of rows to mock. Defaults to 1.

    Returns:
        mock_df_fu (pd.Dataframe): Dataframe of facilities and units.
        mock_lookup_u (dict): Dict of all units and their start date.
    """
    mock_df_fu = get_mock_df(spec_task=spec_task, rows=rows)
    mock_df_fu = mock_df_fu.drop(columns=["timestamp", "value"])
    mock_df_fu = mock_df_fu.drop_duplicates(
        subset=["unit_code"]
    )  # 1 row per unique unit
    mock_lookup_u = (
        mock_df_fu.set_index("unit_code")[["network_id", "unit_data_first_seen"]]
        .rename(columns={"unit_data_first_seen": "start"})
        .to_dict(orient="index")
    )
    return mock_df_fu, mock_lookup_u


@pytest.fixture
def downloader(init_args: dict, task: DownloadTask) -> AemoDownloader:
    """Provides an AemoDownloader with mocked API and preloaded facility/unit data.

    Args:
        init_args (dict): Arguments used to initialize an AemoDownloader instance.
        task (DownloadTask): Metadata of the download tasks, here: date (YYYY-MM/-DD), t_res

    Returns:
        AemoDownloader: AemoDownloader instance.
    """
    mock_fu = get_mock_fu(spec_task=task, rows=1)

    with patch("rbc.energy.aemo.downloader.OEClient") as mock_client:
        mock_client.return_value.get_current_user.return_value = None

        with patch.object(
            AemoDownloader, "_get_facilities_and_units", return_value=mock_fu
        ):
            return AemoDownloader(**init_args)


# ----------------------------------
# Tests - Initialization
# ----------------------------------
def test_downloader_initialization(downloader: AemoDownloader, init_args: dict) -> None:
    """Happy path for class initialization.

    Check that the AemoDownloader sets up paths and checkpoint correctly.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
        init_args (dict): Arguments used to initialize an AemoDownloader instance.
    """
    assert downloader.years == init_args["years"]
    assert downloader.temporal_resolutions == init_args["temporal_resolutions"]
    assert downloader.output_path == init_args["output_path"]
    assert downloader.checkpoint_path == Path(init_args["output_path"], "status.pickle")
    assert downloader.checkpoint == {}
    assert downloader.valid_u  # assert not empty
    assert downloader.lookup_u
    assert isinstance(downloader.df_fu, pd.DataFrame)


def test_downloader_initialization_invalid_tres(init_args: dict) -> None:
    """Failure path for class initialization with invalid temporal resolution.

    Args:
        init_args (dict): Arguments used to initialize an AemoDownloader instance.
    """
    args = init_args.copy()
    args["temporal_resolutions"] = ["invalid"]

    with pytest.raises(InvalidError, match="Invalid temporal resolution"):
        AemoDownloader(**args)


def test_downloader_initialization_invalid_access(init_args: dict) -> None:
    """Failure path for class initialization with invalid request.

    Args:
        init_args (dict): Arguments used to initialize an AemoDownloader instance.
    """
    error = APIError(status_code=401, detail="Unauthorized")

    with patch("rbc.energy.aemo.downloader.OEClient") as mock_client:
        mock_client.return_value.get_current_user.side_effect = error
        with pytest.raises(InvalidError, match="connection failed"):
            AemoDownloader(**init_args)


def test_download_data_resume(init_args: dict, task: DownloadTask) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    If all daily / monthly tasks are already marked as done in the checkpoint, the
    downloader should not attempt any downloads.

    Args:
        init_args (dict): Arguments used to initialize an AemoDownloader instance.
        task (DownloadTask): Metadata of the download tasks, here: date (YYYY-MM/-DD), t_res
    """
    args = init_args.copy()

    # save a fake checkpoint file
    checkpoint = {
        DownloadTask(date=d, temporal_resolution=t_res).identifier: 1
        for t_res in args["temporal_resolutions"]
        for y in args["years"]
        for d in (
            pd.date_range(start=f"{y}-01", end=f"{y}-12", freq="MS").strftime("%Y-%m")
            if t_res == "1h"
            else pd.date_range(start=f"{y}-01-01", end=f"{y}-12-31").strftime(
                "%Y-%m-%d"
            )
        )
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True
    mock_fu = get_mock_fu(task)

    with patch("rbc.energy.aemo.downloader.OEClient") as mock_client:
        with patch.object(
            AemoDownloader, "_get_facilities_and_units", return_value=mock_fu
        ):
            mock_client.return_value.get_current_user.return_value = None
            downloader = AemoDownloader(**args)

            with patch.object(downloader, "_download_task_data") as mock_dump:
                mock_dump.return_value = 1
                downloader.download_data()

                assert mock_dump.call_count == 0
                assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_task_data(downloader: AemoDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
        task (DownloadTask): Metadata of the download tasks, here: date (YYYY-MM/-DD), t_res
    """
    mock_df = pd.DataFrame({"value": [16.2]})

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task).with_suffix(".csv")
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["value"] == 16.2


def test_get_task_data(downloader: AemoDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
        task (DownloadTask): Metadata of the download tasks, here: date (YYYY-MM/-DD), t_res
    """
    mock_df = get_mock_df(task)
    mock_df = mock_df[["timestamp", "unit_code", "value"]]

    with patch("rbc.energy.aemo.downloader.asyncio.run") as mock_run:
        mock_run.return_value = mock_df.to_dict(orient="records")
        df = downloader._get_task_data(task)
        mock_run.call_args[0][0].close()  # close coroutine to prevent RuntimeWarning

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["value"] == 16.0
    assert mock_run.call_count == 1


def test_get_task_data_no_generation_data(
    downloader: AemoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
        task (DownloadTask): Metadata of the download tasks, here: date (YYYY-MM/-DD), t_res
    """
    mock_df_list = pd.DataFrame(columns=EXPECTED_COLS).to_dict(orient="records")

    with patch("rbc.energy.aemo.downloader.asyncio.run") as mock_run:
        mock_run.return_value = mock_df_list
        with pytest.raises(MissingDataError, match="No generation data"):
            downloader._get_task_data(task)
        mock_run.call_args[0][0].close()


def test_get_task_data_structure_changed(
    downloader: AemoDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when dataframe doesn't have all columns.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
        task (DownloadTask): Metadata of the download tasks, here: date (YYYY-MM/-DD), t_res
    """
    mock_df = get_mock_df(task).drop(columns="unit_code")

    with patch("rbc.energy.aemo.downloader.asyncio.run") as mock_run:
        mock_run.return_value = mock_df.to_dict(orient="records")
        with pytest.raises(DataStructureError, match="Relevant column"):
            downloader._get_task_data(task)
        mock_run.call_args[0][0].close()


# ----------------------------------
# Tests - Data crawling async methods
# ----------------------------------
def test_fetch_task_data_flattens_results(
    downloader: AemoDownloader, task: DownloadTask
) -> None:
    """Happy path for nested "fetch_task_data" method to see if results are flattened.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
        task (DownloadTask): Metadata of the download tasks, here: date (YYYY-MM/-DD), t_res
    """
    mock_df = get_mock_df(task, 4)
    u1 = mock_df["unit_code"].iloc[0]
    u2 = mock_df["unit_code"].iloc[1]
    mock_df_fu, mock_lookup_u = get_mock_fu(task, 4)
    downloader.valid_u = [u1, u2]
    downloader.lookup_u = mock_lookup_u
    downloader.df_fu = mock_df_fu
    fetch_out_cols = ["timestamp", "unit_code", "value"]

    async def fake_fetch(*args, **kwargs):
        """Fake _fetch_unit_data_async method that returns a list per unit."""
        unit_code = kwargs.get("unit_code")
        if unit_code == u1:
            return mock_df[fetch_out_cols].iloc[[0, 2]].to_dict("records")
        elif unit_code == u2:
            return mock_df[fetch_out_cols].iloc[[1, 3]].to_dict("records")
        return []

    with (
        patch.object(downloader, "_fetch_unit_data_async") as mock_fetch,
        patch("rbc.energy.aemo.downloader.AsyncOEClient") as mock_async_client,
    ):
        mock_fetch.side_effect = fake_fetch
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)
        df = downloader._get_task_data(task)

    assert len(df) == 4  # 2 units x 2 rows each, flattened
    assert set(df["unit_code"]) == {u1, u2}  # two unique units
    assert len(set(df["timestamp"])) == 2  # two unique timestamps
    assert mock_fetch.call_count == 2


@pytest.mark.asyncio
async def test_fetch_unit_data_async() -> None:
    """Happy path for "_fetch_unit_data_async" method."""
    ts_start = datetime(2020, 1, 1, 1, 0, 1)
    ts_end = ts_start.replace(hour=ts_start.hour + 1)

    mock_data_points = [
        MagicMock(root=(ts_start, 10.0)),
        MagicMock(root=(ts_end, 20.0)),
    ]
    mock_result = MagicMock(data=mock_data_points)
    mock_series = MagicMock(results=[mock_result])
    mock_response = MagicMock(data=[mock_series])

    mock_client = AsyncMock()
    mock_client.get_facility_data = AsyncMock(return_value=mock_response)

    result = await AemoDownloader._fetch_unit_data_async(
        async_client=mock_client,
        semaphore=asyncio.Semaphore(10),
        network_code="NEM",
        unit_code="A",
        date_start=ts_start,
        date_end=ts_end,
        temporal_res="1h",
    )
    assert len(result) == 2
    assert result[0] == {"timestamp": ts_start, "unit_code": "A", "value": 10.0}


@pytest.mark.asyncio
async def test_fetch_unit_data_async_no_data() -> None:
    """Happy path for "_fetch_unit_data_async" when API returns 404 (no data)."""
    mock_client = MagicMock()
    mock_client.get_facility_data = MagicMock(
        side_effect=APIError(status_code=404, detail="Not Found")
    )
    semaphore = asyncio.Semaphore(10)

    result = await AemoDownloader._fetch_unit_data_async(
        async_client=mock_client,
        semaphore=semaphore,
        network_code="NEM",
        unit_code="UNIT1",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 2, 1),
        temporal_res="1h",
    )
    assert result == []


@pytest.mark.asyncio
async def test_fetch_unit_data_async_server_error() -> None:
    """Failure path for "_fetch_unit_data_async" when API returns a server error."""
    mock_client = MagicMock()
    mock_client.get_facility_data = MagicMock(
        side_effect=APIError(status_code=500, detail="Internal Server Error")
    )
    semaphore = asyncio.Semaphore(10)

    with pytest.raises(exceptions.HTTPError, match="Error 500"):
        await AemoDownloader._fetch_unit_data_async(
            async_client=mock_client,
            semaphore=semaphore,
            network_code="NEM",
            unit_code="UNIT1",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 2, 1),
            temporal_res="1h",
        )


# ----------------------------------
# Tests - Data crawling helper methods
# ----------------------------------
def test_get_facilities_and_units(downloader: AemoDownloader) -> None:
    """Happy path for "_get_facilities_and_units", ensuring correct df and lookup.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
    """
    tz = VALID_NETWORKS["NEM"]
    mock_facility = MagicMock()
    mock_facility.model_dump.return_value = {
        "code": "FAC1",
        "name": "Facility 1",
        "network_id": "NEM",
        "network_region": "NSW1",
        "description": "<b>A facility</b>",
        "npi_id": None,
        "location": {"lat": 0.0, "lng": 0.0},
        "created_at": None,
        "updated_at": None,
        "units": [
            {
                "code": "UNIT1",
                "fueltech_id": "solar",
                "status_id": "operating",
                "dispatch_type": "GENERATOR",
                "capacity_registered": 100.0,
                "capacity_maximum": 110.0,
                "capacity_storage": None,
                "data_first_seen": datetime(2018, 6, 15, tzinfo=tz),
                "data_last_seen": datetime(2025, 1, 1, tzinfo=tz),
                "commencement_date": datetime(2018, 1, 1, tzinfo=tz),
            }
        ],
    }
    mock_facilities = MagicMock(data=[mock_facility])

    with patch.object(
        downloader.client, "get_facilities", return_value=mock_facilities
    ):
        df_fu, lookup_u = downloader._get_facilities_and_units()

    assert not df_fu.empty
    assert "unit_code" in df_fu.columns
    assert "<b>" not in df_fu.iloc[0]["description"]

    assert "UNIT1" in lookup_u
    assert lookup_u["UNIT1"]["network_id"] == "NEM"


def test_get_facilities_and_units_no_data(downloader: AemoDownloader) -> None:
    """Failure path for "_get_facilities_and_units" when no data is returned.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
    """
    facilities = MagicMock(data=[])

    with patch.object(downloader.client, "get_facilities", return_value=facilities):
        with pytest.raises(DataStructureError, match="No facilities"):
            downloader._get_facilities_and_units()


def test_get_facilities_and_units_bad_structure(downloader: AemoDownloader) -> None:
    """Failure path for "_get_facilities_and_units" when data can't be transformed.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
    """
    mock_facility = MagicMock()
    mock_facility.model_dump.side_effect = AttributeError("no model_dump")
    mock_response = MagicMock(data=[mock_facility])

    with patch.object(downloader.client, "get_facilities", return_value=mock_response):
        with pytest.raises(DataStructureError, match="Facility data"):
            downloader._get_facilities_and_units()


def test_get_facilities_and_units_missing_column(downloader: AemoDownloader) -> None:
    """Failure path when facility data is missing required columns.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
    """
    mock_facility = MagicMock()
    mock_facility.model_dump.return_value = {"code": "A", "name": "Facility A"}
    mock_response = MagicMock(data=[mock_facility])

    with patch.object(downloader.client, "get_facilities", return_value=mock_response):
        with pytest.raises(DataStructureError, match="Relevant column"):
            downloader._get_facilities_and_units()


def test_get_valid_units(downloader: AemoDownloader) -> None:
    """Happy path for "_get_valid_units", ensuring correct filtering by year and logging.

    Args:
        downloader (AemoDownloader): Instance of AemoDownloader class.
    """
    unit_code = list(downloader.lookup_u.keys())[0]
    start_year = downloader.lookup_u[unit_code]["start"].year

    with patch("rbc.energy.aemo.downloader.logger") as mock_logger:
        # year after start: unit included
        valid = downloader._get_valid_units(units=[unit_code], year=start_year + 1)
        assert unit_code in valid

        # exact start year: unit included
        valid_exact = downloader._get_valid_units(units=[unit_code], year=start_year)
        assert unit_code in valid_exact

        # year before start: unit excluded
        valid_before = downloader._get_valid_units(
            units=[unit_code], year=start_year - 1
        )
        assert unit_code not in valid_before

        # verbose=False: warning logged but no "Skipping" detail
        mock_logger.reset_mock()
        downloader._get_valid_units(
            units=[unit_code], year=start_year - 1, verbose=False
        )
        assert mock_logger.warning.call_count == 1
        assert "Skipping" not in mock_logger.warning.call_args_list[0][0][0]

        # verbose=True: both warning messages logged including "Skipping"
        mock_logger.reset_mock()
        downloader._get_valid_units(
            units=[unit_code], year=start_year - 1, verbose=True
        )
        assert mock_logger.warning.call_count == 2
        assert "Skipping" in mock_logger.warning.call_args_list[1][0][0]

        # verbose=True, all valid: info message logged
        mock_logger.reset_mock()
        downloader._get_valid_units(
            units=[unit_code], year=start_year + 1, verbose=True
        )
        assert mock_logger.info.call_count == 1
        assert "All" in mock_logger.info.call_args_list[0][0][0]


# ----------------------------------
# Tests - General helper methods
# ----------------------------------
@pytest.mark.parametrize(
    "d1_year, d2_year, expected_year",
    [
        (2020, 2019, 2020),
        (2020, None, 2020),
        (None, 2019, 2019),
        (None, None, MIN_YEAR),
    ],
)
def test_get_start_date(
    d1_year: int | None, d2_year: int | None, expected_year: int
) -> None:
    """Happy path for "_get_start_date" function.

    Args:
        d1_year (int | None): First potential start date year.
        d2_year (int | None): Second potential start date year.
        expected_year (int): Expected year of the function output.
    """
    network_id = list(VALID_NETWORKS.keys())[0]
    tz = VALID_NETWORKS[network_id]

    d1, d2, expected_out = [
        datetime(y, 1, 1, tzinfo=tz) if isinstance(y, int) else None
        for y in [d1_year, d2_year, expected_year]
    ]

    out = _get_start_date(d1=d1, d2=d2, network_id=network_id)
    assert out == expected_out
    assert out.tzinfo is tz


def test_get_start_date_invalid_network() -> None:
    """Failure path for "_get_start_date" function when an invalid network is provided."""
    with pytest.raises(InvalidError, match="Invalid network ID"):
        _get_start_date(d1=None, d2=None, network_id="fake_ID")
