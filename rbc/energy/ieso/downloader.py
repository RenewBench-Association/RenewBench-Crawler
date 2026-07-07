"""IESO DATA DOWNLOADER.

Access of IESO website and their Excel/CSV files using pandas' load functionality.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

from rbc.energy.utils import (
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    MissingDataError,
    load_df_from_file,
    load_excel_from_file,
)

URL_BASE_NEW = "https://reports-public.ieso.ca/public/GenOutputCapabilityMonth"
URL_BASE_OLD = "https://www.ieso.ca"

MIN_YEAR = 2010
EXPECTED_COLS = ["Delivery Date", "Generator", "Fuel Type", "Measurement"] + [
    f"Hour {i}" for i in range(1, 25)
]


class IesoDownloader(EnergyDownloader):
    """IESO data downloader.

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
            ConnectionError: If the base URLs aren't reachable.
        """
        super().__init__(
            output_path=output_path, years=years, start_year=MIN_YEAR, resume=resume
        )
        self._download_lock = threading.Lock()
        self._check_connection(
            lambda: requests.head(URL_BASE_NEW, timeout=10), "IESO (new)"
        )
        self._check_connection(
            lambda: requests.head(URL_BASE_OLD, timeout=10), "IESO (old)"
        )

        logger.info(f"IESO Downloader initialized for:\n- years:\t\t{years}")

    def download_data(self) -> None:
        """Parse data for all given years from IESO site and save to CSV."""
        tasks = [DownloadTask(date=d) for d in self._get_month_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get IESO generation data per plant for one specific month.

        IESO's data storing structure and method was changed in April 2019 from
        storing in yearly Excel files (old) to monthly CSV files (new).
        When older data is requested, the structure is changed to mirror the columns
        in the newer data and stored per month as well.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns
            ['Delivery Date', 'Generator', 'Fuel Type', 'Measurement',
            'Hour 1', 'Hour 2', 'Hour 3', ..., 'Hour 23', 'Hour 24']

        Raises:
            MissingDataError: If an earlier year was provided than data exists for or if the
                dataframe is empty.
            DataStructureError: If the data structure changed and relevant columns are now
                missing (this will cause the entire run to be killed).
        """
        if task.year < 2019 or (task.year == 2019 and task.month <= 4):
            df = self._get_from_old_source(task)
        else:
            df = self._get_from_new_source(task)

        if df.empty:
            raise MissingDataError("No energy data available!")

        missing_cols = [c for c in EXPECTED_COLS if c not in df.columns]
        if missing_cols:
            raise DataStructureError(
                f"IESO file structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        return df

    @staticmethod
    def _get_from_new_source(task: DownloadTask) -> pd.DataFrame:
        """Extract data from post-04-2019 (new) source for a given month.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for a desired month.

        Raises:
            DataStructureError: If downloaded data does not have the 'Measurement' column.
        """
        url = f"{URL_BASE_NEW}/PUB_GenOutputCapabilityMonth_{task.year}{str(task.month).zfill(2)}.csv"
        df = load_df_from_file(url, header=3, index_col=False)

        try:
            df = df[df["Measurement"] != "Forecast"]
        except KeyError:
            raise DataStructureError(
                f"IESO file structure change detected in new csv '{url}'! "
                f"'Measurement' column is missing!"
            )
        return df

    def _get_from_old_source(self, task: DownloadTask) -> pd.DataFrame:
        """Extract data from pre-04-2019 (old) source for a given month using the year's Excel.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for a desired month.

        Raises:
            DataStructureError: If 'Delivery Date' column data is not datetime-like.
        """
        url = f"{URL_BASE_OLD}/-/media/Files/IESO/Power-Data/data-directory/GOC-{task.year}"
        url += "-Jan-April.xlsx" if task.year == 2019 else ".xlsx"

        with self._download_lock:
            df_year = self._load_yearly_excel(url)

        # filter for the specific month
        try:
            month_mask = (df_year["Delivery Date"].dt.year == task.year) & (
                df_year["Delivery Date"].dt.month == task.month
            )
        except AttributeError as e:
            raise DataStructureError(
                f"IESO file structure change detected in old excel '{url}'! "
                f"'Delivery Date' is no longer datetimelike: {e}"
            )

        df_month = df_year[month_mask].copy()
        return df_month

    @lru_cache(maxsize=1)
    def _load_yearly_excel(self, url: str) -> pd.DataFrame:
        """Downloads the yearly Excel and concatenates into a standardized df once.

        Args:
            url (str): URL to download data from.

        Returns:
            pd.DataFrame: Dataframe for the desired year.

        Raises:
            DataStructureError: If downloaded data does not have capacity values.
        """
        # 1. load excel once to then extract relevant sheets
        xlsx_file = load_excel_from_file(url)

        # 2. get generation ('Output') data and standardize
        df_gen = pd.read_excel(xlsx_file, sheet_name="Output")
        df_gen = self.standardize_old_data(df_gen, "Output")

        # 2. get capacity ('Capability') data and standardize
        df_cap = None
        for sheet in [
            "Available Capacities",  # for 2015-2018 (correct wind/solar values)
            "Capability - see Notes",  # for 2014 (weird naming in 2014)
            "Capability",  # for 2010-2013 and 2019
        ]:
            try:
                df_cap = pd.read_excel(xlsx_file, sheet_name=sheet)
                break
            except ValueError:  # continue to next one if sheet does not exist
                continue

        if df_cap is None:
            raise DataStructureError(
                f"IESO file structure change detected in old excel '{url}'! "
                f"No valid capacity sheets found!"
            )

        df_cap = self.standardize_old_data(df_cap, "Capability")

        # 3. concatenate generation and capacity into one df
        df = pd.concat([df_gen, df_cap], ignore_index=True)
        df = df.sort_values(by=["Delivery Date", "Generator", "Measurement"])
        return df

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    @staticmethod
    def standardize_old_data(df: pd.DataFrame, measurement_type: str) -> pd.DataFrame:
        """Standardize old dataframes (before 04-2019) to match the newer CSV format.

        From:   DATE | HOUR | Unnamed: 2 | Generator 1 | Generator 2 | ...
        → to:   Delivery Date | Generator | Fuel Type | Measurement | Hour 1 | Hour 2 | ...

        Args:
            df (pd.DataFrame): Dataframe for a desired year.
            measurement_type (str): Type of measurement.

        Returns:
            pd.DataFrame: restructured Dataframe for a specific year.

        Raises:
            DataStructureError: If the downloaded df is missing any required columns.
        """
        try:
            df.columns = df.columns.str.upper()

            # remove irrelevant columns or rows
            df = df.drop(columns=["Unnamed: 2"], errors="ignore")
            df = df[df["DATE"].notna()]  # rows where DATE = "NaN"

            # transpose from wide (col per generator) into long format (row per generator)
            df_long = df.melt(
                id_vars=["DATE", "HOUR"],
                value_vars=[col for col in df.columns if col not in ["DATE", "HOUR"]],
                var_name="Generator",
                value_name="Value",
            )

            # remove exact duplicates (happens sometimes in IESO files and causes error)
            df_long = df_long.drop_duplicates(subset=["DATE", "Generator", "HOUR"])

            # pivot the table to get columns per hour
            df_wide = df_long.pivot(
                index=["DATE", "Generator"], columns="HOUR", values="Value"
            )
            df_wide.columns = [f"Hour {int(c)}" for c in df_wide.columns]
            df_wide = df_wide.reset_index()

            df_wide.insert(2, "Fuel Type", None)  # define properly during processing
            df_wide.insert(3, "Measurement", measurement_type)

            df_wide = df_wide.rename(columns={"DATE": "Delivery Date"})

        except KeyError as e:
            raise DataStructureError(
                f"IESO file structure change detected in old excel! "
                f"Relevant columns are missing: {e}"
            )

        return df_wide
