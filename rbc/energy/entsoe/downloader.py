"""ENTSOE-E DATA DOWNLOADER.

Remote API access of ENTSO-E Platform using the entsoe-apy package.
"""

import os
import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from entsoe.config import get_config, set_config
from entsoe.Generation import ActualGenerationPerGenerationUnit
from entsoe.query.decorators import ServiceUnavailableError
from entsoe.utils import add_timestamps, extract_records, mappings
from loguru import logger
from requests.models import ReadTimeoutError

from rbc.energy.utils import (
    MAX_RETRIES,
    RETRY_DELAY,
    WORKERS,
    DataStructureError,
    write_df_to_csv,
)

RELEVANT_RECORD_KEYS = {
    "timestamp": "timestamp",
    "time_series.mkt_psrtype.power_system_resources.name": "Unit_Name",
    "time_series.mkt_psrtype.power_system_resources.m_rid.value": "Unit_Code",
    "time_series.mkt_psrtype.psr_type": "PSR_Type",
    "time_series.mkt_psrtype.power_system_resources.nominal_p": "Capacity",
    "time_series.period.point.quantity": "Generation_MW",
    "time_series.period.point.secondary_quantity": "Consumption_MW",
    "time_series.quantity_measure_unit_name": "Measurement_Unit",
    "time_series.period.resolution": "Temporal_Resolution",
}


