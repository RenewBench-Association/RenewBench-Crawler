"""UTILS.

Shared helper functions for data downloaders
"""

import os
import pickle
import re
import threading
import time
import urllib
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
import requests
import urllib3
from loguru import logger

WORKERS = 4
MAX_RETRIES = 3
RETRY_DELAY = 5
MAX_RATE_LIMIT_RETRIES = 6

RETRY_ERRORS = (
    # requests / urllib3 (used by requests.get/head)
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.HTTPError,
    urllib3.exceptions.TimeoutError,
    urllib3.exceptions.ReadTimeoutError,
    urllib3.exceptions.ConnectTimeoutError,
    urllib3.exceptions.HTTPError,
    # urllib (standard - used by pandas)
    urllib.error.HTTPError,
    urllib.error.URLError,
    # low-level errors (caught by both)
    ConnectionError,
    TimeoutError,
)


class MissingDataError(Exception):
    """Raised when a data source is missing data that a task is trying to download."""

    pass


class DataStructureError(Exception):
    """Raised when a data source changes its structure significantly."""

    pass


class RateLimitError(Exception):
    """Raised when the API rate limit has been reached and downloading must be stopped."""

    pass


class InvalidError(Exception):
    """Raised when provided values/arguments are invalid in some way that force a stop."""

    pass


@dataclass(frozen=True)
class DownloadTask:
    """Dataclass for defining downloading metadata for a task.

    This defines a task's relevant attributes, which in turn is used to build a consistent
    path structure:
    raw/energy/<source>/<resolution>/<optional ...>/<optional bidding_zone>/<date>.csv

    Attributes:
        date (str | None): Date in the format YYYY-MM(-DD) to download data for.
        temporal_resolution (str): Temporal resolution of data. Defaults to "1h".
        bidding_zone (str | None): Optional bidding zone of data. Defaults to None.
    """

    date: str
    temporal_resolution: str = "1h"
    bidding_zone: str | None = None

    # patterns for matching
    _DATE_PATTERN = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
    _TRES_PATTERN = re.compile(r"^\d+(?:h|min|d)$")

    def __post_init__(self) -> None:
        """Validates the date and temporal resolution formats.

        Raises:
            ValueError: If provided date or temporal resolution are in the wrong format.
        """
        if not self._DATE_PATTERN.match(self.date):
            raise ValueError(f"Invalid date / date format: '{self.date}'")

        if not self._TRES_PATTERN.match(self.temporal_resolution):
            raise ValueError(
                f"Invalid temporal resolution: '{self.temporal_resolution}'"
            )

    # Validate that the date is actually a valid calendar date
    try:
        pd.to_datetime(self.date)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid calendar date: '{self.date}'")

    @property
    def identifier(self) -> str:
        """A task's unique string representation for checkpointing and logging.

        Returns:
            str: Unique string 'date=YYYY-MM(-DD)|temporal_resolution=1h(|bidding_zone=<bz>)'
        """
        parts = [
            f"date={self.date}",
            f"temporal_resolution={self.temporal_resolution}",
        ]
        if self.bidding_zone:
            parts.append(f"bidding_zone={self.bidding_zone}")

        return "|".join(parts)

    def update(self, **changes) -> "DownloadTask":
        """Update a key with provided changes.

        Args:
            changes: Dictionary of changes to make to the DownloadKey instance.

        Returns:
            DownloadTask: Updated download task instance.
        """
        return replace(self, **changes)

    def validate_required_fields(self, *fields: str) -> None:
        """Check that specific fields are not None.

        Args:
              fields (str): List of fields to check.

        Raises:
              ValueError: If any of the required fields are None.
        """
        for field in fields:
            value = getattr(self, field)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(
                    f"Required attribute '{field}' missing for task: {self}"
                )


