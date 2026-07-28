# tests/coordinates/test_orchestrator.py
"""Tests for the coordinate/location finding orchestration functions."""

from pathlib import Path
from unittest.mock import patch

from loguru import logger

from rbc.coordinates.orchestrator import _collect_dirs


# ----------------------------------
# Tests
# ----------------------------------
def test_collect_dirs_filters_correct_files(tmp_path: Path) -> None:
    """Happy path for 'collect_dirs' function, ensuring correct filtering of files.

    Args:
        tmp_path (Path): Path object to be used as a temporary directory.
    """
    # valid path
    tres_dir = Path(tmp_path, "1h")  # correct tres
    tres_dir.mkdir()
    valid_csv = Path(tres_dir, "2023-01-01.csv")  # correct date
    valid_csv.write_text("data")

    # invalid path
    invalid_csv = Path(tres_dir, "invalid_name.csv")
    invalid_csv.write_text("data")

    with (
        patch("rbc.coordinates.orchestrator.DATE_PATTERN") as mock_date,
        patch("rbc.coordinates.orchestrator.TRES_PATTERN") as mock_tres,
    ):
        mock_date.match.side_effect = lambda stem: stem == "2023-01-01"
        mock_tres.match.side_effect = lambda part: part == "1h"

        result = _collect_dirs([tmp_path])

        assert result == [tres_dir.resolve()]


def test_collect_dirs_handles_invalid_paths() -> None:
    """Failure path for 'collect_dirs' function when CSV path does not exist."""
    captured_logs = []
    sink_id = logger.add(lambda msg: captured_logs.append(msg.record), level="WARNING")

    try:
        non_existent_path = Path("/path/does/not/exist")
        result = _collect_dirs([non_existent_path])

        assert result == []
        assert len(captured_logs) == 1
        assert "is not a directory" in captured_logs[0]["message"]
    finally:
        logger.remove(sink_id)
