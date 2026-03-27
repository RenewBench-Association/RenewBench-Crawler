# tests/energy/entsoe/test_downloader.py
"""Tests for Entso-E energy data downloader."""

import pickle
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from entsoe.query.decorators import ServiceUnavailableError

from rbc.energy.entsoe import EntsoeDownloader
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
        dict: Initialisation arguments.
    """
    return {
        "token": "fake_token",
        "output_path": tmp_path,
        "years": [2020],
        "bidding_zones": ["10YES-REE------0"],
        "resume": False,
    }


@pytest.fixture
def downloader(init_args: dict) -> EntsoeDownloader:
    """Returns an instantiated EntsoeDownloader.

    Args:
        init_args (dict): Arguments used to initialize an EntsoeDownloader instance.

    Returns:
        EntsoeDownloader: Instance of EntsoeDownloader class.
    """
    with patch("rbc.energy.entsoe.downloader.set_config"):
        with patch("rbc.energy.entsoe.downloader.get_config"):
            return EntsoeDownloader(**init_args)


@pytest.fixture
def task(init_args: dict) -> DownloadTask:
    """Gets a task as 'date=YYYY-MM-DD,bidding_zone=<ZONE>' from the init arguments.

    Args:
        init_args (dict): Arguments used to initialize an EntsoeDownloader instance.

    Returns:
        DownloadTask: The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    return DownloadTask(
        date=f"{init_args['years'][0]}-01-01",
        bidding_zone=init_args["bidding_zones"][0],
    )


# ----------------------------------
# Tests - Initialization
# ----------------------------------
@pytest.mark.parametrize("bz, valid", [("10YES-REE------0", True), (" ", False)])
def test_downloader_initialization(init_args: dict, bz: str, valid: bool) -> None:
    """Happy path for class initialization.

    Check that the EntsoeDownloader sets up paths and checkpoint correctly.

    Args:
        init_args (dict): Arguments used to initialize an EntsoeDownloader instance.
        bz (str): The bidding zone to use.
        valid (bool): Whether the bidding zone is valid (True) or not (False).
    """
    args = init_args.copy()
    args["bidding_zones"] = [bz]

    if not valid:
        with pytest.raises(InvalidError, match="not supported"):
            EntsoeDownloader(**args)
    else:
        with patch("rbc.energy.entsoe.downloader.set_config"):
            with patch("rbc.energy.entsoe.downloader.get_config"):
                downloader = EntsoeDownloader(**args)

        assert downloader.bidding_zones == args["bidding_zones"]
        assert downloader.years == args["years"]
        assert downloader.output_path == args["output_path"]
        assert downloader.checkpoint_path == Path(
            init_args["output_path"], "status.pickle"
        )
        assert downloader.checkpoint == {}


def test_downloader_initialization_invalid_config(init_args: dict) -> None:
    """Failure path for class initialization with invalid API configuration.

    Args:
        init_args (dict): Arguments used to initialize an AesoDownloader instance.
    """
    with patch("rbc.energy.entsoe.downloader.set_config"):
        with patch("rbc.energy.entsoe.downloader.get_config") as mock_config:
            mock_config.return_value.security_token = None
            with pytest.raises(InvalidError, match="failed to successfully configure"):
                EntsoeDownloader(**init_args)


