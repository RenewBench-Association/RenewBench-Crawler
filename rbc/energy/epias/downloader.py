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

from rbc.energy.utils import WORKERS, DownloadKey, EnergyDownloader


class EpiasDownloader(EnergyDownloader):
    """EPIAS data downloader.

    Attributes:
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (dict): Dict of 0 and 1 values for resuming.
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
            ValueError: If login credentials are incorrect.
        """
        super().__init__(output_path=output_path, years=years, resume=resume)
        self.checkpoint_path = Path(self.output_path, "status.pickle")
        self.checkpoint = self._load_checkpoint(self.checkpoint_path)

        logger.info(f"EPIAS Downloader initialized for:\n- years:\t\t{years}")

        try:
            self.eptr = EPTR2(username=username, password=password)
        except Exception:
            raise ValueError("Provided username and password are incorrect.")

    def download_data(self):
        """Parse data for all given years from EPIAS Platform and save to CSV."""
        tasks = [DownloadKey(date=d) for d in self._get_date_list()]

        logger.info(f"Downloading data for tasks:\n{tasks[0]} to {tasks[-1]}")
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(
                lambda t: self._threading_wrapper(
                    t, self.checkpoint, self.checkpoint_path
                ),
                tasks,
            )

    def _get_task_data(self, task: DownloadKey) -> pd.DataFrame:  # type: ignore[override]
        """Get EPIAS generation data per plant for one specific date.

        Args:
            task (DownloadKey): The metadata of a downloading task, here: date (YYYY-MM-DD)

        Returns:
            pd.DataFrame: Dataframe for specific date.

        Raises:
            ValueError: If no power plant or generation data is available.
        """
        task.validate_required_fields("date")

        # get power-plants   # ['id', 'name', 'eic', 'shortName']
        start = task.date
        end = (pd.Timestamp(start) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df_pp = self.eptr.call("pp-list-for-date-range", start_date=start, end_date=end)
        if df_pp.empty:
            raise ValueError(f"No power plant data available for {task}!")

        # get generation data in batches
        num_batches = math.ceil(len(df_pp) / 1000)  # max allowed batch size = 1000
        batches = np.array_split(df_pp["id"].values, num_batches)

        gen_data = [
            self.eptr.call("rt-gen-bulk", date=task.date, pp_ids=b.tolist())
            for b in batches
        ]

        df_gen = pd.concat(gen_data)
        if df_gen.empty:
            raise ValueError(f"No generation data available for {task}!")

        return df_gen
