"""EPIAS DATA DOWNLOADER.

Remote API access of EPIAS Platform using the eptr2 package.
"""

import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from eptr2 import EPTR2
from loguru import logger

from rbc.energy.utils import (
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    InvalidError,
    MissingDataError,
)

MIN_YEAR = 2013
EXPECTED_COLS = [
    "date",
    "hour",
    "total",
    "powerPlantName",
    "naturalGas",
    "dammedHydro",
    "lignite",
    "river",
    "importCoal",
    "wind",
    "sun",
    "fueloil",
    "geothermal",
    "asphaltiteCoal",
    "blackCoal",
    "biomass",
    "naphta",
    "lng",
    "importExport",
    "wasteheat",
]


class EpiasDownloader(EnergyDownloader):
    """EPIAS data downloader.

    Attributes:
        eptr (EPTR2): EPTR2 object for EPIAS data access.
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
            InvalidError: If login credentials are incorrect.
        """
        super().__init__(output_path=output_path, years=years, resume=resume)

        logger.info(f"EPIAS Downloader initialized for:\n- years:\t\t{years}")

        try:
            self.eptr = EPTR2(username=username, password=password)
        except Exception:
            raise InvalidError("Provided username and password are incorrect.")

    def download_data(self):
        """Parse data for all given years from EPIAS Platform and save to CSV."""
        tasks = [DownloadTask(date=d) for d in self._get_date_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get EPIAS generation data per plant for one specific date.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)

        Returns:
            pd.DataFrame: Dataframe for specific date.

        Raises:
            MissingDataError: If no power plant or generation data is available.
            DataStructureError: If the data structure changed and relevant columns are now
                missing (this will cause the entire run to be killed).
        """
        if task.year < MIN_YEAR:
            raise MissingDataError(
                f"No energy data for year {task.year} (it's before {MIN_YEAR}). Skipping..."
            )

        # get power-plants   # ['id', 'name', 'eic', 'shortName']
        start = task.date
        end = (task.dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        df_pp = self.eptr.call("pp-list-for-date-range", start_date=start, end_date=end)
        if df_pp.empty:
            raise MissingDataError("No power plant data available! Skipping...")

        # get generation data in batches
        num_batches = math.ceil(len(df_pp) / 1000)  # max allowed batch size = 1000
        batches = np.array_split(df_pp["id"].values, num_batches)

        gen_data = [
            self.eptr.call("rt-gen-bulk", date=start, pp_ids=b.tolist())
            for b in batches
        ]

        df_gen = pd.concat(gen_data)
        if df_gen.empty:
            raise MissingDataError("No energy data available! Skipping...")

        missing_cols = [c for c in EXPECTED_COLS if c not in df_gen.columns]
        if missing_cols:
            raise DataStructureError(
                f"EPIAS structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        return df_gen
