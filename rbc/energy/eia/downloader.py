"""EIA DATA DOWNLOADER.

Remote API access of EIA website using the requests package.
"""

import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from loguru import logger
from requests import HTTPError

from rbc.energy.utils import write_df_to_csv

WORKERS = 4
MAX_RETRIES = 3
RETRY_DELAY = 5

URL_ROOT = "https://api.eia.gov/v2/"
URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"


class EiaDownloader:
    """EIA data downloader.

    Attributes:
        token (str): The personal EIA API token.
        years (list[str]): List of years to get data for.
        output_path (Path): Path to the output directory.
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (np.array): Array of 0 and 1 values for resuming.
    """

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Attributes:
            token (str): The personal EIA API token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
            or start from scratch (False). Defaults to True.

        Raises:
            ValueError: If token is invalid or basic API call fails.
        """
        self.token = token
        self.years = years
        self.output_path = output_path
        self.checkpoint_path = Path(self.output_path, "status.pickle")
        self._lock = threading.Lock()

        logger.info(f"EIA Downloader initialised for:\n- years:\t\t{years}")

        try:
            response = requests.get(URL_ROOT, params={"api_key": self.token})
            if response.status_code != 200:
                logger.info(f"Failed: {response.json().get('error', {}).get('code')}")
                raise ValueError(f"Provided API token {token} incorrect.")

        except Exception as e:
            logger.info(f"Failed: {e}")
            raise ValueError(f"Provided API token {token} incorrect.")

        if resume and self.checkpoint_path.is_file():
            with open(self.checkpoint_path, "rb") as f:
                self.checkpoint = pickle.load(f)
        else:
            self.checkpoint = {}

    def download_data(self):
        """Parse data for all given years from EIA site and save to CSV."""
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
                logger.info(f"{date}: Data already downloaded. Skipping.")
                return

        try:
            status = self._download_day_data(date=date)
        except Exception as e:
            logger.error(f"Unexpected error in thread for {date}: {e}")
            status = 0

        with self._lock:
            self.checkpoint[date] = status
            with open(self.checkpoint_path, "wb") as f:
                pickle.dump(self.checkpoint, f)

    def _download_day_data(self, date: str) -> int:
        """Parse data for specific date from EIA Platform and dump to CSV.

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

            except (ConnectionError, HTTPError) as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.critical(f"Failed {date} after {MAX_RETRIES} attempts: {e}")
                    return 0
        return 1

    def _get_day_data(self, date: str) -> pd.DataFrame:
        """Get EIA generation data per plant for one specific date.

        The parsing cap lies at 5000 rows per API call. The amount of hourly data
        per generation company for a single day - without filtering - exceeds that
        (~9000 rows/day), which is why the data is acquired in batches. Given the
        large amount of data, the choice is made here to store a file per day
        instead of per month/year.

        Args:
            date (str): Date to get data for.

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns
            ['period', 'respondent', 'respondent-name', 'fueltype', 'type-name',
            'value', 'value-units']

        Raises:
            ConnectionError: If request timed out.
            HTTPError: If request response is not 200.
            ValueError: If response parsing failed, if not all available data was
            downloaded, or if the dataframe is empty.
        """
        dt = pd.Period(date, freq="D")
        start = dt.strftime("%Y-%m-%dT00")
        end = pd.Period((dt + pd.Timedelta(days=1)), freq="D").strftime("%Y-%m-%dT00")

        params = {
            "api_key": self.token,
            "frequency": "hourly",
            "data[0]": "value",
            "start": start,
            "end": end,
            "offset": 0,
            "length": 5000,  # This is the maximum possible to get at one time!
        }

        all_data = []
        total_available = None
        limit = 5000

        while True:
            try:
                response = requests.get(URL, params=params, timeout=30)
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                raise ConnectionError(f"API request timed out: {e}")

            if response.status_code != 200:
                if response.status_code == 429:
                    logger.warning("Rate limit reached. Sleeping...")
                    time.sleep(10)
                    continue

                raise HTTPError(
                    f"API request failed: {response.status_code} - {response.text}"
                )

            try:
                dict_output = response.json()
                dict_body = dict_output["response"]

                if total_available is None:
                    total_available = int(dict_body["total"])  # total amount for date

                dict_data = dict_body["data"]
                all_data.extend(dict_data)

            except (requests.exceptions.JSONDecodeError, KeyError, ValueError) as e:
                raise ValueError(
                    f"Failed parsing of data from {URL} with parameters {params}: "
                    f"{type(e).__name__}!"
                )

            # Stop if total has been reached
            if len(all_data) >= total_available:
                break

            # Stop if API sent less than the limit (we've reached the end of what's there)
            if len(dict_data) < limit:
                break

            params["offset"] += limit
            time.sleep(0.1)

        # Check all available data was downloaded
        if len(all_data) != total_available:
            raise ValueError(f"Incomplete download: {len(all_data)}/{total_available}")

        df_gen = pd.DataFrame(all_data)
        if df_gen.empty:
            raise ValueError(f"No generation data available for {date}!")

        df_gen = df_gen[df_gen["period"] != end]  # remove included hour from next day
        df_gen = df_gen.sort_values(["period", "respondent"], ignore_index=True)
        return df_gen
