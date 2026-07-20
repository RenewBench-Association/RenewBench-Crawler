"""EAT DATA DOWNLOADER.

Access of EAT site and their CSV files using the pandas package.
"""

from concurrent.futures import ThreadPoolExecutor
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

URL_BASE = "https://emidatasets.blob.core.windows.net/publicdata/Datasets/Wholesale/Generation/Generation_MD"

MIN_YEAR = 1997
EXPECTED_COLS = [
    c.lower()
    for c in [
        "Site_Code",
        "POC_Code",
        "Nwk_Code",
        "Gen_Code",
        "Fuel_Code",
        "Tech_Code",
        "Trading_date",
    ]
    + [f"TP{i}" for i in range(1, 51)]
]  # make lower case because column capitalization changes across the years in EAT data


class EatDownloader(EnergyDownloader):
    """EAT data downloader."""

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
        self._check_connection(lambda: requests.head(URL_BASE, timeout=10), "EAT")

        logger.info(f"EAT Downloader initialized for:\n- years:\t\t{years}")

    def download_data(self) -> None:
        """Parse data for all given years from EAT site and save to CSV."""
        tasks = [
            DownloadTask(date=d, temporal_resolution="30min")
            for d in self._get_month_list()
        ]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get EAT generation data per plant for one specific month.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM)

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns
            ['Site_Code', 'POC_Code', 'Nwk_Code', 'Gen_Code', 'Fuel_Code', 'Tech_Code',
             'Trading_date', 'TP1', 'TP2', 'TP3', ..., 'TP49', 'TP50']

        Raises:
            MissingDataError: If an earlier year was provided than data exists for or if the
                dataframe is empty.
            DataStructureError: If the data structure changed and relevant columns are now
                missing (this will cause the entire run to be killed).
        """
        url = f"{URL_BASE}/{task.year}{str(task.month).zfill(2)}_Generation_MD.csv"
        df = load_df_from_file(url, index_col=False)

        if df.empty:
            raise MissingDataError("No energy data available!")

        df.columns = [c.strip().lower() for c in df.columns]
        missing_cols = [c for c in EXPECTED_COLS if c not in df.columns]
        if missing_cols:
            raise DataStructureError(
                f"EAT file structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        return df
