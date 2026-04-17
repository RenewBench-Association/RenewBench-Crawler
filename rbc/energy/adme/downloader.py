"""ADME DATA DOWNLOADER.

Access ADME website and their Excel/CSV files using requests and pandas load.
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

URL_ROOT_NEW = "https://www.adme.com.uy/panelControl/gpf.php"
URL_BASE_NEW = "https://www.adme.com.uy/panelControl/gpf_excel.php?"
URL_ROOT_OLD = "https://www.adme.com.uy/gpf_historico.php"
URL_BASE_OLD = "https://www.adme.com.uy/db-docs/Docs_secciones/nid_1418/"

MIN_YEAR = 2009
EXPECTED_COLS = ["/", "Hidráulico", "Biomasa", "Térmico", "Eólico", "Solar"]
TIME_COL = ("/", "Fecha")
EXPECTED_OLD_SHEETS = ("GPF", "Eólica", "Solar", "Térmica", "Biomasa")


class AdmeDownloader(EnergyDownloader):
    """ADME data downloader.

    Attributes:
        _download_lock (threading.Lock): Lock for downloading yearly data once.
    """

    def __init__(
        self,
        output_path: Path,
        years: list[int],
        resume: bool = True,
    ):
        """Initializes the instance.

        Args:
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.
        """
        super().__init__(
            output_path=output_path, years=years, start_year=MIN_YEAR, resume=resume
        )
        self._download_lock = threading.Lock()
        self._check_connection(
            lambda: requests.head(URL_ROOT_NEW, timeout=10), "ADME (new)"
        )
        self._check_connection(
            lambda: requests.head(URL_ROOT_OLD, timeout=10), "ADME (old)"
        )

        logger.info(f"ADME Downloader initialized for:\n- years:\t\t{years}")

    def download_data(self) -> None:
        """Parse data for all given years from ADME site and save to CSV."""
        tasks = [DownloadTask(date=d) for d in self._get_month_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get ADME generation data per plant for one specific month.

        ADME's data storing structure and method was changed in 2019 from
        storing in yearly Excel files (old) to monthly CSV and Excel files (new).
        When older data is requested, the structure is changed to mirror the columns
        in the newer data and stored per month as well.
        ADME follows an End-of-Interval timestamp convention, meaning values for an hour
        are saved on the dot of the next hour (i.e. "01:00" = data from 0-1 AM, not 1-2 AM).
        This means for each month, data starts with hour 1 of Day 1 and hour 0 of Day 1
        of the next month (i.e. start = "01-01-2018 01:00", end = "01-02-2018 00:00").

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns as per EXPECTED_COLS.

        Raises:
            MissingDataError: If an earlier year was provided than data exists for or if the
                dataframe is empty.
            DataStructureError: If the data structure changed and relevant columns are now
                missing (this will cause the entire run to be killed).
        """
        if task.year < 2019:
            df = self._get_from_old_source(task)
        else:
            df = self._get_from_new_source(task)

        if df.empty:
            raise MissingDataError(
                f"No energy data available for {task.year}-{task.month}. Skipping..."
            )

        missing_cols = [
            c for c in EXPECTED_COLS if c not in df.columns.get_level_values(0)
        ]
        if missing_cols:
            raise DataStructureError(
                f"ADME file structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        return df

    @staticmethod
    def _get_from_new_source(task: DownloadTask) -> pd.DataFrame:
        """Extract data from 2019 onwards (new) source for a given month.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for a desired month.

        Raises:
            DataStructureError: If the data structure changed and relevant columns are now
                missing (this will cause the entire run to be killed).
        """
        month = str(task.month).zfill(2)
        url = f"{URL_BASE_NEW}anod={task.year}&mesd={month}&periodo=1&fuente=0&tipo=1"
        df = load_df_from_file(url, ".csv", delimiter=";", header=[0, 1])

        # filter to exclude anything beyond the required columns (i.e. imported energy)
        try:
            df = df.loc[:, EXPECTED_COLS]
        except KeyError as e:
            raise DataStructureError(
                f"ADME structure change detected for '{task.identifier}'! "
                f"Relevant columns are missing: {e}"
            )

        return df

    def _get_from_old_source(self, task: DownloadTask) -> pd.DataFrame:
        """Extract data from pre-2019 (old) source for a given month using the year's Excel.

        To ensure ADME's End-of-Interval timestamp convention is adhered to, specific
        masking is implemented. This ensures monthly data is stored as previously described.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for a desired month.

        Raises:
            DataStructureError: If the TIME_COL ("fecha"-based) data is not datetime-like.
        """
        url = f"{URL_BASE_OLD}gpf_{task.year}.xlsx"

        with self._download_lock:
            df_year = self._load_yearly_excel(url)

        # filter for the specific month (taking the End-of-Interval convention into account!)
        next_month = pd.Period(task.date, freq="M") + 1
        month_mask = (
            (df_year[TIME_COL].dt.year == task.year)
            & (df_year[TIME_COL].dt.month == task.month)
            & (~((df_year[TIME_COL].dt.day == 1) & (df_year[TIME_COL].dt.hour == 0)))
        ) | (
            (df_year[TIME_COL].dt.year == next_month.year)
            & (df_year[TIME_COL].dt.month == next_month.month)
            & (df_year[TIME_COL].dt.day == 1)
            & (df_year[TIME_COL].dt.hour == 0)
        )
        df_month = df_year[month_mask].copy()

        # revert to original time format to be consistent with source and new (post-2019 CSVs)
        df_month[TIME_COL] = df_month[TIME_COL].dt.strftime("%d-%m-%Y %H:%M")
        return df_month

    @lru_cache(maxsize=None)
    def _load_yearly_excel(self, url: str) -> pd.DataFrame:
        """Downloads the yearly Excel and concatenates into a standardized df once.

        Args:
            url (str): URL to download data from.

        Returns:
            pd.DataFrame: Dataframe for the desired year.

        Raises:
            DataStructureError: If downloaded data does not have all required sheets, sheet
                loading does not work as expected, or the 'Fecha' column data is not
                datetime-like.
        """
        # 1. load excel once to then extract relevant sheets
        xlsx_file = load_excel_from_file(url)

        if not set(EXPECTED_OLD_SHEETS).issubset(set(xlsx_file.sheet_names)):
            raise DataStructureError(
                f"ADME file structure change detected in old excel '{url}'! "
                f"Not all required sheets '{EXPECTED_OLD_SHEETS}' exist!"
            )

        # 2. get relevant sheets
        df_dict = {}

        for sheet in EXPECTED_OLD_SHEETS:
            try:
                # get df per fuel type (wind, solar, etc)
                df = pd.read_excel(xlsx_file, sheet_name=sheet, header=3)

                # special case: extract df for hydro from general "GPF" sheet
                if sheet == "GPF":
                    cutoff = next(
                        (
                            i
                            for i, c in enumerate(df.columns)
                            if c in EXPECTED_OLD_SHEETS
                        ),
                        None,
                    )
                    df = df.iloc[:, :cutoff]

                # define key for storing df as the fuel type
                fuel_type = {
                    "GPF": "Hidráulico",
                    "Eólica": "Eólico",
                    "Térmica": "Térmico",
                }.get(sheet, sheet)

                df = df.set_index("Fecha")
                df_dict[fuel_type] = df

            except Exception as e:
                raise DataStructureError(
                    f"ADME file structure change detected in old excel '{url}'! "
                    f"Sheet {sheet} does not contain loadable data: {e}"
                )

        # 3. concatenate all dataframes into one
        df = pd.concat(df_dict, axis=1)
        df = df.reset_index()

        # 4. ensure df structure is as required for _get_from_old_source processing
        try:
            # format the datetime column header and column values
            df.columns = pd.MultiIndex.from_tuples(
                [TIME_COL if c[0] == "Fecha" else c for c in df.columns]
            )
            df[TIME_COL] = pd.to_datetime(df[TIME_COL], dayfirst=True)

        except ValueError as e:  # if to_datetime raises DateParseError
            raise DataStructureError(
                f"ADME file structure change detected for '{url}'! "
                f"'Fecha' is no longer datetimelike: {e}"
            )

        # sort cols to match new source dfs (cols not in EXPECTED_COLS will be at end)
        df = df[
            sorted(
                df.columns,
                key=lambda c: (
                    EXPECTED_COLS.index(c[0])
                    if c[0] in EXPECTED_COLS
                    else len(EXPECTED_COLS)
                ),
            )
        ]
        return df
