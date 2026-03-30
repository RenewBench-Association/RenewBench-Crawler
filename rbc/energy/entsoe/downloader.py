"""ENTSOE-E DATA DOWNLOADER.

Remote API access of ENTSO-E Platform using the entsoe-apy package.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from entsoe.config import get_config, set_config
from entsoe.Generation import ActualGenerationPerGenerationUnit
from entsoe.query.decorators import ServiceUnavailableError
from entsoe.utils import add_timestamps, extract_records
from loguru import logger

from rbc.energy.entsoe.mappings import ACTIVE_ZONES, ACTIVE_ZONES_METADATA
from rbc.energy.utils import (
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    InvalidError,
    MissingDataError,
    write_df_to_csv,
)

EXPECTED_COLS_MAPPING = {
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


class EntsoeDownloader(EnergyDownloader):
    """Entsoe-E data downloader.

    Attributes:
        bidding_zones (list[str]): List of bidding zones to get data for.
    """

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        bidding_zones: list[str] = ACTIVE_ZONES,
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            token (str): The personal ENTSO-E RESTful API token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            bidding_zones (list[str]): List of bidding zones to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.

        Raises:
            InvalidError: If bidding zone is unsupported or token is invalid.
        """
        super().__init__(output_path=output_path, years=years, resume=resume)
        self.bidding_zones = list(bidding_zones)

        for bz in self.bidding_zones:
            if bz not in ACTIVE_ZONES:
                raise InvalidError(f"Bidding zone '{bz}' is not supported.")

        logger.info(
            f"Entsoe-E Downloader initialized for:"
            f"\n- bidding zones:\t{bidding_zones}"
            f"\n- years:\t\t{years}"
        )

        set_config(security_token=token)
        if get_config().security_token is None:
            raise InvalidError(
                f"Entsoe-apy failed to successfully configure token '{token}'!"
            )

    def download_data(self) -> None:
        """Parse data for all given years and zones from ENTSO-E Platform and save to CSV."""
        all_dates = self._get_date_list()
        tasks = [
            DownloadTask(date=d, bidding_zone=bz)
            for bz in self.bidding_zones
            for d in all_dates
        ]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get Entso-e generation data per plant for one specific date and bidding zone.

        Args:
            task (DownloadTask): The metadata of a downloading task,
                here: date (YYYY-MM-DD), bidding_zone

        Returns:
            pd.DataFrame: Dataframe for specific task with the columns
            ['production_type', 'plant_name', 'plant_code', 'quantity', 'unit',
            'timestamp']

        Raises:
            ConnectionError: If Entso-E TP is unavailable or the API did not
                return the requested data (this will cause a retry on the next resume).
            MissingDataError: If no data is available for the given task (this will cause
                the task to be skipped in future).
            DataStructureError: If the data structure changed and relevant columns are now
                missing (this will cause the entire run to be killed).
        """
        task.validate_required_fields("bidding_zone")

        bz_start = int(ACTIVE_ZONES_METADATA[str(task.bidding_zone)]["start"])
        if task.year < bz_start:
            raise MissingDataError(
                f"No energy data for year {task.year} (it's before {bz_start}). Skipping..."
            )

        try:
            result = ActualGenerationPerGenerationUnit(
                period_start=int(task.dt.strftime("%Y%m%d0000")),  # start of day
                period_end=int(task.dt.strftime("%Y%m%d2359")),  # end of day
                in_domain=task.bidding_zone,
                psr_type=None,
                registered_resource=None,
            ).query_api()

        except ServiceUnavailableError:
            raise ConnectionError("Entso-E Transparency Platform is unavailable!")

        if not isinstance(result, list):
            raise ConnectionError("API call did not return requested data!")

        if not result:
            raise MissingDataError("No energy data available! Skipping...")

        records = extract_records(result)  # turns into list of dicts
        records = add_timestamps(records)  # adds key 'timestamp' to each dict
        df = pd.DataFrame(records)

        try:
            # Columns names are made to match those on the Entso-E Transparency Platform
            df = df.loc[:, list(EXPECTED_COLS_MAPPING.keys())].rename(
                columns=EXPECTED_COLS_MAPPING
            )
        except KeyError as e:
            raise DataStructureError(
                f"Entsoe-E structure change detected for '{task.identifier}'! "
                f"Relevant columns are missing: {e}"
            )

        # Drop rows that have no PSR_Type and neither Unit_Name nor Unit_Code values
        df = df.dropna(subset=["PSR_Type"])
        df = df.dropna(subset=["Unit_Name", "Unit_Code"], how="all")

        df = df.sort_values(by=["timestamp", "Unit_Name"], ascending=[True, True])
        return df

    def _save_task_data(self, task: DownloadTask, df: pd.DataFrame) -> None:
        """Save ENTSO-E downloaded task data to disk, splitting by temporal resolution.

        The API does not allow temporal resolution arguments, but ENTSO-E data has varying
        resolutions. The df is grouped by t_res and subsets are written to the correct folder.

        Args:
            task (DownloadTask): The metadata for the task that was downloaded.
            df (pd.DataFrame): Downloaded dataframe for the task.
        """
        df_full = df.dropna(subset=["Temporal_Resolution"])
        if len(df_full) != len(df):
            logger.warning(
                "Some rows are missing temporal resolution values! Removing those rows."
            )

        for t_res, df_t_res in df_full.groupby("Temporal_Resolution", sort=True):
            updated_task = task.update(
                temporal_resolution=self._normalize_temporal_resolution(str(t_res))
            )
            file_path = self._build_task_path(updated_task)
            write_df_to_csv(df=df_t_res, file_path=file_path)

    @staticmethod
    def _normalize_temporal_resolution(t_res: str) -> str:
        """Convert ENTSO-E ISO-like temporal resolution string to name, i.e. PT60M -> 1h.

        Args:
            t_res (str): Temporal resolution string as defined in ENTSO-E (i.e. PT60M).

        Returns:
            Normalized temporal resolution name.

        Raises:
            DataStructureError: If the resolution format is unknown.
        """
        if match := re.search(r"^PT(\d+)M$", t_res):
            minutes = int(match.group(1))
            return "1h" if minutes == 60 else f"{minutes}min"

        raise DataStructureError(f"Unknown ENTSO-E temporal resolution '{t_res}'")
