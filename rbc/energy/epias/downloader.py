"""EPIAS DATA DOWNLOADER.

Remote API access of EPIAS Platform using the eptr2 package.
"""

import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from eptr2 import EPTR2
from loguru import logger
from urllib3.exceptions import ReadTimeoutError

from rbc.energy.utils import write_df_to_csv

WORKERS = 4
MAX_RETRIES = 3
RETRY_DELAY = 5


class EpiasDownloader:
    """EPIAS data downloader.

    Attributes:
        years (list[str]): List of years to get data for.
        output_path (Path): Path to the output directory.
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (np.array): Array of 0 and 1 values for resuming.
        eptr (EPTR2): EPTR2 object for EPIAS data access.
        _lock (threading.Lock): Parallelisation lock for thread-safety.
    """

    def __init__(
        self,
        username: str,
        password: str,
        output_path: Path,
        years: list[int],
        resume: bool = True,
    ):
        """Initializes the instance.

        Args:
            username (str): The personal EPIAS Transparency Platform username.
            password (str): The personal EPIAS Transparency Platform password.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
            or start from scratch (False). Defaults to True.

        Raises:
            ValueError: If login credentials are incorrect.
        """
        self.years = years
        self.output_path = output_path
        self.checkpoint_path = Path(self.output_path, "status.pickle")
        self._lock = threading.Lock()

        logger.info(f"EPIAS Downloader initialised for:\n- years:\t\t{years}")

        try:
            self.eptr = EPTR2(username=username, password=password)
        except Exception:
            raise ValueError("Provided username and password are incorrect.")

        if resume and self.checkpoint_path.is_file():
            with open(self.checkpoint_path, "rb") as f:
                self.checkpoint = pickle.load(f)
        else:
            self.checkpoint = {}

    def download_data(self):
        """Parse data for all given years from EPIAS Platform and save to CSV."""
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

        try:
            logger.info(f"Downloading data for: {all_dates[0]} to {all_dates[-1]}")
            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                executor.map(self._threading_wrapper, all_dates)

        except IndexError:
            logger.info(f"Provided years '{self.years}' lie in the future!")

    def _threading_wrapper(self, date: str) -> None:
        """Threading wrapper for data download and checkpoint reading/saving.

        Args:
            date (str): Date to download data for.
        """
        with self._lock:
            if self.checkpoint.get(date) == 1:
                logger.info(f"{date}: Data already downloaded.")
                return

        try:
            success_code = self._download_day_data(date=date)
        except Exception as e:
            logger.error(f"Unexpected error in thread for {date}: {e}")
            success_code = 0

        with self._lock:
            self.checkpoint[date] = success_code
            with open(self.checkpoint_path, "wb") as f:
                pickle.dump(self.checkpoint, f)

    def _download_day_data(self, date: str) -> int:
        """Parse data for specific date from EPIAS Platform and dump to CSV.

        Args:
            date (str): Date to download data for.

        Returns:
            int: Status of the download (1 if successful, 0 if unsuccessful).
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                df_gen = self._get_day_data(date=date)
                write_df_to_csv(
                    df=df_gen,
                    file_path=Path(self.output_path, date + ".csv"),
                    index=True,
                )
                return 1

            except ValueError as e:
                logger.error(f"Missing data for {date}: {e}")
                return 1  # Skip day

            except (ReadTimeoutError, ConnectionError):
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.critical(f"Failed {date} after {MAX_RETRIES} attempts.")
                    return 0
        return 1

    def _get_day_data(self, date: str) -> pd.DataFrame:
        """Get EPIAS generation data per plant for one specific date.

        Args:
            date (str): Date to get data for.

        Returns:
            pd.DataFrame: Dataframe for specific date.
        """
        # get power-plants   # ['id', 'name', 'eic', 'shortName']
        end = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df_pp = self.eptr.call("pp-list-for-date-range", start_date=date, end_date=end)
        if df_pp.empty:
            raise ValueError(f"No power plant data available for {date}!")

        # get generation data in batches
        num_batches = len(df_pp) // 1000 + 1  # max allowed batch size = 1000
        batches = np.array_split(df_pp["id"].values, num_batches)

        gen_data = [
            self.eptr.call("rt-gen-bulk", date=date, pp_ids=b.tolist()) for b in batches
        ]

        df_gen = pd.concat(gen_data)
        if df_gen.empty:
            raise ValueError(f"No generation data available for {date}!")

        return df_gen
