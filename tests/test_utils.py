# tests/test_utils.py
from pathlib import Path

from loguru import logger

from rbc.utils import setup_logging


# ----------------------------------
# Tests
# ----------------------------------
def test_setup_logging(tmp_path: Path) -> None:
    """Happy path for "setup_logging" function.

    Args:
        tmp_path (Path): Path to the temporary directory.
    """
    logs = []
    sink = logger.add(lambda msg: logs.append(msg.record["message"]), level="INFO")

    try:
        setup_logging(tmp_path)
        assert any("Log file initialized." in msg for msg in logs)

        log_dir = Path(tmp_path, "logs")
        assert log_dir.exists()

        generated_files = list(log_dir.rglob("*.log"))
        assert len(generated_files) == 1

    finally:
        logger.remove(sink)
