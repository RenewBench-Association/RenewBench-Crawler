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
from entsoe.utils import add_timestamps, extract_records, mappings
from loguru import logger

from rbc.energy.utils import (
    WORKERS,
    DataStructureError,
    DownloadKey,
    EnergyDownloader,
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
        bidding_zones: list[str] = mappings.keys(),
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
            ValueError: If bidding zone is unsupported or token is invalid.
        """
        super().__init__(output_path=output_path, years=years, resume=resume)
        self.bidding_zones = list(bidding_zones)

        for bz in self.bidding_zones:
            if bz not in list(mappings.keys()):
                raise ValueError(f"Bidding zone '{bz}' is not supported.")

        logger.info(
            f"Entsoe-E Downloader initialized for:"
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

        for bz in self.bidding_zones:
            checkpoint_path = self._build_checkpoint_path(
                task=DownloadKey(bidding_zone=bz)
            )
            checkpoint = self._load_checkpoint(checkpoint_path)

            tasks = [DownloadKey(date=d, bidding_zone=bz) for d in all_dates]

            logger.info(f"Downloading data for tasks:\n{tasks[0]} to {tasks[-1]}")
            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                executor.map(
                    lambda t: self._threading_wrapper(t, checkpoint, checkpoint_path),
                    tasks,
                )

    def _get_task_data(self, task: DownloadKey) -> pd.DataFrame:  # type: ignore[override]
        """Get Entso-e generation data per plant for one specific date and bidding zone.

        Args:
            task (DownloadKey): The metadata of a downloading task,
                here: date (YYYY-MM-DD), bidding_zone

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
        task.validate_required_fields("date", "bidding_zone")
        dt = pd.Period(task.date, freq="D")

        try:
            result = ActualGenerationPerGenerationUnit(
                period_start=int(dt.strftime("%Y%m%d0000")),  # start of day
                period_end=int(dt.strftime("%Y%m%d2359")),  # end of day
                in_domain=task.bidding_zone,
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

    def _save_task_data(self, task: DownloadKey, df: pd.DataFrame) -> None:
        """Save ENTSO-E downloaded task data to disk, splitting by temporal resolution.

        The API does not allow temporal resolution arguments, but ENTSO-E data has varying
        resolutions. The df is grouped by t_res and subsets are written to the correct folder.

        Args:
            task (DownloadKey): The metadata for the task that was downloaded.
            df (pd.DataFrame): Downloaded dataframe for the task.

        Raises:
            DataStructureError: If columns are missing temporal resolution values
        """
        df_full = df.dropna(subset=["Temporal_Resolution"])
        if df.all().all() != df_full.all().all():
            logger.warning(
                "Some rows are missing temporal resolution values! Skipping."
            )

        for t_res, df_t_res in df.groupby("Temporal_Resolution", sort=True):
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
