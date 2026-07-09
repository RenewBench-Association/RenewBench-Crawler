# tests/test_utils.py
import sys
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from rbc.utils import clean_record, handle_exceptions, setup_logging


# ----------------------------------
# Tests
# ----------------------------------
@pytest.mark.parametrize("verbose, level", [[False, "INFO"], [True, "DEBUG"]])
def test_setup_logging(tmp_path: Path, verbose: bool, level: str) -> None:
    """Happy path for "setup_logging" function, ensuring messages are logged to file.

    Args:
        tmp_path (Path): Path to the temporary directory.
        verbose (bool, optional): Whether or not to define a high logging verbosity level.
        level (str): The resulting logging level.
    """
    logger.remove()
    setup_logging(tmp_path, verbose=verbose)

    log_dir = Path(tmp_path, "logs")
    assert log_dir.exists()

    log_files = list(log_dir.rglob("*.log"))
    assert len(log_files) == 1

    log_file = log_files[0]
    content = log_file.read_text()

    assert f"Logging initialized with level {level}." in content
    assert "Log file writing to:" in content
    assert str(log_file.name) in content


def test_handle_exceptions(tmp_path: Path):
    """Happy path for handle_exceptions function, ensuring traceback is logged to file.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    logger.remove()
    setup_logging(tmp_path)

    try:
        raise ValueError("Simulated Task Failure")
    except ValueError:
        exc_info = sys.exc_info()  # get exception info (type, value, traceback)
        handle_exceptions(*exc_info)  # manually trigger the handler

    log_dir = Path(tmp_path, "logs")
    log_file = list(log_dir.glob("*.log"))[0]
    log_content = log_file.read_text()

    assert "Error occurred that killed the run:" in log_content
    assert "ValueError: Simulated Task Failure" in log_content
    assert "test_handle_exceptions" in log_content


def test_handle_exceptions_do_nothing_when_keyboardinterrupt(tmp_path: Path):
    """Happy path for handle_exceptions function when the error is a KeyboardInterrupt.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    logger.remove()
    setup_logging(tmp_path)

    try:
        raise KeyboardInterrupt("Simulated CTRL+C")
    except KeyboardInterrupt:
        exc_info = sys.exc_info()  # get exception info (type, value, traceback)
        handle_exceptions(*exc_info)  # manually trigger the handler

    log_dir = Path(tmp_path, "logs")
    log_file = list(log_dir.glob("*.log"))[0]
    log_content = log_file.read_text()

    assert "Error occurred that killed the run:" not in log_content
    assert "Simulated CTRL+C" not in log_content


@pytest.mark.parametrize(
    "message",
    [
        "token=SECRET_T",
        "password='SECRET_P'",
        "token: SECRET_T",
        "password: SECRET_P",
        "{'token': 'SECRET_T', 'username': 'USER', 'password': 'SECRET_P'}",
        "access.token=SECRET_T",
        "access.password=SECRET_P",
        "AccessAccount(username='USER', password='SECRET_P')",
    ],
)
def test_clean_record(message: str) -> None:
    """Happy path for "clean_record" function, ensuring sensitive data is masked.

    Args:
        message (str): Message to be logged containing sensitive data.
    """
    record: dict[str, Any] = {"message": message}

    clean_record(record)

    if "SECRET" in message:
        assert "SECRET_T" not in record["message"]
        assert "SECRET_P" not in record["message"]
        assert "******" in record["message"]
    if "USER" in message:
        assert "USER" in record["message"]
