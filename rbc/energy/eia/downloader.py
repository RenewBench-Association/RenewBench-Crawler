"""EIA DATA DOWNLOADER.

Remote API access of EIA website using the requests package.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from loguru import logger
from requests import exceptions

from rbc.energy.utils import (
    MAX_RATE_LIMIT_RETRIES,
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    InvalidError,
    MissingDataError,
    RateLimitError,
)

URL_ROOT = "https://api.eia.gov/v2/"
URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"


class EiaDownloader(EnergyDownloader):
    """EIA data downloader.

    Attributes:
        token (str): The personal EIA API token.
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (dict): Dict of 0 and 1 values for resuming.
    """

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            token (str): The personal EIA API token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.

        Raises:
            InvalidError: If token is invalid or basic API call fails.
        """
        super().__init__(output_path=output_path, years=years, resume=resume)
        self.token = token

        logger.info(f"EIA Downloader initialized for:\n- years:\t\t{years}")

        try:
            response = requests.get(URL_ROOT, params={"api_key": self.token})
            if response.status_code != 200:
                logger.info(f"Failed: {response.json().get('error', {}).get('code')}")
                raise InvalidError(f"Provided API token {token} incorrect.")

        except Exception as e:
            logger.info(f"Failed: {e}")
            raise InvalidError(f"Provided API token {token} incorrect.")

    def download_data(self):
        """Parse data for all given years from EIA site and save to CSV."""
        tasks = [DownloadTask(date=d) for d in self._get_date_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get EIA generation data per plant for one specific date.

        The parsing cap lies at 5000 rows per API call. The amount of hourly data
        per generation company for a single day - without filtering - exceeds that
        (~9000 rows/day), which is why the data is acquired in batches. Given the
        large amount of data, the choice is made here to store a file per day
        instead of per month/year.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns
            ['period', 'respondent', 'respondent-name', 'fueltype', 'type-name',
            'value', 'value-units']

        Raises:
            ConnectionError/Timeout: If API issue occurred with connection or timeout or if
                not all available data was downloaded.
            HTTPError: If request response is not 200.
            RateLimitError: If API rate limit has been exceeded.
            DataStructureError: If response parsing failed due to a change in EIA structure.
            MissingDataError: If the loaded dataframe is empty.
        """
        dt = pd.Period(task.date, freq="D")
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
        attempt = 0

        while True:
            try:
                response = requests.get(URL, params=params, timeout=30)
            except (exceptions.ConnectionError, exceptions.Timeout) as e:
                raise type(e)(f"API request failed: {e}") from e  # dynamically reraise

            if response.status_code != 200:
                if response.status_code == 429:
                    if attempt < MAX_RATE_LIMIT_RETRIES:  # retry 6 times (= 1 min)
                        logger.warning("Rate limit reached. Sleeping 10 seconds...")
                        time.sleep(10)
                        attempt += 1
                        continue
                    else:
                        raise RateLimitError(
                            "API rate limit has been exceeded and waiting 1 min "
                            "doesn't help. You should wait for a brief cool-down "
                            "period (EIA doesn't specify a duration), then retry!"
                        )

                raise exceptions.HTTPError(
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
                raise DataStructureError(
                    f"EIA API structure change detected for '{task.identifier}'!"
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
            raise ConnectionError(
                f"Incomplete download: {len(all_data)}/{total_available}"
            )

        df_gen = pd.DataFrame(all_data)
        if df_gen.empty:
            raise MissingDataError("No energy generation data available! Skipping...")

        df_gen = df_gen[df_gen["period"] != end]  # remove included hour from next day
        df_gen = df_gen.sort_values(["period", "respondent"], ignore_index=True)
        return df_gen
