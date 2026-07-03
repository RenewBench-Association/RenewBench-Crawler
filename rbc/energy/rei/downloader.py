"""REI DATA DOWNLOADER.

Access of REI (Renewable Energy Institute) website and their JSON files using requests.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from loguru import logger

from rbc.energy.utils import (
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    InvalidError,
    MissingDataError,
    write_dict_to_json,
)

TIMEZONE = ZoneInfo("Asia/Tokyo")
URL_BASE = "https://www.renewable-ei.org/en/statistics/electricity/"

MIN_YEAR = 2016  # April
EXPECTED_REGIONS = [
    "hokkaido",
    "tohoku",
    "tokyo",
    "chubu",
    "hokuriku",
    "kansai",
    "chugoku",
    "shikoku",
    "kyushu",
]
EXPECTED_KEYS = ["epochs"] + EXPECTED_REGIONS


class ReiDownloader(EnergyDownloader):
    """REI data downloader.

    Attributes:
        _download_lock (threading.Lock): Lock for downloading yearly data once.
    """

    def __init__(
        self,
        output_path: Path,
        years: list[int],
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.

        Raises:
            ConnectionError: If the base URL isn't reachable.
        """
        super().__init__(
            output_path=output_path, years=years, start_year=MIN_YEAR, resume=resume
        )
        self._download_lock = threading.Lock()
        self._check_connection(lambda: requests.head(URL_BASE, timeout=10), "REI")

        logger.info(f"REI Downloader initialized for:\n- years:\t\t{years}")

    def download_data(self) -> None:
        """Parse data for all given years from REI site and save to JSON."""
        tasks = [DownloadTask(date=d) for d in self._get_month_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> dict:  # type: ignore[override]
        """Get REI generation data per plant for one specific month using the year's JSON.

        REI's data is provided by interactive dashboard with downloadable CSV files,
        based on underlying yearly JSON files. The CSVs cannot be directly requested
        remotely, so instead the raw JSON files are loaded and stored.
        For any given year, the "yearly" JSON file actually spans from April of said year
        to March 31st of the next (!) year. This needs to be accounted for.
        Checks for DataStructureErrors are all included in the "_load_yearly_json" method.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            dict: Dictionary for specific date with the keys as per EXPECTED_KEYS.

        Raises:
            MissingDataError: If an earlier year was requested than data exists for or if the
                parsed monthly dictionary is empty.
        """
        # check which yearly JSON is required based on the task month
        json_year = task.year if task.month >= 4 else task.year - 1

        if json_year < MIN_YEAR:
            raise MissingDataError(
                f"No energy data available (it's before {MIN_YEAR}-4). Skipping..."
            )

        # load yearly JSON file
        url = f"{URL_BASE}data/{json_year}/power-data.json"

        with self._download_lock:
            # NOTE: dict_year is cached - do NOT mutate it!
            dict_year, ts_year = self._load_yearly_json(url)

        # filter timestamps to get the specific month
        month_mask = (ts_year.year == task.year) & (ts_year.month == task.month)
        matching_indices = month_mask.nonzero()[0]

        if len(matching_indices) == 0:
            raise MissingDataError(
                f"No energy data found for month {task.year}-{task.month}. Skipping..."
            )

        start_idx = matching_indices[0]
        end_idx = matching_indices[-1] + 1  # +1 because Python slicing is exclusive

        if len(matching_indices) != (end_idx - start_idx):
            logger.warning(
                f"REI timestamp continuity issue detected for {task.year}-{task.month}: "
                f"{len(matching_indices)} timestamps in range of {end_idx - start_idx}!"
            )

        # build monthly dict by slicing all arrays from the cached yearly data
        dict_month = {"epochs": dict_year["epochs"][start_idx:end_idx]}

        for key in dict_year:
            if key == "epochs":
                continue
            dict_month[key] = {
                fueltype: values[start_idx:end_idx]
                for fueltype, values in dict_year[key].items()
            }

        return dict_month

    @staticmethod
    @lru_cache(maxsize=None)
    def _load_yearly_json(url: str) -> tuple[dict, pd.DatetimeIndex]:
        """Downloads the yearly JSON and slims dict down to keys of interest.

        The raw yearly JSON should have the following setup, which is ensured through checks:
        - dict:
            'epochs': list(UNIX times),
            '<EXPECTED_REGIONS regions>': dict:
                <EXPECTED_FUELTYPES>: list(power values)
            '<other regions>': dict: ...

        Only the EXPECTED_KEYS are retained, not other regions. Fuel type names are not
        validated here as they vary across years (e.g., 'thermal' in pre-2024 data vs.
        'thermal_lng', 'thermal_coal', etc. from 2024 onwards). Instead, structural integrity
        is verified: region data must be a dict and all fuel type arrays must have the same
        length as the epoch timestamps.

        Args:
            url (str): URL to download data from.

        Returns:
            dict: JSON data for the desired year.
            pd.DatetimeIndex: List of all timestamps given in the data for the desired year.

        Raises:
            DataStructureError: If downloaded data is missing any of the expected regions
                or columns (incl. the "epochs" column), if the data in "epochs" cannot
                be converted to datetime-like values, if region data is not a dictionary,
                if there are issues with the intervals (s. _determine_temporal_resolution)
                or if the amount of energy generation values doesn't match the epoch number.
        """
        response = requests.get(url, timeout=120)
        response.raise_for_status()  # errors are propagated to _download_task in parent

        try:
            data: dict = response.json()
        except requests.exceptions.JSONDecodeError as e:
            raise DataStructureError(
                f"REI file structure change detected for '{url}'! "
                f"Data no longer json-serializable: {e}"
            )

        try:
            # get timestamps from epoch for monthly slicing later
            ts_data = pd.DatetimeIndex(pd.to_datetime(data["epochs"], unit="s"))
            ts_data = ts_data.tz_localize("UTC").tz_convert(TIMEZONE)
            num_ts = len(ts_data)  # number of timestamps

            t_res = ReiDownloader._determine_temporal_resolution(ts_data, context=url)
            logger.info(f"REI data for {url} has a temporal resolution of {t_res}.")

            # slim down full yearly JSON to only get the expected keys
            relevant_data = {k: data[k] for k in EXPECTED_KEYS}

            for r in EXPECTED_REGIONS:
                r_data = relevant_data[r]
                if not isinstance(r_data, dict):
                    raise DataStructureError(
                        f"REI file structure change detected for '{url}'! "
                        f"Region '{r}' data is no longer a dictionary!"
                    )
                for ft, ft_data in r_data.items():
                    if len(ft_data) != num_ts:
                        raise DataStructureError(
                            f"REI file structure change detected for '{url}'! "
                            f"Data for region '{r}', fueltype '{ft}' has {len(ft_data)} "
                            f"entries, but there are {num_ts} timestamps!"
                        )

        except KeyError as e:
            raise DataStructureError(
                f"REI file structure change detected for '{url}'! "
                f"Missing expected JSON dict key: {e}"
            )
        except ValueError as e:  # if to_datetime raises DateParseError
            raise DataStructureError(
                f"REI file structure change detected for '{url}'! "
                f"'epochs' is no longer datetimelike: {e}"
            )

        return relevant_data, ts_data

    def _save_task_data(self, task: DownloadTask, data: pd.DataFrame | dict) -> None:
        """Save REI downloaded task data to disk, splitting by temporal resolution.

        The JSON file does not have specific temporal resolutions specified, but the
        UNIX epochs (timestamps) vary from hourly intervals (up until 2024-03) to half
        hourly intervals (2024-04 onwards). This means the task definition needs to be
        adapted to ensure correct saving.

        Args:
            task (DownloadTask): The metadata for the task that was downloaded.
            data (pd.DataFrame | dict): Downloaded dataframe for the task.
        """
        if not isinstance(data, dict):
            raise InvalidError(
                f"REI data for '{task.identifier}' must be a dictionary, "
                f"got '{type(data).__name__}'."
            )

        ts_data = pd.DatetimeIndex(pd.to_datetime(data["epochs"], unit="s"))
        ts_data = ts_data.tz_localize("UTC").tz_convert(TIMEZONE)
        t_res = self._determine_temporal_resolution(ts_data, context=task.identifier)

        updated_task = task.update(temporal_resolution=t_res)
        base_path = self._build_task_path(updated_task)
        write_dict_to_json(data=data, file_path=base_path)

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    @staticmethod
    def _determine_temporal_resolution(ts_data: pd.DatetimeIndex, context: str) -> str:
        """Determines the temporal resolution from a list of timestamps.

        Args:
            ts_data (pd.DatetimeIndex): List of timestamps.
            context (str): Context (like URL or task info) for log/error messages.

        Returns:
            str: Temporal resolution string, e.g. "1h" or "30min".

        Raises:
            DataStructureError: If there are fewer than two timestamps,
                if they aren't monotonically increasing,
                if the determined temporal resolution is not a whole number
                or has grown to be coarser than 1h.
        """
        msg = f"REI timestamp continuity issue detected for {context}"

        if len(ts_data) < 2:
            raise DataStructureError(f"{msg}: Less than 2 timestamps!")
        if not ts_data.is_monotonic_increasing:
            raise DataStructureError(f"{msg}: Timestamps not monotonically increasing!")

        ts_diffs = pd.Series(ts_data[1:] - ts_data[:-1])
        ts_diff = ts_diffs.mode().iloc[0]  # most common Timedelta interval
        t_res = ts_diff.total_seconds() / 60

        if (ts_diffs != ts_diff).any():
            logger.warning(f"{msg}: Temporal resolution is not constant!")

        if t_res % 1 != 0:
            raise DataStructureError(
                f"{msg}: Temporal resolution {t_res}min not a whole number!"
            )

        t_res = int(t_res)
        if t_res > 60:
            raise DataStructureError(
                f"{msg}: Temporal resolution {t_res}min is greater than 1h!"
            )

        return "1h" if t_res == 60 else f"{t_res}min"