def test_download_data_resume(init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    Args:
        init_args (dict): Arguments used to initialize an EntsoeDownloader instance.
    """
    args = init_args.copy()

    # save a fake checkpoint file
    bz = args["bidding_zones"][0]
    y = args["years"][0]
    checkpoint = {
        DownloadTask(date=d, bidding_zone=bz).identifier: 1
        for d in pd.date_range(start=f"{y}-01-01", end=f"{y}-12-31").strftime(
            "%Y-%m-%d"
        )
    }
    checkpoint_path = Path(args["output_path"], "status.pickle")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True

    with patch("rbc.energy.entsoe.downloader.set_config"):
        with patch("rbc.energy.entsoe.downloader.get_config"):
            downloader = EntsoeDownloader(**args)

            with patch.object(downloader, "_download_task_data") as mock_dump:
                mock_dump.return_value = 1
                downloader.download_data()

                assert mock_dump.call_count == 0
                assert downloader.checkpoint == checkpoint


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_download_day_data(downloader: EntsoeDownloader, task: DownloadTask) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    mock_df = pd.DataFrame({"Generation_MW": [16.2], "Temporal_Resolution": ["PT60M"]})

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = downloader._build_task_path(task)
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["Generation_MW"] == 16.2


def test_get_task_data(downloader: EntsoeDownloader, task: DownloadTask) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    timestamp = f"{task.date}T00:00:00+00:00"
    return_value = [
        {
            "timestamp": timestamp,
            "time_series.mkt_psrtype.power_system_resources.name": "Test Plant",
            "time_series.mkt_psrtype.power_system_resources.m_rid.value": "X",
            "time_series.mkt_psrtype.psr_type": "B01",
            "time_series.mkt_psrtype.power_system_resources.nominal_p": 200,
            "time_series.period.point.quantity": 100,
            "time_series.period.point.secondary_quantity": 0,
            "time_series.quantity_measure_unit_name": "MAW",
            "time_series.period.resolution": "PT60M",
        }
    ]

    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        with patch("rbc.energy.entsoe.downloader.extract_records") as mock_extract:
            mock_api.return_value.query_api.return_value = return_value
            mock_extract.return_value = return_value

            df = downloader._get_task_data(task)

    assert not df.empty
    assert len(df) == 1
    assert "timestamp" in df.columns
    assert "Generation_MW" in df.columns
    assert df.iloc[0]["timestamp"] == timestamp
    assert df.iloc[0]["Generation_MW"] == 100
    assert mock_extract.call_count == 1


def test_get_task_data_no_data_for_old_year(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the bz has no data for the task's year.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    old_year_task = task.update(date="1900-01-01")

    with pytest.raises(MissingDataError, match="No energy data for year"):
        downloader._get_task_data(old_year_task)


def test_get_task_data_service_unavailable(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the service is unavailable.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.return_value.query_api.side_effect = ServiceUnavailableError

        with pytest.raises(ConnectionError, match="unavailable"):
            downloader._get_task_data(task)


def test_get_task_data_requested_no_requested_data_returned(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the requested data is not returned.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.query_api.return_value = "not a list"

        with pytest.raises(ConnectionError, match="did not return requested"):
            downloader._get_task_data(task)


def test_get_task_data_no_generation_data(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when no generation data is available.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.return_value.query_api.return_value = []

        with pytest.raises(MissingDataError, match="No energy data available"):
            downloader._get_task_data(task)


def test_get_task_data_structure_changed(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Failure path for "_get_task_data" method when the expected columns are missing.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api, patch(
        "rbc.energy.entsoe.downloader.extract_records"
    ) as mock_extract, patch("rbc.energy.entsoe.downloader.add_timestamps") as mock_ts:
        mock_api.return_value.query_api.return_value = ["dummy_data"]
        mock_extract.return_value = [{"some_col": 1}]
        mock_ts.return_value = [{"some_col": 1, "timestamp": "2020-01-01"}]

        with pytest.raises(DataStructureError, match="structure change detected"):
            downloader._get_task_data(task)


# ----------------------------------
# Tests - Data crawling helper methods
# ----------------------------------
def test_save_task_data_single_tres(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Happy path for _save_task_data with one temporal res and missing data rows are removed.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    df = pd.DataFrame(
        {
            "Generation_MW": [10.0, 20.0],
            "Temporal_Resolution": ["PT60M", None],
        }
    )
    downloader._save_task_data(task, df)

    expected_file = downloader._build_task_path(task.update(temporal_resolution="1h"))
    assert expected_file.is_file()

    saved_df = pd.read_csv(expected_file)
    assert len(saved_df) == 1  # row with missing temporal resolution value removed
    assert saved_df.iloc[0]["Generation_MW"] == 10.0


def test_save_task_data_two_tres(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Happy path for _save_task_data with two temporal resolutions.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD), bz
    """
    df = pd.DataFrame(
        {
            "Generation_MW": [10.0, 20.0],
            "Temporal_Resolution": ["PT60M", "PT20M"],
        }
    )
    downloader._save_task_data(task, df)

    file_1h = downloader._build_task_path(task.update(temporal_resolution="1h"))
    file_20min = downloader._build_task_path(task.update(temporal_resolution="20min"))

    assert file_1h.is_file()
    assert file_20min.is_file()

    df_1h = pd.read_csv(file_1h)
    df_20min = pd.read_csv(file_20min)

    assert len(df_1h) == 1
    assert len(df_20min) == 1
    assert df_1h.iloc[0]["Generation_MW"] == 10.0
    assert df_20min.iloc[0]["Generation_MW"] == 20.0


def test_save_task_data_invalid_tres(
    downloader: EntsoeDownloader, task: DownloadTask
) -> None:
    """Failure path for _save_task_data when provided temporal resolution isn't supported."""
    df = pd.DataFrame(
        {
            "timestamp": [f"{task.date}T00:00:00+00:00"],
            "Generation_MW": [16.2],
            "Temporal_Resolution": ["INVALID"],
        }
    )
    with pytest.raises(DataStructureError, match="Unknown ENTSO-E temporal resolution"):
        downloader._save_task_data(task, df)


@pytest.mark.parametrize(
    "tres, tres_normalized",
    [
        ("PT60M", "1h"),
        ("PT20M", "20min"),
        ("PT5M", "5min"),
    ],
)
def test_normalize_temporal_resolution(tres: str, tres_normalized: str) -> None:
    """Happy path for _normalize_temporal_resolution.

    Args:
        tres (str): Raw temporal resolution string.
        tres_normalized (str): Expected temporal resolution string.
    """
    assert EntsoeDownloader._normalize_temporal_resolution(tres) == tres_normalized


@pytest.mark.parametrize("invalid_tres", ["PT1H", "invalid", "", "60M"])
def test_normalize_temporal_resolution_invalid(invalid_tres: str) -> None:
    """Failure path for _normalize_temporal_resolution with unsupported format.

    Args:
        invalid_tres (str): Invalid raw temporal resolution string.
    """
    with pytest.raises(DataStructureError, match="Unknown ENTSO-E temporal resolution"):
        EntsoeDownloader._normalize_temporal_resolution(invalid_tres)
