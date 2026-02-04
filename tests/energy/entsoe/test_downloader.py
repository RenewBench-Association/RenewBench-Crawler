# tests/downloaders/test_downloader.py
import pickle
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pandas as pd
import pytest
from entsoe.query.decorators import ServiceUnavailableError

from rbc.energy.entsoe import EntsoeDownloader


# ----------------------------------
# Specific fixtures
# ----------------------------------
@pytest.fixture
def api_config() -> Generator:
    """Fixture that patches the entsoe-apy package configuration."""
    with patch("rbc.energy.entsoe.downloader.set_config"):
        with patch("rbc.energy.entsoe.downloader.get_config") as mock_get:
            mock_get.return_value.security_token = "fake_token"
            yield


@pytest.fixture
def init_args(tmp_path: Path) -> dict:
    """Creates a basic setup with a temporary directory."""
    return {
        "token": "fake_token",
        "output_path": tmp_path,
        "years": [2020],
        "bidding_zones": ["10YES-REE------0"],
        "resume": False,
    }


@pytest.fixture
def downloader(api_config, init_args: dict) -> EntsoeDownloader:
    """Returns an instantiated EntsoeDownloader."""
    dl = EntsoeDownloader(**init_args)
    return dl


# ----------------------------------
# Tests
# ----------------------------------
@pytest.mark.parametrize("bz, valid", [("10YES-REE------0", True), (" ", False)])
def test_downloader_initialization(
    api_config, init_args: dict, bz: str, valid: bool
) -> None:
    """Happy path for class initialization.

    Check that the EntsoeDownloader sets up paths and checkpoint correctly.

    Args:
        api_config: Fixture that patches the ENTSO-E global configuration.
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
        assert downloader.checkpoint_path == Path(args["output_path"], "status.pickle")
        assert downloader.checkpoint == {}


def test_download_data_resume(api_config: Generator, init_args: dict) -> None:
    """Happy path for "download_data" method when resuming from checkpoint.

    Args:
        api_config: Fixture that patches the ENTSO-E global configuration.
        init_args (dict): Arguments used to initialise an EntsoeDownloader instance.
    """
    # save a fake checkpoint file
    checkpoint = {(init_args["years"][0], init_args["bidding_zones"][0]): 0}
    checkpoint_path = Path(init_args["output_path"], "status.pickle")
    with open(checkpoint_path, "wb") as f:
        pickle.dump(checkpoint, f)

    init_args["resume"] = True
    downloader = EntsoeDownloader(**init_args)

    with patch.object(downloader, "_download_year_zone_data") as mock_dump:
        downloader.download_data()

        assert mock_dump.call_count == 0
        assert downloader.checkpoint == checkpoint


def test_download_year_zone_data(downloader: EntsoeDownloader) -> None:
    """Happy path for "_download_year_zone_data" method.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
    """
    zone = downloader.bidding_zones[0]
    year = downloader.years[0]

    # 1. SETUP MOCKS (for the API response)
    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        with patch("rbc.energy.entsoe.downloader.extract_records") as mock_extract:
            mock_api.return_value.query_api.return_value = "mock_result"
            mock_extract.return_value = [
                {
                    "time_series.mkt_psrtype.psr_type": "B01",
                    "time_series.mkt_psrtype.power_system_resources.name": "Test plant",
                    "time_series.period.point.quantity": 100,
                    "time_series.quantity_measure_unit_name": "MW",
                    "timestamp": pd.Timestamp("2020-01-01 12:00:00"),
                }
            ]

            # 2. RUN
            status = downloader._download_year_zone_data(zone, year)

    # 3. ASSERT
    assert status == 1

    expected_file = Path(downloader.output_path, zone, f"{year}.csv")
    assert expected_file.is_file(), f"The CSV {expected_file} was not created!"

    df = pd.read_csv(expected_file)
    assert not df.empty
    assert "production_type" in df.columns
    assert df.iloc[0]["production_type"] == "Biomass"


def test_download_year_zone_data_no_data(downloader: EntsoeDownloader) -> None:
    """Happy path for "_download_year_zone_data" method when no data is available.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
    """
    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.return_value.query_api.return_value = None

        status = downloader._download_year_zone_data(
            downloader.bidding_zones[0], downloader.years[0]
        )

    assert status == 1


def test_download_year_zone_data_service_unavailable(
    downloader: EntsoeDownloader,
) -> None:
    """Failure path for "_download_year_zone_data" method when service is unavailable.

    Args:
        downloader (EntsoeDownloader): Instance of EntsoeDownloader class.
    """
    with patch(
        "rbc.energy.entsoe.downloader.ActualGenerationPerGenerationUnit"
    ) as mock_api:
        mock_api.return_value.query_api.side_effect = ServiceUnavailableError

        with pytest.raises(ValueError, match="unavailable"):
            downloader._download_year_zone_data(
                downloader.bidding_zones[0], downloader.years[0]
            )
