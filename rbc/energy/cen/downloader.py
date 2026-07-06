"""CEN DATA DOWNLOADER.

Access CEN API using the requests package.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from loguru import logger
from requests import exceptions

from rbc.energy.utils import (
    MAX_RETRIES,
    RATE_LIMIT_RETRY_DELAY,
    WORKERS,
    DataStructureError,
    DownloadTask,
    EnergyDownloader,
    MissingDataError,
)

URL_ROOT = "https://sipub.api.coordinador.cl/"
URL_BASE = "https://sipub.api.coordinador.cl/generacion-real/v3/findByDate"

MIN_YEAR = 2000
EXPECTED_COLS = [
    "id_opreal",
    "llave_opreal",
    "id_central",
    "central",
    "gen_real_mw",
    "fecha_hora",
    "hora",
    "potencia_maxima",
    "id_propietario",
    "propietario",
    "id_coordinado",
    "coordinado",
    "tipo_tecnologia",
    "subtipo_tecnologia",
    "factor_ernc",
    "alcance",
    "valor_ernc",
]


class CenDownloader(EnergyDownloader):
    """CEN data downloader."""

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        resume: bool = True,
    ):
        """Initializes the instance.

        Args:
            token (str): The CEN API token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            resume (bool, optional): Whether to resume from a previous download (True)
                or start from scratch (False). Defaults to True.
        """
        super().__init__(
            output_path=output_path, years=years, start_year=MIN_YEAR, resume=resume
        )
        self.token = token

        init_params: dict[str, str | int] = {
            "startDate": f"{self.years[0]}-01-01",
            "endDate": f"{self.years[0]}-01-01",
            "user_key": self.token,
            "pageSize": 1,
            "page": 1,
        }
        self._check_connection(
            lambda: requests.get(
                URL_BASE,  # API has no status / health endpoint so use the task one
                params=init_params,  # make request as small as possible for very basic check
                timeout=10,
            ),
            "CEN",
        )

        logger.info(f"CEN Downloader initialized for:\n- years:\t\t{years}")

    def download_data(self) -> None:
        """Parse data for all given years from CEN site and save to CSV."""
        tasks = [DownloadTask(date=d) for d in self._get_date_list()]

        logger.info(
            f"Downloading tasks: {tasks[0].identifier} --- {tasks[-1].identifier}"
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            executor.map(self._threading_wrapper, tasks)

    def _get_task_data(self, task: DownloadTask) -> pd.DataFrame:  # type: ignore[override]
        """Get CEN generation data per plant for one specific date.

        The parsing cap depends on the amount of data available for the day - 10,000 seems
        work consistently. The amount of hourly data per generation source for a single day
        (~40,000 rows/day) exceeds that, which is why the data is acquired in batches.
        Given the large amount of data, the choice is made here to store a file per day
        instead of per month/year.
        NOTE: The data (pre-2026) can also be found in variously formatted Excel files at:
        https://www.coordinador.cl/reportes-y-estadisticas/#Estadisticas
        However, since these change formats and the API allows access to all data,
        this approach is selected.

        Args:
            task (DownloadTask): The metadata of a downloading task, here: date (YYYY-MM-DD)

        Returns:
            pd.DataFrame: Dataframe for specific date with the columns
            ['id_opreal', 'llave_opreal', 'id_central', 'central', 'gen_real_mw',
             'fecha_hora', 'hora', 'potencia_maxima', 'id_propietario',
             'propietario', 'id_coordinado', 'coordinado', 'tipo_tecnologia',
             'subtipo_tecnologia', 'factor_ernc', 'alcance', 'valor_ernc']

        Raises:
            ConnectionError/Timeout: If API issue occurred with connection or timeout or if
                not all available data was downloaded.
            HTTPError: If request response is not 200, if the response is 500 (internal
                error) despite reducing the page size number several times or if the API
                rate limit has been reached and the full task requires retrying.
            MissingDataError: If the requested data is an empty list or the loaded df empty.
            DataStructureError: If the CEN structure changed causing response parsing fail or
                relevant columns to be missed (this will cause the entire run to be killed).
        """
        params: dict[str, str | int] = {
            "startDate": f"{task.date}",
            "endDate": f"{task.date}",
            "user_key": self.token,
            "pageSize": 10000,
            "page": 1,
        }

        all_data: list = []
        attempt_network = 0
        attempt_ratelimit = 0
        attempt_pagesize = 0

        while True:
            try:
                response = requests.get(URL_BASE, params=params, timeout=60)
                status_code = response.status_code
                attempt_network = 0

            except exceptions.RequestException as e:
                # catch ALL requests errors locally (prevents crashing of parent thread!)
                if attempt_network < MAX_RETRIES:  # retry 3 times
                    attempt_network += 1
                    logger.warning(
                        f"Network issue for {task.date} (Page {params['page']}): "
                        f"{type(e).__name__}. Retrying page request in 5 seconds..."
                    )
                    time.sleep(5)
                    continue
                else:
                    raise type(e)(
                        f"Network retries exceeded by CenDownloader for {task.date} (Page "
                        f"{params['page']}). Bubbling up to parent EnergyDownloader! {e}"
                    ) from e  # reraise for parent to catch!

            if status_code != 200:
                if status_code == 429:
                    if attempt_ratelimit < MAX_RETRIES:  # retry 3 times
                        attempt_ratelimit += 1
                        logger.warning(
                            f"CEN API rate limit reached (429) on page {params['page']}. "
                            f"Sleeping {RATE_LIMIT_RETRY_DELAY} seconds..."
                        )
                        time.sleep(RATE_LIMIT_RETRY_DELAY)
                        continue
                    else:
                        raise exceptions.HTTPError(
                            f"CEN API rate limit (429) persists for {task.date}: "
                            f"{response.text[:200]}. Propagating for further handling...",
                            response=response,
                        )

                if status_code == 500:
                    if attempt_pagesize < 3:
                        attempt_pagesize += 1
                        logger.warning(
                            "Server overload (too much data requested at once). Halving "
                            "page size and restarting date task..."
                        )
                        params["pageSize"] = int(int(params["pageSize"]) / 2)
                        params["page"] = 1  # reset back to the beginning!
                        all_data = []  # clear already accumulated data so no duplicates
                        continue
                    else:
                        raise exceptions.HTTPError(
                            f"API request failed (despite page size reduction to "
                            f"{params['pageSize']}): {status_code} - {response.text}"
                        )

                raise exceptions.HTTPError(
                    f"API request failed: {status_code} - {response.text}",
                    response=response,
                )

            try:
                dict_body = response.json()
                data = dict_body["data"]  # list of data

                total_pages = dict_body["totalPages"]  # total pages for date
                current_page = dict_body["page"]  # current page

                if data == [] and total_pages == 0:
                    raise MissingDataError("No energy data available! Skipping...")

                all_data.extend(data)

            except (exceptions.JSONDecodeError, KeyError, ValueError) as e:
                raise DataStructureError(
                    f"CEN structure change detected for '{task.identifier}'! "
                    f"Failed parsing of data from {URL_BASE} with parameters {params}: "
                    f"{type(e).__name__}!"
                )

            # Stop if last page has been reached
            if current_page == total_pages:
                break

            params["page"] = current_page + 1
            time.sleep(0.1)

        # Check if created dataframe is as expected
        df_gen = pd.DataFrame(all_data)
        if df_gen.empty:
            raise MissingDataError("No energy data available! Skipping...")

        missing_cols = [c for c in EXPECTED_COLS if c not in df_gen.columns]
        if missing_cols:
            raise DataStructureError(
                f"CEN structure change detected for '{task.identifier}'! "
                f"Missing columns: {missing_cols}"
            )

        df_gen = df_gen.sort_values(["fecha_hora", "central"], ignore_index=True)
        return df_gen