class EnergyDownloader(ABC):
    """Abstract base class for parallelized daily energy downloader classes.

    Attributes:
        RETRY_ERRORS (tuple): Tuple of exceptions that may be raised when retrying calls.
        output_path (Path): Path to the output directory.
        years (list[int]): List of years to get data for.
        resume (bool, optional): Whether to resume from a previous download (True) or
            start from scratch (False). Defaults to True.
        _lock (threading.Lock): Threading lock to ensure thread-safe checkpoint updates.
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (dict): Dict of 0 and 1 values for resuming.
    """

    RETRY_ERRORS = RETRY_ERRORS

    def __init__(self, output_path: Path, years: list[int], resume: bool = True):
        """Initializes the instance.

        Args:
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.
        """
        self.output_path = output_path
        self.years = years
        self.resume = resume
        self._lock = threading.Lock()

        self.checkpoint_path = Path(self.output_path, "status.pickle")
        self.checkpoint = self._load_checkpoint()

    def _threading_wrapper(self, task: DownloadTask) -> None:
        """Thread-safe wrapper for one download task (download and checkpoint reading/saving).

        Args:
            task (DownloadTask): The metadata for a task to download data for.
        """
        with self._lock:
            if self.checkpoint.get(task.identifier) == 1:
                logger.info(
                    f"Task '{task.identifier}': Data already downloaded. Skipping."
                )
                return

        try:
            status = self._download_task_data(task=task)
        except Exception as e:
            logger.error(f"Unexpected error in thread for {task.identifier}: {e}")
            status = 0

        with self._lock:
            self.checkpoint[task.identifier] = status
            self._save_checkpoint()

    def _download_task_data(self, task: DownloadTask) -> int:
        """Parse data for a specific task and dump to CSV.

        Child classes must raise / propagate errors the following errors to be handled here:
        - DataStructureError / RateLimitError / InvalidError: to immediately kill a run.
        - MissingDataError: when data is missing for a specific task.
        - self.RETRY_ERRORS: when accessing generally fails.

        Args:
            task (DownloadTask): The metadata for a task to download data for.

        Returns:
            int: Status of the download (1 if successful, 0 if unsuccessful).
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                df_gen = self._get_task_data(task=task)
                self._save_task_data(task=task, df=df_gen)
                return 1

            except (DataStructureError, RateLimitError, InvalidError) as e:  # kill run
                logger.critical(f"FATAL! Stopping run due to error: {e}")
                os._exit(1)

            except MissingDataError as e:  # handle missing data for task
                logger.error(f"Missing data for '{task.identifier}': {e}")

                task.validate_required_fields("date")
                if pd.Timestamp(task.date).year == pd.Timestamp.now().year:
                    return 0  # current year task -> might become available later!

                return 1  # skip task

            except self.RETRY_ERRORS as e:  # handle access failures
                code = self._get_status_code(e)

                if code:
                    # 1. permanent missing data
                    if code == 404:
                        logger.warning(
                            f"Data for '{task.identifier}' not found (404). Skipping."
                        )
                        return 1
                    # 2. permanent client errors (400-499, except rate limits 429)
                    if 400 <= code < 500 and code != 429:
                        logger.error(
                            f"Permanent error {code} for '{task.identifier}'. Skipping."
                        )
                        return 1

                # 3. everything else (500s, Timeouts, 429s) -> Retry
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.critical(
                        f"Failed '{task.identifier}' after {MAX_RETRIES} attempts: {e}"
                    )
                    return 0

        return 1  # pragma: no cover

    @abstractmethod
    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:
        """Method to get the task's data (child classes MUST implement/overwrite this!).

        Args:
            task (DownloadTask): The metadata for a task to download data for.

        Returns:
            DataFrame: The task's downloaded data (child classes MUST implement this!).
        """

    def _save_task_data(self, task: DownloadTask, df: pd.DataFrame) -> None:
        """Save downloaded task data to disk.

        Functionality is separated here to allow child classes to overwrite (i.e. Entso-e).

        Args:
            task (DownloadTask): The metadata for the task that was downloaded.
            df (pd.DataFrame): Downloaded dataframe for the task.
        """
        file_path = self._build_task_path(task)
        write_df_to_csv(df=df, file_path=file_path)

    # ------------------------------------------------------------------
    # Path definition and checkpoint helpers (using DownloadTask)
    # ------------------------------------------------------------------
    def _load_checkpoint(self) -> dict[str, int]:
        """Load checkpoint from checkpoint path depending on resume logic.

        Returns:
            dict: Loaded checkpoint.
        """
        if self.resume and self.checkpoint_path.is_file():
            logger.info(f"Loading checkpoint from '{self.checkpoint_path}'")

            try:
                with open(self.checkpoint_path, "rb") as f:
                    return pickle.load(f)
            except (EOFError, pickle.UnpicklingError):
                logger.warning(
                    f"Checkpoint '{self.checkpoint_path}' is corrupted. Starting fresh."
                )
                return {}
        else:
            logger.info(
                "No checkpoint loading (first run or resume=False). Starting fresh."
            )
            return {}

    def _save_checkpoint(self) -> None:
        """Save checkpoint safely (ensure abrupt terminations don't corrupt the file)."""
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.checkpoint_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            pickle.dump(self.checkpoint, f)
        os.replace(temp_path, self.checkpoint_path)

    def _build_task_path(self, task: DownloadTask) -> Path:
        """Build the CSV file path to which the downloaded task data will be saved.

        Designed structure:
        <output_path>/<temporal_resolution>/<optional ...>/<optional bz>/<date>.csv

        Args:
            task (DownloadTask): The metadata for a task to download data for.

        Returns:
            Path: Path to the csv file.
        """
        parts: list[str | Path] = [self.output_path, task.temporal_resolution]

        if task.bidding_zone:
            parts.append(task.bidding_zone)

        return Path(*parts, f"{task.date}.csv")

    # --------------------------------------------
    # General helper methods
    # --------------------------------------------
    @staticmethod
    def _get_status_code(e: Exception) -> int | None:
        """Extracts HTTP status code from various library exceptions.

        Args:
            e (Exception): Exception raised when an error occurs.

        Returns:
            int | None: HTTP status code if it was a HTTPError, otherwise None.
        """
        if hasattr(e, "response") and hasattr(e.response, "status_code"):  # requests
            return e.response.status_code
        if hasattr(e, "code"):  # urllib
            return e.code
        return None

    def _get_date_list(self) -> list[str]:
        """Get a list of all valid dates in the provided year(s).

        Includes checks to ensure future years are not evaluated and that if the
        current year is provided, nothing beyond the previous day is taken into account.

        Returns:
            list[str]: List of all valid dates, formatted as YYYY-MM-DD.
        """
        yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).normalize()

        all_dates = []
        for year in self.years:
            year_start = pd.Timestamp(f"{year}-01-01")
            year_end = pd.Timestamp(f"{year}-12-31")

            if year_start > yesterday:  # don't evaluate future years
                continue

            actual_end = min(year_end, yesterday)  # don't evaluate beyond yesterday

            all_dates.extend(
                pd.date_range(start=year_start, end=actual_end)
                .strftime("%Y-%m-%d")
                .tolist()
            )

        if not all_dates:
            raise InvalidError(f"Provided years '{self.years}' lie in the future!")

        return all_dates

    def _get_month_list(self) -> list[str]:
        """Get a list of all valid months in the provided year(s).

        Returns:
            list[str]: List of all valid months, formatted as YYYY-MM.
        """
        return list(dict.fromkeys(d[:7] for d in self._get_date_list()))

    def _get_year_list(self) -> list[str]:
        """Get a list of all valid years among the provided year(s).

        Returns:
            list[str]: List of all valid years, formatted as YYYY.
        """
        return list(dict.fromkeys(d[:4] for d in self._get_date_list()))


