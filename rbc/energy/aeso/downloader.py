"""AESO DATA DOWNLOADER.

Access of AESO site and their zip (CSV) files using zipfile and pandas packages.
"""

import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
from box_sdk_gen import BoxClient, BoxDeveloperTokenAuth, FileBaseTypeField
from loguru import logger

from rbc.energy.utils import (
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    InvalidError,
    MissingDataError,
)

URL_BASE = "https://aeso.app.box.com/s/qofgn9axnnw6uq3ip1goiq2ngb11txe5"
BOXAPI = f"shared_link={URL_BASE}"
ROOT_ID = "196731538687"
FOLDER_ID_DICT = {"1h": "196178549071", "5min": "196706124680"}

MIN_YEAR = 2015
EXPECTED_COLS = [
    "Date (MST)",
    "Date (MPT)",
    "Asset Short Name",
    "Asset Name",
    "Asset Grouping",
    "Volume",
    "Maximum Capability",
    "System Capability",
    "Fuel Type",
    "Sub Fuel Type",
    "Planning Area",
    "Region",
]


class AesoDownloader(EnergyDownloader):
    """AESO data downloader.

    Attributes:
        temporal_resolutions (list[str]): The temporal resolutions to download.
        client (BoxClient): AESO box cloud storage client.
        _source_lookup (dict): Lookup dict of files that can be downloaded from AESO site.
    """

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        temporal_resolutions: list[str],
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            token (str): The personal box cloud storage API developer token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            temporal_resolutions (list[str]): The temporal resolutions to download.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.

        Raises:
            InvalidError: If provided temporal_resolutions are invalid (not 1h &/ 5min).
            ConnectionError: If the AESO box endpoint isn't reachable.
        """
        super().__init__(output_path=output_path, years=years, resume=resume)

        self.temporal_resolutions = temporal_resolutions
        invalid_t_res = set(temporal_resolutions) - set(FOLDER_ID_DICT.keys())
        if invalid_t_res:
            raise InvalidError(
                f"Invalid temporal resolution(s): {sorted(invalid_t_res)}"
            )

        logger.info(
            f"AESO Downloader initialized for:"
            f"\n- years:\t\t{years}"
            f"\n- temporal resolutions:\t{temporal_resolutions}"
        )

        try:
            requests.get(
                f"https://api.box.com/2.0/folders/{ROOT_ID}/items",
                headers={
                    "Authorization": f"Bearer {token}",
                    "boxapi": BOXAPI,
                },
                params={"limit": 1},
                timeout=10,
            ).raise_for_status()

        except (requests.exceptions.HTTPError, requests.exceptions.Timeout) as e:
            logger.error("Initialization AESO connectivity check failed!")
            raise ConnectionError(f"AESO box cloud storage is unreachable: {e}")

        # API setup
        auth = BoxDeveloperTokenAuth(token=token)
        self.client = BoxClient(auth=auth)

        self._source_lookup = self._build_source_lookup()

    def download_data(self) -> None:
        """Parse data for all given years from AESO site and save to CSV."""
        all_months = self._get_month_list()
        tasks = [
            DownloadTask(date=d, temporal_resolution=t_res)
            for t_res in self.temporal_resolutions
            for d in all_months
        ]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get AESO generation data per plant for one specific month.

        AESO provides 5-min (2015 - 2023) and hourly (2015 - now) data on their site.
        All data is stored in zip folders containing a single CSV file.
        The 5-min files are labelled "CSD Generation (5-min) - YYYY-MM.zip".
        The Hourly files are labelled
        - "CSD Generation (hourly) - YYYY-01/07 to YYYY-06/12.zip" until 2025-06
        - "CSD Generation (hourly) - YYYY-MM.zip" from 2025-07 onward.

        Args:
            task (DownloadTask): The metadata of a downloading task,
                here: date (YYYY-MM), temporal_resolution

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns
            ["Date (MST)", "Date (MPT)", "Asset Short Name", "Asset Name", "Asset Grouping",
             "Volume", "Maximum Capability", "System Capability", "Fuel Type", "Sub Fuel Type",
             "Planning Area", "Region"]

        Raises:
            MissingDataError: If a month date was requested for which no data exists or if the
                returned dataframe is empty.
            DataStructureError: If the data structure changed and relevant columns are now
                missing or data is unparsable (this will cause the entire run to be killed).
        """
        task.validate_required_fields("temporal_resolution")

        # find remote item that contains relevant data
        try:
            item = self._source_lookup[task.temporal_resolution][task.date]
        except KeyError:
            raise MissingDataError(
                "No AESO data that matches requested task! Skipping..."
            )

        # load remote data into dataframe (using id and name because dict can't be cached!)
        df = self._load_zip(item_id=item["id"], item_name=item["name"])

        if df.empty:
            raise MissingDataError("No energy data available! Skipping...")

        missing_cols = [c for c in EXPECTED_COLS if c not in df.columns]
        if missing_cols:
            raise DataStructureError(
                f"AESO file structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        # slice relevant month excerpt from dataframe (some files cover multiple months!)
        date_col = pd.to_datetime(df["Date (MPT)"], errors="coerce")  # AESO uses MPT!
        if date_col.isna().any():
            raise DataStructureError(
                f"AESO file structure change detected for '{task.identifier}'! "
                f"'Date (MPT)' contains unparsable values."
            )

        df = df.loc[date_col.dt.to_period("M") == pd.Period(task.date, freq="M")].copy()

        if df.empty:
            raise MissingDataError("No energy data after month filter! Skipping...")

        df = df.sort_values(
            by=["Date (MST)", "Date (MPT)", "Asset Name"], ignore_index=True
        )
        return df

    @lru_cache(maxsize=8)
    def _load_zip(self, item_id: str, item_name: str) -> pd.DataFrame:
        """Downloads the CSV contained in the zip file into a df once.

        Decorator lru_cache enables download and storage in cache of a file once, that can
        be used over

        Args:
            item_id: Specific ID of item in URL to download.
            item_name: Specific name of item in URL to download.

        Returns:
            pd.DataFrame: Dataframe for the desired source file.

        Raises:
            DataStructureError: If remote downloaded data does not have capacity values.
        """
        file_stream = self.client.downloads.download_file(item_id, boxapi=BOXAPI)
        file_bytes = file_stream.read()

        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            file_names = z.namelist()
            if len(file_names) != 1:
                raise DataStructureError(
                    f"AESO file structure change detected in file '{item_name}': "
                    f"expected exactly one file in ZIP, found {file_names}"
                )

            csv_name = file_names[0]
            if not csv_name.lower().endswith(".csv"):
                raise DataStructureError(
                    f"AESO file structure change detected in file '{item_name}': "
                    f"expected CSV, found {csv_name}"
                )

            with z.open(csv_name) as f:
                return pd.read_csv(f)

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    def _build_source_lookup(self) -> dict[str, dict]:
        """Build lookup table from AESO box site of all relevant files that can be downloaded.

        Returns:
            dict: Lookup dict {<t_res>: {YYYY-MM: {"id": <id>, "name": <name>}}, ...}

        Raises:
            DataStructureError: If downloaded data does not have capacity values.
        """
        lookup: dict = {t_res: {} for t_res in self.temporal_resolutions}

        for t_res in self.temporal_resolutions:
            limit = 1000  # max allowed by box
            offset = 0

            while True:
                items = self.client.folders.get_folder_items(
                    FOLDER_ID_DICT[t_res], boxapi=BOXAPI, limit=limit, offset=offset
                )

                for item in items.entries:
                    if item.type == FileBaseTypeField.FILE:
                        item_dates = re.findall(r"\d{4}-\d{2}(?=[^0-9])", item.name)

                        if len(item_dates) == 1:
                            lookup[t_res][item_dates[0]] = {
                                "id": item.id,
                                "name": item.name,
                            }

                        elif len(item_dates) == 2:
                            date_range = pd.date_range(
                                start=item_dates[0], end=item_dates[1], freq="MS"
                            )
                            for date in date_range.strftime("%Y-%m"):
                                lookup[t_res][date] = {"id": item.id, "name": item.name}

                        else:
                            raise DataStructureError(
                                f"AESO file structure change detected in file '{item.name}'! "
                                f"Naming convention changed, date search returns {item_dates}"
                            )

                offset += len(items.entries)

                if offset >= items.total_count:
                    break

            if not lookup[t_res]:
                raise DataStructureError(
                    f"AESO file structure change detected! "
                    f"No data for temporal resolution: {t_res}"
                )

        return lookup
