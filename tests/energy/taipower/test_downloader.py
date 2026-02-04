# tests/energy/taipower/test_downloader.py
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from rbc.energy.taipower.downloader import download_realtime_data


# ----------------------------------
# Specific fixtures
# ----------------------------------
@pytest.fixture
def mock_response() -> MagicMock:
    """Mock requests response object.

    Returns:
        MagicMock: Fixture that mocks a successful requests response.
    """
    mock = MagicMock()
    mock.status_code = 200
    return mock


# ----------------------------------
# Tests
# ----------------------------------
def test_download_realtime_data(mock_response: MagicMock, tmp_path: Path) -> None:
    """Happy path for "download_realtime_data" function.

    Args:
        mock_response (MagicMock): Fixture to mock requests response.
        tmp_path (Path): Path to temporary directory.
    """
    correct_json_data = {
        "": "2026-01-29 21:00",
        "dataset": [
            [
                "<A NAME='coal'></A><b>COAL</b>",
                "",
                "Linkou#1",
                "800.0",
                "755.4",
                "94.425%",
                " ",
                "",
            ]
        ],
    }
    mock_response.json.return_value = correct_json_data

    with patch("rbc.energy.taipower.downloader.Session.get") as mock_get:
        mock_get.return_value = mock_response
        with pytest.raises(SystemExit) as exc_info:
            download_realtime_data(tmp_path)

        assert exc_info.value.code == 0

    generated_files = list(tmp_path.glob("*.csv"))
    assert len(generated_files) == 1

    df = pd.read_csv(generated_files[0])
    assert "fueltype" in df.columns
    assert df["fueltype"].iloc[0] == "COAL"
    assert df["output"].iloc[0] == 755.4


def test_download_realtime_data_site_unavailable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Failure path for "download_realtime_data" function when site is unavailable.

    Args:
        tmp_path (Path): Path to temporary directory.
        capsys (pytest.CaptureFixture): Fixture to capture printed messages.
    """
    mock_response = MagicMock()
    mock_response.status_code = 400

    with patch("rbc.energy.taipower.downloader.Session.get") as mock_get:
        mock_get.return_value = mock_response
        with pytest.raises(SystemExit) as exc_info:
            download_realtime_data(tmp_path)

        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Request query failed with status code 400" in captured.out


def test_download_realtime_data_change_in_column_amount(
    mock_response: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Handling of column amount changes in "download_realtime_data" function.

    Ensures that failure message is printed but data is still saved when the number
    of columns differs from what is expected, f.e. one has been removed or added.

    Args:
        mock_response (MagicMock): Fixture to mock requests response.
        tmp_path (Path): Path to temporary directory.
        capsys (pytest.CaptureFixture): Fixture to capture printed messages.
    """
    erroneous_json_data = {
        "": "2026-01-29 21:00",
        "dataset": [
            [
                "<A NAME='coal'></A><b>COAL</b>",
                "",
                "Linkou#1",
                "800.0",
                "755.4",
                "94.425%",
                " ",
            ]
        ],
    }
    mock_response.json.return_value = erroneous_json_data

    with patch("rbc.energy.taipower.downloader.Session.get") as mock_get:
        mock_get.return_value = mock_response
        with pytest.raises(SystemExit) as exc_info:
            download_realtime_data(tmp_path)

        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "Number of data columns has changed" in captured.out

    generated_files = list(tmp_path.glob("*.csv"))
    assert len(generated_files) == 1


def test_download_realtime_data_change_in_numeric_columns(
    mock_response: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Handling of numeric columns' changes in "download_realtime_data" function.

    Ensures that failure message is printed but data is still saved when the 4th and
    5th columns (capacity and generation) do not contain numerical data anymore,
    f.e. when columns have been reordered.

    Args:
        mock_response (MagicMock): Fixture to mock requests response.
        tmp_path (Path): Path to temporary directory.
        capsys (pytest.CaptureFixture): Fixture to capture printed messages.
    """
    erroneous_json_data = {
        "": "2026-01-29 21:00",
        "dataset": [
            [
                "<A NAME='coal'></A><b>COAL</b>",
                "",
                "Linkou#1",
                "",
                "",
                "94.425%",
                "800.0",
                "755.4",
            ]
        ],
    }
    mock_response.json.return_value = erroneous_json_data

    with patch("rbc.energy.taipower.downloader.Session.get") as mock_get:
        mock_get.return_value = mock_response
        with pytest.raises(SystemExit) as exc_info:
            download_realtime_data(tmp_path)

        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "Production data is entirely NaN" in captured.out

    generated_files = list(tmp_path.glob("*.csv"))
    assert len(generated_files) == 1
