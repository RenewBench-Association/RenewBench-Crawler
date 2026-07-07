"""ONS DATA DOWNLOADER.

Access of ONS website and their CSV files using pandas' load functionality.
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

URL_BASE = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/geracao_usina_2_ho/"

MIN_YEAR = 2000
EXPECTED_COLS = [
    "din_instante",
    "id_subsistema",
    "nom_subsistema",
    "id_estado",
    "nom_estado",
    "cod_modalidadeoperacao",
    "nom_tipousina",
    "nom_tipocombustivel",
    "nom_usina",
    "id_ons",
    "ceg",
    "val_geracao",
]


class OnsDownloader(EnergyDownloader):
    """ONS data downloader.

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
        self._check_connection(lambda: requests.head(URL_BASE, timeout=10), "ONS")

        logger.info(f"ONS Downloader initialized for:\n- years:\t\t{years}")

    def download_data(self) -> None:
        """Parse data for all given years from ONS site and save to CSV."""
        tasks = [DownloadTask(date=d) for d in self._get_month_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get ONS generation data per plant for one specific month.

        ONS's data storing structure and method was changed in 2022 from
        storing in yearly CSV and Excel files (old) to monthly CSV and Excel files (new).
        The data structure itself (column headers) have remained the same throughout.

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
        if task.year < 2022:
            df = self._get_from_yearly_csv(task)
        else:
            df = self._get_from_monthly_csv(task)

        if df.empty:
            raise MissingDataError("No energy data available (after month filter)!")

        missing_cols = [c for c in EXPECTED_COLS if c not in df.columns]
        if missing_cols:
            raise DataStructureError(
                f"ONS file structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        return df

    @staticmethod
    def _get_from_monthly_csv(task: DownloadTask) -> pd.DataFrame:
        """Extract data from 2022 onwards for a given month.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for a desired month.
        """
        url = f"{URL_BASE}GERACAO_USINA-2_{task.year}_{str(task.month).zfill(2)}.csv"
        df = load_df_from_file(url, delimiter=";")
        return df

    def _get_from_yearly_csv(self, task: DownloadTask) -> pd.DataFrame:
        """Extract data from before 2022 for a given month using the year's CSV.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for a desired month.
        """
        url = f"{URL_BASE}GERACAO_USINA-2_{task.year}.csv"

        with self._download_lock:
            df_year = self._load_yearly_csv(url)

        # filter for the specific month
        month_mask = (df_year["din_instante"].dt.year == task.year) & (
            df_year["din_instante"].dt.month == task.month
        )

        df_month = df_year[month_mask].copy()
        return df_month

    @staticmethod
    @lru_cache(maxsize=None)
    def _load_yearly_csv(url: str) -> pd.DataFrame:
        """Downloads the yearly CSV and ensures datetime column has datetime-like values.

        Args:
            url (str): URL to download data from.

        Returns:
            pd.DataFrame: Dataframe for the desired year.

        Raises:
            DataStructureError: If downloaded data does not have the 'din_instante' column
                or the data in the column cannot be converted to datetime-like values.
        """
        df = load_df_from_file(url, delimiter=";")
        try:
            df["din_instante"] = pd.to_datetime(df["din_instante"])
        except KeyError:
            raise DataStructureError(
                f"ONS file structure change detected for '{url}'! "
                f"Missing datetime column 'din_instante'"
            )
        except ValueError as e:  # if to_datetime raises DateParseError
            raise DataStructureError(
                f"ONS file structure change detected for '{url}'! "
                f"'din_instante' is no longer datetimelike: {e}"
            )
        return df
