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
)

URL_NEW_BASE = "https://reports-public.ieso.ca/public/GenOutputCapabilityMonth"
URL_OLD_BASE = "https://www.ieso.ca"
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
        super().__init__(output_path=output_path, years=years, resume=resume)
        self._download_lock = threading.Lock()

        logger.info(f"IESO Downloader initialized for:\n- years:\t\t{years}")

        try:
            for url in [URL_NEW_BASE, URL_OLD_BASE]:
                requests.head(url, timeout=10).raise_for_status()

        except Exception as e:
            logger.error("Initialization IESO connectivity check failed!")
            raise ConnectionError(f"One or more IESO endpoints are unreachable: {e}")

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
        dt = pd.Period(task.date, freq="M")
        year = dt.year
        month = dt.month

        if year < 2010:
            raise MissingDataError(
                f"No data for year {year} (it's before 2010). Skipping..."
            )

        if year < 2019 or (year == 2019 and month <= 4):
            df = self._get_from_old_source(year, month)
        else:
            df = self._get_from_new_source(year, month)

        if df.empty:
            raise MissingDataError(
                f"No energy generation data available for {year}-{month}. Skipping..."
            )

        missing_cols = [c for c in EXPECTED_COLS if c not in df.columns]
        if missing_cols:
            raise DataStructureError(
                f"IESO file structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        return df

    @staticmethod
    def _get_from_new_source(year: int, month: int) -> pd.DataFrame:
        """Extract data from post-04-2019 (new) source for a given month.

        Args:
            year (int): Year to extract data for.
            month (int): Month to extract data for.

        Returns:
            pd.DataFrame: Dataframe for a desired month.

        Raises:
            RETRY_ERRORS / InvalidError: If loading data from the URL fails.
            DataStructureError: If downloaded data does not have the 'Measurement' column.
        """
        url = f"{URL_NEW_BASE}/PUB_GenOutputCapabilityMonth_{year}{str(month).zfill(2)}.csv"
        df = load_df_from_file(url, header=3, index_col=False)

        try:
            df = df[df["Measurement"] != "Forecast"]
        except KeyError:
            raise DataStructureError(
                f"IESO file structure change detected in new csv '{url}'! "
                f"'Measurement' column is missing!"
            )
        return df

    def _get_from_old_source(self, year: int, month: int) -> pd.DataFrame:
        """Extract data from pre-04-2019 (old) source for a given month using the year's Excel.

        Args:
            year (int): Year to extract data for.
            month (int): Month to extract data for.

        Returns:
            pd.DataFrame: Dataframe for a desired month.

        Raises:
            DataStructureError: If downloaded data does not have the 'Measurement' column.
        """
        url = f"{URL_OLD_BASE}/-/media/Files/IESO/Power-Data/data-directory/GOC-{year}"
        url += "-Jan-April.xlsx" if year == 2019 else ".xlsx"

        with self._download_lock:
            df_year = self._load_yearly_excel(url)

        # filter for the specific month
        try:
            month_mask = (df_year["Delivery Date"].dt.year == year) & (
                df_year["Delivery Date"].dt.month == month
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
            RETRY_ERRORS / InvalidError: If loading data from the URL fails.
            DataStructureError: If downloaded data does not have capacity values.
        """
        # 1. get generation ('Output') data and standardize
        df_gen = load_df_from_file(url, sheet_name="Output")
        df_gen = self.standardize_old_data(df_gen, "Output")

        # 2. get capacity ('Capability') data and standardize
        df_cap = None
        for sheet in [
            "Available Capacities",  # for 2015-2018 (correct wind/solar values)
            "Capability - see Notes",  # for 2014 (weird naming in 2014)
            "Capability",  # for 2010-2013 and 2019
        ]:
            try:
                df_cap = load_df_from_file(url, sheet_name=sheet)
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
        """Standardize old (pre-2019) dataframes to match the newer CSV format.

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
