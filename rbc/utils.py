"""UTILS.

Shared helper functions for rbc package
"""

import sys
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Type

from loguru import logger


def handle_exceptions(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    """Global exception handler to propagate errors to the log file.

    Args:
        exc_type (Type[BaseException]): The class of the exception.
        exc_value (BaseException): The actual exception instance.
        exc_traceback (TracebackType | None): The traceback object containing
            the call stack.
    """
    if issubclass(exc_type, KeyboardInterrupt):  # don't log CTRL+C
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.opt(exception=(exc_type, exc_value, exc_traceback)).error(
        "Error occurred that killed the run:"
    )


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

    # add file logging
    logger.add(
        log_path,
        retention="30 days" if retention else None,  # delete files older than 30 days
        compression="zip" if compression else None,  # compress logs to zip
        level="INFO",
    )
    # register the global exception hook
    sys.excepthook = handle_exceptions

    logger.info(f"Log file initialized. Writing to: {log_path}")
