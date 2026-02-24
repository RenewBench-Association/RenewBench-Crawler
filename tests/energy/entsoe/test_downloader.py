# tests/energy/entsoe/test_downloader.py
import pickle
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pandas as pd
import pytest
from entsoe.query.decorators import ServiceUnavailableError

from rbc.energy.entsoe import EntsoeDownloader
from rbc.energy.utils import DataStructureError


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def api_config() -> Generator:
    """Fixture that patches the entsoe-apy package configuration.

    Yields:
       patched successful api configuration.
    """
    with patch("rbc.energy.entsoe.downloader.set_config"):
        with patch("rbc.energy.entsoe.downloader.get_config") as mock_get:
            mock_get.return_value.security_token = "fake_token"
            yield


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
def downloader(api_config: Generator, init_args: dict) -> EntsoeDownloader:
    """Returns an instantiated EntsoeDownloader.

    Args:
        api_config (Generator): Fixture that patches the ENTSO-E global configuration.
        init_args (dict): Arguments used to initialise an EntsoeDownloader instance.

    Returns:
        dl (EntsoeDownloader): Instance of EntsoeDownloader class.
    """
    dl = EntsoeDownloader(**init_args)
    return dl


@pytest.fixture
def download_args(init_args: dict) -> tuple[tuple, dict, Path]:
    """Gets a set of download arguments from the initialisation arguments.

    Args:
        init_args (dict): Arguments used to initialise an EntsoeDownloader instance.

    Returns:
        tuple[tuple, dict, Path]: Tuple of ((bidding zone, date), checkpoint,
        checkpoint_path) for downloading.
    """
    task = (init_args["bidding_zones"][0], f"{init_args['years'][0]}-01-01")
    checkpoint: dict = {}
    checkpoint_path = Path(
        init_args["output_path"], init_args["bidding_zones"][0], "status.pickle"
    )
    return task, checkpoint, checkpoint_path


# ----------------------------------
# Tests - Initialization
# ----------------------------------
@pytest.mark.parametrize("bz, valid", [("10YES-REE------0", True), (" ", False)])
def test_downloader_initialization(
    api_config: Generator, init_args: dict, bz: str, valid: bool
) -> None:
    """Happy path for class initialization.

    Check that the EntsoeDownloader sets up paths and checkpoint correctly.

    Args:
        api_config (Generator): Fixture that patches the ENTSO-E global configuration.
        init_args (dict): Arguments used to initialise an EntsoeDownloader instance.
        bz (str): The bidding zone to use.
        valid (bool): Whether the bidding zone is valid (True) or not (False).
    """
    args = init_args.copy()
    args["bidding_zones"] = [bz]

    if not valid:
        with pytest.raises(ValueError, match="not supported"):
            EntsoeDownloader(**args)
    else:
        downloader = EntsoeDownloader(**args)

        assert downloader.bidding_zones == args["bidding_zones"]
        assert downloader.years == args["years"]
        assert downloader.output_path == args["output_path"]