def write_df_to_csv(df: pd.DataFrame, file_path: Path, index: bool = False) -> None:
    """Write dataframe to csv file.

    Args:
        df (pd.DataFrame): Pandas dataframe to be stored in csv file.
        file_path (Path): Path to the csv file.
        index (bool, optional): Whether to include the df index in the csv (True) or not
            (False). Defaults to False.
    """
    if file_path.suffix != ".csv":
        file_path = file_path.with_suffix(".csv")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(file_path, index=index)
    logger.info(f"Successfully wrote dataframe to '{file_path}'")


def load_df_from_file(file_path: Path | str, **args) -> pd.DataFrame:
    """Load pandas dataframe from a file such as an Excel or csv (file or URL directly).

    Args:
        file_path (Path | str): Path to the Excel file.
        args (optional): Additional arguments to be passed to pandas loading
        function, i.e. sheet_name for an Excel or index_col for a CSV.

    Returns:
        pd.DataFrame: Pandas dataframe extracted from the provided file.

    Raises:
        InvalidError: If the file doesn't have one of the expected suffixes, if the file
            doesn't exist, if invalid arguments (args) were provided for loading with pandas.
        RETRY_ERRORS: If the file is a URL that is inaccessible for some reason.
    """
    try:
        if Path(file_path).suffix == ".xlsx":
            df = pd.read_excel(str(file_path), **args)

        elif Path(file_path).suffix == ".csv":
            df = pd.read_csv(str(file_path), **args)

        else:
            raise InvalidError(
                f"Invalid extension in '{file_path}' - not a csv or xlsx!"
            )

    except FileNotFoundError:
        raise InvalidError(f"Invalid path - file '{file_path}' does not exist!")

    except TypeError as e:
        raise InvalidError(f"Invalid argument for loading from '{file_path}': {e}")

    except RETRY_ERRORS:  # these can occur when the file is a URL!
        raise

    logger.info(f"Successfully loaded dataframe from '{file_path}'")
    return df
