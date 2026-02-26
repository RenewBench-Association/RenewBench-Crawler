"""UTILS.

Shared helper functions for rbc package
"""

from datetime import datetime
from pathlib import Path

from loguru import logger


def setup_logging(
    output_dir: Path,
    retention: bool = False,
    compression: bool = False,
) -> None:
    """Configures Loguru to output to both console and a timestamped file.

    Args:
        output_dir (Path): Directory where the script outputs will be saved.
        retention (bool): Whether to delete log files older than 30 days. Defaults to False.
        compression (bool): Whether to compress log files. Defaults to False.
    """
    log_dir = Path(output_dir, "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir, f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log")
    logger.add(
        log_path,
        retention="30 days" if retention else None,  # delete files older than 30 days
        compression="zip" if compression else None,  # compress logs to zip
        level="INFO",
    )
    logger.info(f"Log file initialized. Writing to: {log_path}")
