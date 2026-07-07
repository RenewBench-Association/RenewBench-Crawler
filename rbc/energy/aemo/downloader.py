"""AEMO DATA DOWNLOADER.

Remote API access of AEMO (OpenElectricity) Platform using the openelectricity-python package.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import pandas as pd
import requests
from loguru import logger
from openelectricity import AsyncOEClient, DataMetric, OEClient
from openelectricity.client import APIError
from openelectricity.models.facilities import FacilityResponse

from rbc.energy.utils import (
    ASYNC_WORKERS,
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    InvalidError,
    MissingDataError,
)

logging.getLogger("openelectricity").setLevel(logging.CRITICAL)

MIN_YEAR = 1998  # start in December
VALID_NETWORKS = {
    "NEM": timezone(timedelta(hours=10)),
    "WEM": timezone(timedelta(hours=8)),
    "AU": timezone(timedelta(hours=10)),
}
# For more information on Australian timezones, s.
# https://docs.openelectricity.org.au/sdk/typescript/utilities#date-and-time-utilities
EXPECTED_COLS = [
    "timestamp",
    "code",
    "name",
    "network_id",
    "network_region",
    "description",
    "location",
    "unit_code",
    "unit_fueltech_id",
    "unit_status_id",
    "unit_dispatch_type",
    "unit_capacity_registered",
    "unit_capacity_maximum",
    "unit_capacity_storage",
    "unit_data_first_seen",
    "unit_data_last_seen",
    "unit_commencement_date",
    "value",
]


class AemoDownloader(EnergyDownloader):
    """AEMO data downloader.

    Attributes:
        token (str): The personal OpenElectricity API token.
        client (OEClient): OEClient object for AEMO (OpenElectricity) data access.
        df_fu (pd.DataFrame): Dataframe containing information on all units.
        lookup_u (dict): Lookup dict for unit start dates.
        valid_u (list): List of valid AEMO units for the given time frame.
    """

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        temporal_resolutions: list[str],
        resume: bool = True,
    ):
        """Initializes the instance.

        Args:
            token (str): The personal OpenElectricity API token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            temporal_resolutions (list[str]): The temporal resolutions to download.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.

        Raises:
            InvalidError: If provided temporal_resolutions are invalid (not 1h &/ 5min) or if
                login credentials are incorrect.
        """
        super().__init__(
            output_path=output_path, years=years, start_year=MIN_YEAR, resume=resume
        )
        self.temporal_resolutions = temporal_resolutions

        invalid_t_res = set(temporal_resolutions) - {"1h", "5min"}
        if invalid_t_res:
            raise InvalidError(
                f"Invalid temporal resolution(s): {sorted(invalid_t_res)}"
            )

        # API setup
        self.token = token
        self.client = OEClient(api_key=token)
        try:
            self.client.get_current_user()
        except APIError as e:
            raise InvalidError(f"AEMO (OpenElectricity) connection failed: {e}") from e

        logger.info(
            f"AEMO (OpenElectricity) Downloader initialized for:\n- years:\t\t{years}"
        )

        # get dataframe of existing facilities & units and lookup dict for start dates
        self.df_fu, self.lookup_u = self._get_facilities_and_units()

        # pre-filter units to only those that generate data in the requested year(s)
        unique_u = self.df_fu["unit_code"].unique()
        self.valid_u = self._get_valid_units(
            units=unique_u, year=max(years), verbose=True
        )

    def download_data(self) -> None:
        """Parse data for all given years from AEMO (OpenElectricity) and save to CSV."""
        # download per month for "1h", per day for anything else (i.e. "5min")
        tasks = [
            DownloadTask(date=d, temporal_resolution=t_res)
            for t_res in self.temporal_resolutions
            for d in (
                self._get_month_list() if t_res == "1h" else self._get_date_list()
            )
        ]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get AEMO (OpenElectricity) generation data per plant for one specific date.

        AEMO follows an End-of-Interval timestamp convention, meaning values for an hour
        are saved on the dot of the next hour (i.e. "01:00" = data from 0-1 AM, not 1-2 AM).
        This means for each day, data starts with hour 1 of Day 1 and hour 0 of Day 2
        (i.e. start = "2018-01-01T01:00", end = "2018-01-02T00:00"). Analogous for 5 min data.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)

        Returns:
            df_fu (pd.DataFrame): Dataframe of units for specific date.

        Raises:
            MissingDataError: If no generation data exists.
            DataStructureError: If the data structure changed and relevant columns are now
                missing (this will cause the entire run to be killed).
        """
        t_res = task.temporal_resolution
        t_res = t_res if "min" not in t_res else t_res.replace("min", "m")

        start = task.dt.to_pydatetime()
        start = start.replace(second=1)  # to ensure end-of-interval timeframe

        task_type = "month" if t_res == "1h" else "day"
        if task_type == "month":
            end = (start + pd.offsets.MonthBegin(1)).to_pydatetime()
        else:
            end = start + timedelta(days=1)

        # filter list of units further based on current task
        valid_u = self._get_valid_units(units=self.valid_u, year=task.year)

        async def fetch_task_data() -> list:
            """Fetch all data for a task (date, t_res) using an async (parallel) client.

            This is implemented as a nested function to forgo unnecessary argument definition
            (it requires parameters defined in the main method, e.g. start, end, t_res).

            Returns:
                list: List of data from all units for a given task (date, t_res)
            """
            async with AsyncOEClient(api_key=self.token) as a_client:
                semaphore = asyncio.Semaphore(
                    ASYNC_WORKERS
                )  # few to work with threading
                coroutines = []

                # get data for 1 unit at a time because results are otherwise aggregated
                for unit in valid_u:
                    coroutines.append(
                        self._fetch_unit_data_async(
                            a_client,
                            semaphore,
                            network_code=self.lookup_u[unit]["network_id"],
                            unit_code=unit,
                            date_start=start,
                            date_end=end,
                            temporal_res=t_res,
                        )
                    )

                results = await asyncio.gather(*coroutines)

                logger.info(
                    f"Task {task.identifier}: {sum(1 for r in results if r)} / {len(results)}"
                    f" units with data"
                )
                return [item for sublist in results for item in sublist]

        # get results
        data = asyncio.run(fetch_task_data())

        if not data:
            raise MissingDataError("No generation data!")

        # define dataframe to be saved
        df_api = pd.DataFrame(data)
        try:
            df = pd.merge(self.df_fu, df_api, on=["unit_code"])
            df = df[EXPECTED_COLS].sort_values(by=["timestamp"])
        except KeyError as e:
            raise DataStructureError(
                f"AEMO (OpenElectricity) structure change detected! Relevant column(s) "
                f"missing from facilities and units data: {e}"
            )

        return df

    @staticmethod
    async def _fetch_unit_data_async(
        async_client: AsyncOEClient,
        semaphore: asyncio.Semaphore,
        network_code: str,
        unit_code: str,
        date_start: datetime,
        date_end: datetime,
        temporal_res: str,
    ) -> list[dict]:
        """Fetch data for one specific unit at a time, within the realm of the given task.

        The OpenElectricity API offers the download of DataMetric.ENERGY and DataMetric.POWER
        data, where POWER [MW] is the instantenous output at a specific point in time and
        ENERGY [MWh] is the average of power generated during a given interval and the
        previous interval (s. https://docs.openelectricity.org.au/guides/energy).
        All data is based on the 5-min interval values, i.e. 1h values are aggregated from
        that.

        Args:
            async_client (AsyncOEClient): AsyncOEClient object from OpenElectricity API.
            semaphore (asyncio.Semaphore): Asyncio parallelization lock.
            network_code (str): Network code.
            unit_code (str): Unit code.
            date_start (datetime): Start of timeframe to fetch data for.
            date_end (datetime): End of timeframe to fetch data from.
            temporal_res (str): Temporal resolution to fetch data for.

        Returns:
            list: List of all unit data for the task in dict form or empty, if none exists.

        Raises:
            HTTPError: If unit data exists but an error occurred during fetching.
        """
        async with semaphore:
            try:
                response = await async_client.get_facility_data(
                    network_code=network_code,
                    unit_code=unit_code,
                    metrics=[DataMetric.ENERGY],
                    interval=temporal_res,
                    date_start=date_start,
                    date_end=date_end,
                )
                # map the nested response back to a flat list of dicts
                logger.debug(f"Energy data found for unit {unit_code}")
                return [
                    {"timestamp": d.root[0], "unit_code": unit_code, "value": d.root[1]}
                    for s in response.data
                    for result in s.results
                    for d in result.data
                ]

            except APIError as e:  # openelectricity-package error that will be raised
                status_code = e.status_code
                detail = e.detail

                if status_code == 404:  # when data is permanently missing (404), skip!
                    logger.debug(
                        f"No energy data for unit {unit_code}. Skipping..."
                    )  # don't raise error here or loop will be interrupted
                    return []

                response = requests.Response()
                response.status_code = status_code
                response.reason = detail

                raise requests.exceptions.HTTPError(
                    f"Error {status_code} retrieving {unit_code} data with "
                    f"the OpenElectricity API: {detail}",
                    response=response,
                )

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    def _get_facilities_and_units(self) -> tuple[pd.DataFrame, dict]:
        """Get dataframe of all facilities and units and lookup dict for start dates.

        This method requests data of all existing energy generation facilities, given as:
        ['code', 'name', 'network_id', 'network_region', 'description', 'npi_id',
         'location', 'units', 'created_at', 'updated_at']
        Information on any units these facilities have is stored under the 'units' header:
        ['code', 'fueltech_id', 'status_id', 'capacity_registered', 'capacity_maximum',
         'capacity_storage', 'emissions_factor_co2', 'data_first_seen', 'data_last_seen',
         'dispatch_type', 'commencement_date', 'commencement_date_specificity',
         'commencement_date_display', 'closure_date', 'closure_date_specificity',
         'closure_date_display', 'expected_operation_date', 'expected_operation_date_specificity',
         'expected_operation_date_display', 'expected_closure_date',
         'expected_closure_date_specificity', 'expected_closure_date_display',
         'construction_start_date', 'construction_start_date_specificity',
         'construction_start_date_display', 'project_approval_date',
         'project_approval_date_specificity', 'project_approval_date_display',
         'project_lodgement_date', 'created_at', 'updated_at']
        All columns are combined into one df by adding the prefix 'unit' to the unit data.
        The lookup dictionary is generated from this dataframe to have the keys:
        ["code", "network_id", "unit_code", "start"]

        Returns:
            df_fu (pd.Dataframe): Dataframe of units with their associated facility data.
            lookup_u (dict): Dict of all units and their start date.

        Raises:
            DataStructureError: If the API facilities data no longer contains content that
                can be postprocessed, no data was downloaded, or relevant columns are missing.
        """
        facilities: FacilityResponse = self.client.get_facilities(
            network_id=list(VALID_NETWORKS)
        )

        try:
            data: list[dict] = [f.model_dump() for f in facilities.data]
            df_f = pd.DataFrame(data)

        except (AttributeError, ValueError) as e:
            raise DataStructureError(
                f"AEMO (OpenElectricity) structure change detected! Facility data no "
                f"longer contains 'data' object that can be transformed into a df: {e}"
            )

        # check if data or created dataframe are empty (no data was downloaded)
        if not data or df_f.empty:
            raise DataStructureError(
                "AEMO (OpenElectricity) structure change detected! No facilities / units "
                "data was downloaded."
            )

        # create merged dataframe and lookup dictionary
        try:
            df_f = df_f.drop(columns=["units"])
            df_f["description"] = df_f["description"].str.replace(
                r"<[^>]*>", "", regex=True
            )

            # build a dataframe of units including their facilities information
            df_u = pd.json_normalize(
                data,
                record_path=["units"],
                meta=["code", "name", "network_region"],
                record_prefix="unit_",
            )
            df_fu = pd.merge(df_f, df_u, on=["code", "name", "network_region"])

            # build a lookup dict with start dates for all rows (units)
            df_lookup = df_fu.copy()
            df_lookup["start"] = df_lookup.apply(
                lambda r: _get_start_date(
                    d1=r["unit_data_first_seen"],
                    d2=r["unit_commencement_date"],
                    network_id=r["network_id"],
                ),
                axis=1,
            )
            df_lookup = df_lookup[["code", "network_id", "unit_code", "start"]]

            lookup_u = df_lookup.set_index("unit_code")[
                ["network_id", "start"]
            ].to_dict("index")

        except (KeyError, ValueError) as e:
            raise DataStructureError(
                f"AEMO (OpenElectricity) structure change detected! Relevant column missing "
                f"from facility and units data: {e}"
            )

        return df_fu, lookup_u

    def _get_valid_units(self, units: list, year: int, verbose: bool = False) -> list:
        """Get a list of units that are valid based on start date.

        Args:
            units (list): List of all units as basis for getting valid ones.
            year (int, optional): Year to compare to start time.
            verbose (bool, optional): Whether to log verbosely (i.e. skipped units) or not.
                Defaults to False.

        Returns:
            list: List of valid units.
        """
        valid_units = [u for u in units if self.lookup_u[u]["start"].year <= year]

        diff = set(units) - set(valid_units)
        if len(diff) > 0:
            logger.warning(
                f"No energy data for {len(diff)} out of {len(units)} units "
                f"(not yet generating in {year})."
            )
            if verbose:
                logger.warning(f"Skipping:\n{diff}")
        else:
            if verbose:
                logger.info(f"All {len(units)} units are producing energy data.")

        return valid_units


def _get_start_date(
    d1: datetime | None, d2: datetime | None, network_id: str
) -> datetime:
    """Define (buffered) start date using d1, d2 or MIN_YEAR depending on which is not None.

    In this case, d1 is the "data_first_seen" date and d2 is the "commencement_date". The
    assumption here is that the "data_first_seen" date is what we're actually looking for,
    but since that is sometimes None, the fallback is d2, or even the MIN_YEAR value.

    Args:
        d1 (datetime | None): first datetime object (or None)
        d2 (datetime | None): second datetime object (or None)
        network_id (str): Network ID used to identify the row's timezone info.

    Returns:
        datetime: unit's start date

    Raises:
        InvalidError: If provided network_id is not valid (not defined in VALID_NETWORKS).
    """
    try:
        row_tz: tzinfo = VALID_NETWORKS[network_id]
    except KeyError as e:
        raise InvalidError(f"Invalid network ID provided: {e}")

    start_date = (
        d1
        if isinstance(d1, datetime)
        else d2
        if isinstance(d2, datetime)
        else (datetime(MIN_YEAR, 1, 1, tzinfo=row_tz))
    )
    buffered_start_date = start_date.replace(month=1, day=1, hour=0, minute=0, second=0)
    return buffered_start_date
