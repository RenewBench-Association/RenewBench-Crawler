"""REI DATA DOWNLOADER.

Access of REI (Renewable Energy Institute) website and their JSON files using requests.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
from loguru import logger
from zoneinfo import ZoneInfo

from rbc.energy.utils import (
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    MissingDataError,
    write_df_to_csv,
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
EXPECTED_COLS_MAPPING = {
    "nuclear": "Nuclear",
    "thermal": "Thermal",
    "hydropower": "Hydropower",
    "geothermal": "Geothermal",
    "bioenergy": "Biomass",
    "solar": "SolarPV",
    "wind": "Wind",
    "pumping_up": "Pumped hydro(pump up)",
    "pumping_down": "Pumped hydro(generate)",
    "regional_in": "Import",
    "regional_out": "Export",
    "solar_curtailment": "SolarPV(curtailment)",
    "wind_curtailment": "Wind(curtailment)",
    # 'demand': 'Demand',
    # 'spot_price': 'JEPX Day-Ahead Market Price',
}


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
        """Parse data for all given years from REI site and save to CSV."""
        tasks = [DownloadTask(date=d) for d in self._get_month_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get REI generation data per plant for one specific month using the year's JSON.

        REI's data is provided by interactive dashboard with downloadable CSV files. These
        are based on underlying yearly JSON files. The CSVs cannot be directly requested
        remotely, so instead the JSON files are loaded and reformatted to match the CSVs.
        For any given year, the "yearly" JSON file actually spans from April of said year
        to March 31st of the next (!) year. This needs to be accounted.
        Checks for DataStructureErrors are all included in the "_load_yearly_json" method.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns as per EXPECTED_COLS.

        Raises:
            MissingDataError: If an earlier year was requested than data exists for or if the
                parsed monthly dataframe is empty.
        """
        # check which yearly JSON is required based on the task month
        year = task.year if task.month >= 4 else task.year - 1

        if year < MIN_YEAR:
            raise MissingDataError(
                f"No energy data available (it's before {MIN_YEAR}-4). Skipping..."
            )

        # load yearly JSON file
        url = f"{URL_BASE}data/{year}/power-data.json"

        with self._download_lock:
            df_year = self._load_yearly_json(url)

        # filter for the specific month
        month_mask = (df_year.index.year == task.year) & (
            df_year.index.month == task.month
        )

        df = df_year[month_mask].copy()
        if df.empty:
            raise MissingDataError(
                "No energy data left after extracting task month. Skipping..."
            )

        return df

    @staticmethod
    @lru_cache(maxsize=None)
    def _load_yearly_json(url: str) -> pd.DataFrame:
        """Downloads the yearly JSON and reformats to match downloadable CSVs.

        After getting a raw JSON file, it is converted into a dataframe to mimic the CSVs
        returned by the REI dashboard: https://www.renewable-ei.org/en/statistics/electricity/
        These have a MultiIndex (double row header) format with lots of "unnamed" columns.
        The raw JSON structure:
        - dict:
            'epochs': list(UNIX times),
            '<EXPECTED_REGIONS regions>': dict:
                <EXPECTED_COLS_MAPPING keys>: list(power values)
            '<other regions>': dict: ...
        The "raw" CSV structure as given in files downloaded via the dashboard:
        - MultiIndex([
            (                    '',                          ''),  # date (local Japan)
            (                    '',                          ''),  # time (local Japan)
            ('<EXPECTED_REGIONS 1>', '<EXPECTED_COLS_MAPPING 1>'),  # reg 1, fueltype 1 vals
            (                    '', '<EXPECTED_COLS_MAPPING 2>'),  # reg 1, fueltype 2 vals
            (                    '', '<EXPECTED_COLS_MAPPING 3>'),  # ...
            ...
            ('<EXPECTED_REGIONS n>', '<EXPECTED_COLS_MAPPING 1>'),  # reg n, fueltype 1 vals
            ...
            (                    '', '<EXPECTED_COLS_MAPPING m>'),  # reg n, fueltype m vals
          ])
        The df structure returned by the method here is:
        - MultiIndex([
            ('<EXPECTED_REGIONS 1>', '<EXPECTED_COLS_MAPPING 1>'),  # reg 1, fueltype 1 vals
            ...
            ('<EXPECTED_REGIONS n>', '<EXPECTED_COLS_MAPPING 1>'),  # reg n, fueltype 1 vals
            ...
            (                    '', '<EXPECTED_COLS_MAPPING m>'),  # reg n, fueltype m vals
          ])
          ===> with index = timestamp in globally defined TIMEZONE.
        The division into the two columns (date, time) occur later.

        Args:
            url (str): URL to download data from.

        Returns:
            pd.DataFrame: Dataframe for the desired year.

        Raises:
            DataStructureError: If downloaded data is missing any of the expected regions
                or columns (incl. the "epochs" column) or if the data in "epochs" cannot
                be converted to datetime-like values.
        """
        response = requests.get(url, timeout=120)
        response.raise_for_status()  # errors are propagated to _download_task in parent

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as e:
            raise DataStructureError(
                f"REI file structure change detected for '{url}'! "
                f"Data no longer json-serializable: {e}"
            )

        try:
            # get UNIX/Epoch time and convert to local japanese timezone
            dt_index = pd.to_datetime(data["epochs"], unit="s")
            dt_index = dt_index.tz_localize("UTC").tz_convert(TIMEZONE)

            # create list of region dfs by iterating through expected regions
            df_list = []

            for region in EXPECTED_REGIONS:
                # create df with columns = EXPECTED_COLS_MAPPING
                # i.e. ['Nuclear', 'Thermal', 'Hydropower', 'Biomass', ...]
                region_df = pd.DataFrame(data[region])
                region_df = region_df[list(EXPECTED_COLS_MAPPING)]
                region_df = region_df.rename(columns=EXPECTED_COLS_MAPPING)

                # create top row of MultiIndex (double headers) with region name as first col
                # i.e.: ['Hokkaido', '', ..., '']
                cols = [
                    (region.capitalize() if i_col == 0 else "", col)
                    for i_col, col in enumerate(region_df.columns)
                ]

                region_df.columns = pd.MultiIndex.from_tuples(cols)
                df_list.append(region_df)

            # combine individual region dfs into full df with timestamp index (as helper)
            df = pd.concat(df_list, axis=1)
            df.index = dt_index

        except KeyError as e:
            raise DataStructureError(
                f"REI file structure change detected for '{url}'! "
                f"Missing region and/or column: {e}"
            )
        except ValueError as e:  # if to_datetime raises DateParseError
            raise DataStructureError(
                f"REI file structure change detected for '{url}'! "
                f"'epochs' is no longer datetimelike: {e}"
            )
        return df

    def _save_task_data(self, task: DownloadTask, df: pd.DataFrame) -> None:
        """Save REI downloaded task data to disk, ensuring date and time columns are included.

        The REI CSV files have a date and time column with blank headers. To mimic this,
        the saving method needs to adapted to allow this behavior.

        Args:
            task (DownloadTask): The metadata for the task that was downloaded.
            df (pd.DataFrame): Downloaded dataframe for the task.
        """
        file_path = self._build_task_path(task)

        # expand the index (timestamp) to two columns (date, time)
        df_save = df.copy()
        df_save.insert(0, ("Date", ""), df_save.index.strftime("%Y/%m/%d"))
        df_save.insert(1, ("Time", ""), df_save.index.strftime("%H:%M"))

        # construct a clean list of headers to match the REI CSVs
        new_cols = [("", "")] * 2 + list(df_save.columns[2:])

        # overwrite all columns at once (Pandas allows duplicate headers this way!)
        df_save.columns = pd.MultiIndex.from_tuples(new_cols)

        write_df_to_csv(df=df_save, file_path=file_path, index=False)
