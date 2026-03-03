"""UTILS.

Shared helper functions for data downloaders
"""

import os
import pickle
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import requests
import urllib3
from loguru import logger

WORKERS = 4
MAX_RETRIES = 3
RETRY_DELAY = 5
MAX_RATE_LIMIT_RETRIES = 6


class DataStructureError(Exception):
    """Raised when a data source changes its structure significantly."""

    pass


class RateLimitError(Exception):
    """Raised when the API rate limit has been reached and downloading must be stopped."""

    pass


class InvalidError(Exception):
    """Raised when provided values/arguments are invalid in some way that force a stop."""

    pass


class DailyDownloader(ABC):
    """Abstract base class for parallelized daily energy downloader classes.

    Attributes:
        output_path (Path): Path to the output directory.
        years (list[int]): List of years to get data for.
        resume (bool, optional): Whether to resume from a previous download (True) or
        start from scratch (False). Defaults to True.
        _lock (threading.Lock): Threading lock to ensure thread-safe checkpoint updates.
        RETRY_ERRORS (tuple): Tuple of exceptions that may be raised when retrying calls.
    """

    RETRY_ERRORS = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
        urllib3.exceptions.TimeoutError,
        urllib3.exceptions.ReadTimeoutError,
        urllib3.exceptions.ConnectTimeoutError,
        ConnectionError,
        TimeoutError,
    )

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

    def _threading_wrapper(
        self, task: str | tuple[str, str], checkpoint: dict, checkpoint_path: Path
    ) -> None:
        """Threading wrapper for data download and checkpoint reading/saving.

        Args:
            task (str | tuple): Date or (zone, date) to download data for.
            checkpoint (dict): Dict of 0 and 1 values for resuming.
            checkpoint_path (Path): Path to the checkpoint file for resuming.
        """
        with self._lock:
            if checkpoint.get(task) == 1:
                logger.info(f"{task}: Data already downloaded. Skipping.")
                return

        try:
            status = self._download_task_data(task=task)
        except Exception as e:
            logger.error(f"Unexpected error in thread for {task}: {e}")
            status = 0

        with self._lock:
            checkpoint[task] = status
            self._save_checkpoint(checkpoint, checkpoint_path)

    def _download_task_data(self, task: str | tuple[str, str]) -> int:
        """Parse data for a specific task and dump to CSV.

        Args:
            task (str | tuple): Date or (zone, date) to download data for.

        Returns:
            int: Status of the download (1 if successful, 0 if unsuccessful).
        """
        file_path = self._get_csv_path(task)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                df_gen = self._get_task_data(task=task)
                write_df_to_csv(df=df_gen, file_path=file_path)
                return 1

            # errors that warrant immediate run kill
            except (DataStructureError, RateLimitError, InvalidError) as e:
                logger.critical(f"FATAL! Stopping run due to error: {e}")
                os._exit(1)

            except ValueError as e:
                logger.error(f"Missing data for {task}: {e}")
                return 1  # skip task

            except self.RETRY_ERRORS as e:
                code = self._get_status_code(e)

                if code:
                    # 1. permanent missing data
                    if code == 404:
                        logger.warning(
                            f"Data for task {task} not found (404). Skipping."
                        )
                        return 1
                    # 2. permanent client errors (400-499, except rate limits 429)
                    if 400 <= code < 500 and code != 429:
                        logger.error(f"Permanent error {code} for {task}. Skipping.")
                        return 1

                # 3. everything else (500s, Timeouts, 429s) -> Retry
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.critical(f"Failed {task} after {MAX_RETRIES} attempts: {e}")
                    return 0

        return 1  # pragma: no cover

    @abstractmethod
    def _get_task_data(self, task: str | tuple[str, str]) -> pd.DataFrame:
        """Method to get the task's data (child classes MUST implement/overwrite this!).

        Args:
            task (str | tuple): Date or (zone, date) to download data for.
        """

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    @staticmethod
    def _get_status_code(e: Exception) -> int | None:
        """Extracts HTTP status code from various library exceptions.

        Args:
            e (Exception): Exception raised when an error occurs.

        Returns:
            int | None: HTTP status code if it was a HTTPError, otherwise None.
        """
        if hasattr(e, "response") and hasattr(
            e.response, "status_code"
        ):  # for requests
            return e.response.status_code
        if hasattr(e, "code"):  # for urllib
            return e.code
        return None

    def _get_csv_path(self, task: str | tuple[str, str]) -> Path:
        """Get csv file path to which resume logic will be saved.

        Args:
            task (str | tuple): Date or (zone, date) to download data for.

        Returns:
            Path: Path to the csv file.

        Raises:
            ValueError: If task is not a string or tuple.
        """
        if isinstance(task, str):  # Case for EIA / EPIAS
            return Path(self.output_path, f"{task}.csv")

        if isinstance(task, tuple) and len(task) == 2:  # Case for Entsoe (zone, date)
            zone, date = task
            return Path(self.output_path, zone, f"{date}.csv")

        raise ValueError(f"CSV path can't be defined. Unsupported task format: {task}")

    def _load_checkpoint(self, checkpoint_path: Path) -> dict:
        """Load checkpoint from checkpoint path depending on resume logic.

        Args:
            checkpoint_path (Path): Path to checkpoint file.

        Returns:
            dict: Loaded checkpoint.
        """
        if self.resume and checkpoint_path.is_file():
            logger.info(f"Loading checkpoint from '{checkpoint_path}'")

            try:
                with open(checkpoint_path, "rb") as f:
                    return pickle.load(f)
            except (EOFError, pickle.UnpicklingError):
                logger.warning(
                    f"Checkpoint '{checkpoint_path}' is corrupted. Starting fresh."
                )
                return {}
        else:
            logger.info(
                "No checkpoint loading (first run or resume=False). Starting fresh."
            )
            return {}

    @staticmethod
    def _save_checkpoint(checkpoint: dict, checkpoint_path: Path) -> None:
        """Save checkpoint safely (ensure abrupt terminations don't corrupt the file).

        Args:
            checkpoint (dict): Checkpoint to be saved.
            checkpoint_path (Path): Path to checkpoint file.
        """
        temp_path = checkpoint_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            pickle.dump(checkpoint, f)
        os.replace(temp_path, checkpoint_path)

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
            raise ValueError(f"Provided years '{self.years}' lie in the future!")

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
        index (bool, optional): Whether to include the df index in the
            csv (True) or not (False). Defaults to False.
    """
    if file_path.suffix != ".csv":
        file_path = file_path.with_suffix(".csv")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(file_path, index=index)
    logger.info(f"Successfully wrote dataframe to '{file_path}'")


def load_df_from_file(file_path: Path | str, **args) -> pd.DataFrame:
    """Load pandas dataframe from a file such as an Excel or csv file.

    Args:
        file_path (Path | str): Path to the Excel file.
        args (optional): Additional arguments to be passed to pandas loading
        function, i.e. sheet_name for an Excel or index_col for a CSV.

    Returns:
        pd.DataFrame: Pandas dataframe extracted from the provided file.

    Raises:
        InvalidError: If the file doesn't have one of the expected suffixes, if the file
        doesn't exist, if invalid arguments (args) were provided for loading with pandas.
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
        raise InvalidError(f"File '{file_path}' does not exist!")

    except TypeError as e:
        raise InvalidError(f"Invalid argument for loading from '{file_path}': {e}")

    logger.info(f"Successfully loaded dataframe from '{file_path}'")
    return df
