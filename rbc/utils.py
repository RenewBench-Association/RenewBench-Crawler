"""UTILS.

Shared helper functions for rbc package
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Type

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


def clean_record(record: dict[str, Any]) -> None:
    """Masks sensitive keys in the log record's message body using regex.

    Args:
        record (dict): The log record with 'message' body containing sensitive values to mask.
    """
    sensitive_keys = ("token", "password", "secret", "key")
    pattern = rf"(['\"]?(?:{'|'.join(sensitive_keys)})['\"]?\s*[:=]\s*)['\"]?([^'\"\s,\n\)}}]+)['\"]?"

    # find and replace all parts of the log message that match the pattern
    record["message"] = re.sub(
        pattern=pattern,
        repl=lambda m: f"{m.group(1)}'******'",
        string=record["message"],
        flags=re.IGNORECASE,  # ignore case
    )


def setup_logging(
    output_dir: Path,
    verbose: bool = False,
    retention: bool = False,
    compression: bool = False,
) -> None:
    """Configures Loguru to output to both console and a timestamped file.

    Args:
        output_dir (Path): Directory where the script outputs will be saved.
        verbose (bool): Whether to include DEBUG logging messages in file. Defaults to False.
        retention (bool): Whether to delete log files older than 30 days. Defaults to False.
        compression (bool): Whether to compress log files. Defaults to False.
    """
    log_level = "DEBUG" if verbose else "INFO"

    # define the file logging sink
    log_dir = Path(output_dir, "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir, f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log")

    # configure logger to have both a console sink and file logging sink
    logger.configure(
        patcher=clean_record,  # automatically scrub sensitive data from message
        handlers=[
            {"sink": sys.stderr, "level": log_level, "diagnose": False},
            {
                "sink": log_path,
                "level": log_level,
                "retention": "30 days" if retention else None,  # delete files >30 days
                "compression": "zip" if compression else None,  # compress logs to zip
                "diagnose": False,
            },
        ],
    )

    # register the global exception hook
    sys.excepthook = handle_exceptions

    logger.info(f"Logging initialized with level {log_level}.")
    logger.info(f"Log file writing to: {log_path}")