def test_download_data_resume(api_config: Generator, init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    Args:
        api_config (Generator): Fixture that patches the ENTSO-E global configuration.
        init_args (dict): Arguments used to initialise an EntsoeDownloader instance.
    """
    args = init_args.copy()

    # save a fake checkpoint file
    bz = args["bidding_zones"][0]
    y = args["years"][0]
    checkpoint = {
        (bz, d): 1
        for d in pd.date_range(start=f"{y}-01-01", end=f"{y}-12-31")
        .strftime("%Y-%m-%d")
        .tolist()
    }

    bz_path = Path(args["output_path"], bz)
    bz_path.mkdir(parents=True, exist_ok=True)
    checkpoint_path = Path(bz_path, "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    args["resume"] = True
    downloader = EntsoeDownloader(**args)

    with patch.object(downloader, "_download_task_data") as mock_dump:
        downloader.download_data()

        assert mock_dump.call_count == 0


# ----------------------------------
# Tests - Parallelisation
# ----------------------------------
def test_threading_wrapper_missing_data(
    downloader: EntsoeDownloader, download_args: tuple
) -> None:
    """Happy path for "_threading_wrapper" function when no data is available.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, checkpoint, checkpoint_path = download_args

    with patch.object(downloader, "_get_task_data", side_effect=ValueError):
        with patch.object(downloader, "_save_checkpoint") as mock_save:
            downloader._threading_wrapper(task, checkpoint, checkpoint_path)

            assert checkpoint[task] == 1
            mock_save.assert_called_once_with(checkpoint, checkpoint_path)


def test_threading_wrapper_service_unavailable(
    downloader: EntsoeDownloader, download_args: tuple
) -> None:
    """Failure path for "_threading_wrapper" function when connection error occurs.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, checkpoint, checkpoint_path = download_args

    with patch.object(downloader, "_get_task_data", side_effect=ConnectionError):
        with patch("rbc.energy.utils.time.sleep"):
            with patch.object(downloader, "_save_checkpoint"):
                downloader._threading_wrapper(task, checkpoint, checkpoint_path)

                assert checkpoint[task] == 0


def test_threading_wrapper_structure_changed(
    downloader: EntsoeDownloader, download_args: tuple
) -> None:
    """Failure path for "_threading_wrapper" function when data structure changed.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, checkpoint, checkpoint_path = download_args

    with patch("os._exit", side_effect=SystemExit("Process killed")) as mock_exit:
        with patch.object(downloader, "_get_task_data", side_effect=DataStructureError):
            with pytest.raises(SystemExit, match="Process killed"):
                downloader._threading_wrapper(task, checkpoint, checkpoint_path)

    mock_exit.assert_called_once_with(1)
    assert task not in checkpoint


def test_download_day_data(downloader: EntsoeDownloader, download_args: tuple) -> None:
    """Happy path for "_download_task_data" method when resuming from checkpoint.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, checkpoint, checkpoint_path = download_args
    mock_df = pd.DataFrame({"Generation_MW": [16.2]})

    with patch.object(downloader, "_get_task_data", return_value=mock_df):
        status = downloader._download_task_data(task)

        assert status == 1
        expected_file = Path(downloader.output_path, task[0], task[1] + ".csv")
        assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

        saved_df = pd.read_csv(expected_file)
        assert saved_df.iloc[0]["Generation_MW"] == 16.2


# ----------------------------------
# Tests - Data crawling logic
# ----------------------------------
def test_get_task_data(downloader: EntsoeDownloader, download_args: tuple) -> None:
    """Happy path for "_get_task_data" method.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, checkpoint, checkpoint_path = download_args
    timestamp = f"{task[1]}T00:00:00+00:00"
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


def test_get_task_data_timed_service_unavailable(
    downloader: EntsoeDownloader, download_args: tuple
) -> None:
    """Failure path for "_get_task_data" method when the service is unavailable.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, _, _ = download_args

    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.return_value.query_api.side_effect = ServiceUnavailableError

        with pytest.raises(ConnectionError, match="unavailable"):
            downloader._get_task_data(task)


def test_get_task_data_requested_data_not_returned(
    downloader: EntsoeDownloader, download_args: tuple
) -> None:
    """Failure path for "_get_task_data" method when the requested data is not returned.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, _, _ = download_args

    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.query_api.return_value = "not a list"

        with pytest.raises(ConnectionError, match="did not return requested"):
            downloader._get_task_data(task)


def test_get_task_data_no_data_available(
    downloader: EntsoeDownloader, download_args: tuple
) -> None:
    """Failure path for "_get_task_data" method when the requested data is empty.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, _, _ = download_args

    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.return_value.query_api.return_value = []

        with pytest.raises(ValueError, match="No data available"):
            downloader._get_task_data(task)


def test_get_task_data_structure_change(
    downloader: EntsoeDownloader, download_args: tuple
) -> None:
    """Failure path for "_get_task_data" method when the expected columns are missing.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
        download_args (tuple): Tuple of download arguments for running _get_task_data.
    """
    task, _, _ = download_args

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
