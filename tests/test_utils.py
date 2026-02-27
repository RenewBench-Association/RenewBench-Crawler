# tests/test_utils.py
import sys
from pathlib import Path

from loguru import logger

from rbc.utils import handle_exceptions, setup_logging


# ----------------------------------
# Tests
# ----------------------------------
def test_setup_logging(tmp_path: Path) -> None:
    """Happy path for "setup_logging" function, ensuring messages are logged to file.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    logger.remove()
    logs = []
    sink = logger.add(lambda msg: logs.append(msg.record["message"]), level="INFO")

    try:
        setup_logging(tmp_path)
        assert any("Log file initialized." in msg for msg in logs)

        log_dir = Path(tmp_path, "logs")
        assert log_dir.exists()

        log_files = list(log_dir.rglob("*.log"))
        assert len(log_files) == 1

    finally:
        logger.remove(sink)


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