class EntsoeDownloader:
    """Entsoe-E data downloader.

    Attributes:
        years (list[str]): List of years to get data for.
        bidding_zones (list[str]): List of bidding zones to get data for.
        output_path (Path): Path to the output directory.
        resume (bool, optional): Whether to resume from a previous
         download (True) or start from scratch (False). Defaults to True.
    """

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        bidding_zones: list[str] = mappings.keys(),
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Attributes:
            token (str): The personal ENTSO-E RESTful API token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            bidding_zones (list[str]): List of bidding zones to get data for.
            resume (bool, optional): Whether to resume from a previous
             download (True) or start from scratch (False). Defaults to True.

        Raises:
            ValueError: If bidding zone is unsupported or token is invalid.
        """
        self.years = years
        self.bidding_zones = list(bidding_zones)
        self.output_path = output_path
        self.resume = resume
        self._lock = threading.Lock()

        for bz in self.bidding_zones:
            if bz not in list(mappings.keys()):
                raise ValueError(f"Bidding zone '{bz}' is not supported.")

        logger.info(
            f"Entsoe-E Downloader initialised for:"
            f"\n- bidding zones:\t{bidding_zones}"
            f"\n- years:\t\t{years}"
        )

        set_config(security_token=token)
        if get_config().security_token is None:
            raise ValueError(
                f"Entsoe-apy failed to successfully configure token '{token}'!"
            )

    def download_data(self) -> None:
        """Parse data for all given years and zones from ENTSO-E Platform and save to CSV."""
        all_dates = self._get_date_list()

        try:
            for bz in self.bidding_zones:
                bz_path = Path(self.output_path, bz)
                bz_path.mkdir(parents=True, exist_ok=True)

                checkpoint_path = Path(bz_path, "status.pickle")
                checkpoint = self._load_checkpoint(checkpoint_path)

                logger.info(
                    f"Downloading data in '{bz}' for: {all_dates[0]} to {all_dates[-1]}"
                )
                with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                    executor.map(
                        lambda t: self._threading_wrapper(
                            t, checkpoint, checkpoint_path
                        ),
                        [(bz, d) for d in all_dates],
                    )

        except IndexError:
            logger.info(f"Provided years '{self.years}' lie in the future!")

    def _threading_wrapper(
        self, task: tuple[str, str], checkpoint: dict, checkpoint_path: Path
    ) -> None:
        """Threading wrapper for data download and checkpoint reading/saving.

        Args:
            task (tuple): Tuple of date and bidding zone to download data for.
            checkpoint (dict): Dict of 0 and 1 values for resuming.
            checkpoint_path (Path): Path to the checkpoint file for resuming.
        """
        with self._lock:
            if checkpoint.get(task) == 1:
                logger.info(f"{task}: Data already downloaded. Skipping.")
                return

        try:
            status = self._download_day_data(task=task)
        except Exception as e:
            logger.error(f"Unexpected error in thread for {task}: {e}")
            status = 0

        with self._lock:
            checkpoint[task] = status
            self._save_checkpoint(checkpoint, checkpoint_path)

    def _download_day_data(self, task: tuple[str, str]) -> int:
        """Parse data for specific date from Entso-E Platform and dump to CSV.

        Args:
            task (tuple): Tuple of (zone, date) to download data for.

        Returns:
            int: Status of the download (1 if successful, 0 if unsuccessful).
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                df_gen = self._get_day_data(task=task)
                write_df_to_csv(
                    df=df_gen,
                    file_path=Path(self.output_path, task[0], task[1] + ".csv"),
                )
                return 1

            except DataStructureError as e:
                logger.critical(f"FATAL! Data structure has changed: {e}")
                os._exit(1)  # data structure change that warrants entire process kill

            except ValueError as e:
                logger.error(f"Missing data for {task}: {e}")
                return 1  # skip day

            except (ReadTimeoutError, ConnectionError):
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.critical(f"Failed {task} after {MAX_RETRIES} attempts.")
                    return 0

        return 1

    @staticmethod
    def _get_day_data(task: tuple[str, str]) -> pd.DataFrame:
        """Get Entso-e generation data per plant for one specific date and bidding zone.

        Args:
            task (tuple): Tuple of (zone, date) to download data for.

        Returns:
            pd.DataFrame: Dataframe for specific task with the columns
            ['production_type', 'plant_name', 'plant_code', 'quantity', 'unit',
            'timestamp']

        Raises:
            ConnectionError: If Entso-E TP is unavailable or the API did not
            return the requested data (this will cause a retry on the next resume).
            ValueError: If no data is available for the given task (this will cause
            the task to be skipped in future).
            DataStructureError: If data structure has changed and relevant columns
            are missing (this will cause the entire run to be killed).
        """
        zone, date = task
        dt = pd.Period(date, freq="D")

        try:
            result = ActualGenerationPerGenerationUnit(
                period_start=int(dt.strftime("%Y%m%d0000")),  # start of day
                period_end=int(dt.strftime("%Y%m%d2359")),  # end of day
                in_domain=zone,
                psr_type=None,
                registered_resource=None,
            ).query_api()

        except ServiceUnavailableError:
            raise ConnectionError(
                "Entso-E Transparency Platform is currently unavailable!"
            )

        if type(result) is not list:
            raise ConnectionError(f"API call did not return requested data for {task}!")

        if not result:
            raise ValueError(
                f"No data available for {task}! Setting download status to 1."
            )

        records = extract_records(result)  # turns into list of dicts
        records = add_timestamps(records)  # adds key 'timestamp' to each dict
        df = pd.DataFrame(records)

        try:
            # Columns names are made to match those on the Entso-E Transparency Platform
            df = df.loc[:, list(RELEVANT_RECORD_KEYS.keys())].rename(
                columns=RELEVANT_RECORD_KEYS
            )
        except KeyError as e:
            raise DataStructureError(
                f"Entsoe-E structure change detected for {task}! "
                f"Relevant columns are missing: {e}"
            )

        # Drop rows that have no PSR_Type and neither Unit_Name nor Unit_Code values
        df = df.dropna(subset=["PSR_Type"])
        df = df.dropna(subset=["Unit_Name", "Unit_Code"], how="all")

        df = df.sort_values(by=["timestamp", "Unit_Name"], ascending=[True, True])
        return df

    def _load_checkpoint(self, checkpoint_path: Path) -> dict:
        """Load checkpoint from checkpoint path depending on resume logic.

        Args:
            checkpoint_path (Path): Path to checkpoint file.

        Returns:
            dict: Loaded checkpoint.
        """
        if self.resume and checkpoint_path.is_file():
            logger.info(f"Loading checkpoint from '{checkpoint_path}'")

            try:
                with open(checkpoint_path, "rb") as f:
                    return pickle.load(f)
            except (EOFError, pickle.UnpicklingError):
                logger.warning(
                    f"Checkpoint '{checkpoint_path}' is corrupted. Starting fresh."
                )
                return {}
        else:
            logger.info(
                "No checkpoint loading (first run or resume=False). Starting fresh."
            )
            return {}

    @staticmethod
    def _save_checkpoint(checkpoint: dict, checkpoint_path: Path) -> None:
        """Save checkpoint safely (ensure abrupt terminations don't corrupt the file).

        Args:
            checkpoint (dict): Checkpoint to be saved.
            checkpoint_path (Path): Path to checkpoint file.
        """
        temp_path = checkpoint_path.with_suffix(".tmp")
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        with open(temp_path, "wb") as f:
            pickle.dump(checkpoint, f)

        os.replace(temp_path, checkpoint_path)

    def _get_date_list(self) -> list[str]:
        """Get a list of all dates in the provided year(s).

        Includes checks to ensure future years are not evaluated and that if the
        current year is provided, nothing beyond the previous day is taken into account.

        Returns:
            list[str]: List of all dates in the provided years.
        """
        yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).normalize()

        all_dates = []
        for year in self.years:
            year_start = pd.Timestamp(f"{year}-01-01")
            year_end = pd.Timestamp(f"{year}-12-31")

            if year_start > yesterday:  # don't evaluate future years
                continue

            actual_end = min(year_end, yesterday)  # don't evaluate beyond yesterday

            all_dates.extend(
                pd.date_range(start=year_start, end=actual_end)
                .strftime("%Y-%m-%d")
                .tolist()
            )

        return all_dates
