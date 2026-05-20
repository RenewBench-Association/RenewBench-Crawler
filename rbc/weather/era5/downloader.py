"""ERA5 REANALYSIS DATA DOWNLOADER.

Remote API access of ERA5 reanalysis data using the cdsapi package.
"""

from calendar import monthrange
from pathlib import Path
from typing import Any

import cdsapi  # type: ignore[import-untyped]
import requests
from loguru import logger

from rbc.weather.era5.mappings import (
    ALL_MODEL_LEVEL_VARIABLES,
    ALL_MODEL_LEVELS,
    ALL_PRESSURE_LEVEL_VARIABLES,
    ALL_PRESSURE_LEVELS,
    ALL_SINGLE_LEVEL_VARIABLES,
    DEFAULT_MODEL_LEVELS,
    DEFAULT_PRESSURE_LEVELS,
    DEFAULT_VARIABLES,
    MODEL_CONFIG,
    VARIABLE_TO_MARS_PARAM,
)
from rbc.weather.utils import WeatherDownloader


class Era5Downloader(WeatherDownloader):
    """ERA5 reanalysis data downloader.

    Attributes:
        area (list[float] | None): Bounding box [North, West, South, East] in degrees. None for world (all).
        client (cdsapi.Client): CDS API client for retrieving data.
        model_config (dict): Model-specific configuration from MODEL_CONFIG.
        model_levels (list[str] | None): List of model levels to download (for 3D variables).
        pressure_levels (list[str] | None): List of pressure levels to download (for 3D variables).
    """

    def __init__(
        self,
        api_key: str,
        output_path: Path,
        years: list[int],
        months: list[str] | None = None,
        variables: list[str] | None = None,
        area: list[float] | None = None,
        pressure_levels: list[str] | None = None,
        model_levels: list[str] | None = None,
        dry_run: bool = False,
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            api_key (str): The CDS API key.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            months (list[str] | None, optional): List of months (01-12).
                If None, defaults to all months.
            variables (list[str] | None, optional): List of ERA5 variables.
                If None, defaults to DEFAULT_VARIABLES.
            area (list[float] | None, optional): Bounding box [N, W, S, E].
                If None, defaults to global.
            pressure_levels (list[str] | None, optional): Pressure levels (hPa).
                If None, defaults to DEFAULT_PRESSURE_LEVELS.
            model_levels (list[str] | None, optional): Model levels (1-137).
                If None, defaults to DEFAULT_MODEL_LEVELS.
            dry_run (bool, optional): If True, print requests without submitting them.
                Defaults to False.
            resume (bool, optional): Whether to resume from a previous download.
                Defaults to True.

        Raises:
            ValueError: If API credentials are invalid.
            ConnectionError: If the CDS API endpoint is unreachable.
        """
        self.model_config = MODEL_CONFIG
        self.area = area  # If None, API downloads global data (area parameter omitted from request)

        # Determine which level types to download
        # If both are None, default to pressure levels
        if pressure_levels is None and model_levels is None:
            self.pressure_levels: list[str] | None = DEFAULT_PRESSURE_LEVELS
            self.model_levels: list[str] | None = None
        else:
            # Use default levels if specified as empty but not None
            self.pressure_levels = pressure_levels
            if self.pressure_levels is not None and len(self.pressure_levels) == 0:
                self.pressure_levels = DEFAULT_PRESSURE_LEVELS

            self.model_levels = model_levels
            if self.model_levels is not None and len(self.model_levels) == 0:
                self.model_levels = DEFAULT_MODEL_LEVELS

        area_str = f"{self.area}" if self.area is not None else "Global (all)"
        level_info = []
        if self.pressure_levels is not None:
            level_info.append(f"Pressure levels: {len(self.pressure_levels)} levels")
        if self.model_levels is not None:
            level_info.append(f"Model levels: {len(self.model_levels)} levels")

        resolved_variables = variables if variables is not None else DEFAULT_VARIABLES

        # Initialize CDS API client before calling super().__init__ so that
        # _validate_variables() (called after super) can use self.client.
        try:
            self.client = cdsapi.Client(url=self.model_config["url"], key=api_key)
            logger.info("CDS API client initialized successfully.")
        except Exception as e:
            raise ValueError(f"Failed to initialize CDS API client: {e}")

        try:
            requests.head(self.model_config["url"], timeout=10).raise_for_status()
        except Exception as e:
            logger.error("Initialization ERA5 connectivity check failed!")
            raise ConnectionError(f"CDS API endpoint unreachable: {e}")

        super().__init__(
            output_path=output_path,
            years=years,
            months=months,
            variables=resolved_variables,
            dry_run=dry_run,
            resume=resume,
            start_year=int(self.model_config["start_year"]),
        )

        dry_run_str = " [DRY RUN - NO DATA WILL BE DOWNLOADED]" if self.dry_run else ""
        logger.info(
            f"ERA5 Downloader initialized for:{dry_run_str}"
            f"\n- years:\t\t{self.years}"
            f"\n- months:\t\t{self.months}"
            f"\n- variables:\t\t{self.variables}"
            f"\n- area (N,W,S,E):\t{area_str}"
            f"\n- {'; '.join(level_info) if level_info else 'No levels specified'}"
        )

        self._validate_variables()

    def _get_tasks(self) -> list[tuple]:
        """Return all download tasks as (year, month, level_type) tuples.

        Returns:
            list[tuple]: Ordered list of (year, month, level_type) tuples.
        """
        logger.info("Starting ERA5 download")
        tasks = []
        for year in self.years:
            for month in self.months:
                tasks.append((year, month, "single"))
                if self.pressure_levels is not None:
                    tasks.append((year, month, "pressure"))
                if self.model_levels is not None:
                    tasks.append((year, month, "model"))
        return tasks

    def _download_task(self, task: tuple) -> int:
        """Download ERA5 variables for a specific (year, month, level_type) task.

        Args:
            task (tuple): Task tuple of (year, month, level_type).

        Returns:
            int: 1 if successful, 0 if failed.
        """
        year, month, level_type = task
        return self._download_variables(year=year, month=month, level_type=level_type)

    def _download_variables(
        self, year: int, month: str, level_type: str = "single"
    ) -> int:
        """Download ERA5 variables for a specific year, month, and level type.

        Unified method for downloading single-level (2D), pressure-level (3D), and model-level (3D) variables.
        All variables of same year, month and level_type are combined into a single file.

        Args:
            year (int): Year to download data for.
            month (str): Month to download data for (format: '01' to '12').
            level_type (str): Type of levels to download ("single", "pressure", or "model").

        Returns:
            int: Status of the download (1 if successful, 0 if any failed).
        """
        # Determine which variables to download based on level type
        if level_type == "single":
            variables_to_download = [
                v for v in self.variables if v in ALL_SINGLE_LEVEL_VARIABLES
            ]
            level_prefix = "sl"
        elif level_type == "pressure":
            variables_to_download = [
                v for v in self.variables if v in ALL_PRESSURE_LEVEL_VARIABLES
            ]
            level_prefix = "pl"
        else:  # model
            variables_to_download = [
                v for v in self.variables if v in ALL_MODEL_LEVEL_VARIABLES
            ]
            level_prefix = "ml"

        # Skip if no variables to download for this level type
        if not variables_to_download:
            return 1

        # Build filename suffix
        level_suffix = f"_{level_prefix}"
        if (
            level_type == "pressure"
            and self.pressure_levels is not None
            and self.pressure_levels != ALL_PRESSURE_LEVELS
        ):
            levels_str = "-".join(self.pressure_levels)
            level_suffix += f"_{levels_str}"
        elif (
            level_type == "model"
            and self.model_levels is not None
            and self.model_levels != ALL_MODEL_LEVELS
        ):
            levels_str = "-".join(self.model_levels)
            level_suffix += f"_{levels_str}"

        # Build combined filename with short names separated by "-"
        short_names = [self._get_mars_param(var) for var in variables_to_download]
        variables_str = "-".join(short_names)
        output_file = Path(
            self.output_path,
            f"era5_{year}_{month}{level_suffix}_{variables_str}.grib",
        )

        if output_file.exists():
            logger.info(
                f"{year}-{month} ({level_type}): File already exists locally, skipping"
            )
            return 1

        try:
            # Build a single request with all variables combined
            dataset, request_params = self._build_request_batch(
                short_names=short_names,
                year=year,
                month=month,
                level_type=level_type,
            )

            if self.dry_run:
                params_str = "\n".join(f"  {k}: {v}" for k, v in request_params.items())
                logger.info(
                    f"\n{'=' * 80}"
                    f"\nDRY RUN: {year}-{month} ({level_type}, {len(variables_to_download)} variables)"
                    f"\n{'=' * 80}"
                    f"\nDataset: {dataset}"
                    f"\nVariables: {', '.join(variables_to_download)}"
                    f"\nRequest parameters:\n{params_str}"
                    f"\nOutput file (would be): {output_file}"
                    f"\n{'=' * 80}"
                )
                return 1
            else:
                logger.info(
                    f"{year}-{month} ({level_type}, {len(variables_to_download)} variables): Starting download..."
                )
                self.client.retrieve(dataset, request_params, str(output_file))
                logger.info(
                    f"{year}-{month} ({level_type}): Downloaded and saved to {output_file}"
                )

            all_success = True
        except Exception as e:
            logger.error(
                f"{year}-{month} ({level_type}): Download failed with error: {e}"
            )
            all_success = False

        return 1 if all_success else 0

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    def _validate_variables(self) -> None:
        """Validate that all requested variables are available in ERA5.

        Raises:
            ValueError: If any requested variable is not available.
        """
        unrecognized_variables: list[str] = []
        invalid_pressure_level: list[str] = []
        invalid_model_level: list[str] = []

        for variable in self.variables:
            is_single_level = variable in ALL_SINGLE_LEVEL_VARIABLES

            if is_single_level:
                # Single-level variable is valid
                pass
            else:
                # Check if 3D variable is available
                if (
                    variable not in ALL_PRESSURE_LEVEL_VARIABLES
                    and variable not in ALL_MODEL_LEVEL_VARIABLES
                ):
                    unrecognized_variables.append(variable)
                else:
                    # Check against specific level types if requested
                    if (
                        self.pressure_levels is not None
                        and variable not in ALL_PRESSURE_LEVEL_VARIABLES
                    ):
                        invalid_pressure_level.append(
                            f"{variable} (not available at pressure levels)"
                        )
                    if (
                        self.model_levels is not None
                        and variable not in ALL_MODEL_LEVEL_VARIABLES
                    ):
                        invalid_model_level.append(
                            f"{variable} (not available at model levels)"
                        )

        # Compile error messages
        error_messages = []

        if unrecognized_variables:
            error_messages.append(
                f"Unrecognized variables: {', '.join(unrecognized_variables)}\n"
                f"Run 'python scripts/weather/era5_download.py --list-variables' to see available variables."
            )

        if invalid_pressure_level:
            error_messages.append(
                f"Invalid pressure-level variables: {', '.join(invalid_pressure_level)}\n"
                f"Run 'python scripts/weather/era5_download.py --list-variables' to see available variables."
            )

        if invalid_model_level:
            error_messages.append(
                f"Invalid model-level variables: {', '.join(invalid_model_level)}\n"
                f"Run 'python scripts/weather/era5_download.py --list-variables' to see available variables."
            )

        if error_messages:
            raise ValueError("\n".join(error_messages))

        logger.info(f"All {len(self.variables)} requested variables are available.")

    def _get_mars_param(self, variable: str) -> str:
        """Convert variable name to MARS parameter code.

        Args:
            variable (str): ERA5 variable name

        Returns:
            str: MARS parameter code
        """
        if variable in VARIABLE_TO_MARS_PARAM:
            return VARIABLE_TO_MARS_PARAM[variable]
        # Fallback: use variable name directly
        return variable

    def _build_request_batch(
        self, short_names: list[str], year: int, month: str, level_type: str = "single"
    ) -> tuple[str, dict[str, Any]]:
        """Build a CDS / MARS format request for multiple variables combined.

        Combines all variables into a single request. Combining variables into a single
        request is more efficient than making separate requests for each variable, especially
        when downloading multiple variables for the same year and month.
        The CDS API and MARS backend can optimize retrieval when multiple parameters
        are requested together, reducing overhead and improving download speed.
        For pressure and single level variables, the request is made through the CDS API
        endpoint which is faster than the MARS endpoint but do not offer model-level variables.
        For model level variables, the request is made through the MARS endpoint.

        Args:
            short_names (list[str]): List of ERA5 variable short names
            year (int): Year
            month (str): Month (format: '01' to '12')
            level_type (str): Type of levels ("single", "pressure", or "model")

        Returns:
            tuple: Dataset name and CDS / MARS format request parameters with combined param codes
        """
        days_in_month = monthrange(year, int(month))[1]
        dataset_map = {
            "model": self.model_config["MARS"]["dataset"],
            "pressure": self.model_config["CDS"]["dataset_pl"],
            "single": self.model_config["CDS"]["dataset_sl"],
        }
        dataset = dataset_map[level_type]

        request: dict[str, Any]

        # The model-level request uses the MARS endpoint which has a different request format and
        # requires additional parameters ('class', 'stream', 'type', etc.) compared to the CDS API
        # endpoint used for single and pressure level variables.
        if level_type == "model":
            date_range = f"{year}-{month}-01/to/{year}-{month}-{days_in_month:02d}"

            # Format times as HH:MM:SS separated by slashes
            time_range = "/".join([f"{i:02d}:00:00" for i in range(24)])

            # Build base request
            request = {
                "class": self.model_config["MARS"]["mars_class"],
                "date": date_range,
                "expver": self.model_config["MARS"]["mars_expver"],
                "levellist": "/".join(self.model_levels)
                if self.model_levels is not None
                else None,
                "leveltype": self.model_config["MARS"]["levtype_model"],
                "param": "/".join(short_names),
                "stream": self.model_config["MARS"]["mars_stream"],
                "time": time_range,
                "type": self.model_config["MARS"]["mars_type"],
            }

            # Add area if specified
            if self.area:
                # Format area as N/W/S/E string
                request["area"] = (
                    f"{self.area[0]}/{self.area[1]}/{self.area[2]}/{self.area[3]}"
                )

        # Pressure- and single level use the CDS API endpoint.
        else:
            date_list = [f"{i:02d}" for i in range(1, days_in_month + 1)]
            time_list = [f"{i:02d}:00" for i in range(24)]
            request = {
                "product_type": self.model_config["CDS"]["product_type"],
                "variable": short_names,
                "year": [year],
                "month": [month],
                "day": date_list,
                "time": time_list,
                "data_format": self.model_config["CDS"]["data_format"],
                "download_format": self.model_config["CDS"]["download_format"],
            }

            # Add pressure levels for pressure level variables request
            if level_type == "pressure":
                request["pressure_level"] = self.pressure_levels

            # Add area if specified
            if self.area:
                # Format area as list N, W, S, E
                request["area"] = [
                    self.area[0],
                    self.area[1],
                    self.area[2],
                    self.area[3],
                ]

        return dataset, request

    @staticmethod
    def print_available_variables() -> None:
        """Print all available ERA5 variables organized by dataset type."""
        single_level_lines = "\n".join(
            f"  - {var}{' [DEFAULT]' if var in DEFAULT_VARIABLES else ''}"
            for var in sorted(ALL_SINGLE_LEVEL_VARIABLES)
        )
        pressure_level_lines = "\n".join(
            f"  - {var}{' [DEFAULT]' if var in DEFAULT_VARIABLES else ''}"
            for var in sorted(ALL_PRESSURE_LEVEL_VARIABLES)
        )
        model_level_lines = "\n".join(
            f"  - {var}{' [DEFAULT]' if var in DEFAULT_VARIABLES else ''}"
            for var in sorted(ALL_MODEL_LEVEL_VARIABLES)
        )

        logger.info(
            "\n"
            + "=" * 80
            + "\nAVAILABLE ERA5 VARIABLES"
            + "\n"
            + "=" * 80
            + "\n\n--- SINGLE-LEVEL (2D) VARIABLES ---"
            + "\nDataset: reanalysis-era5-single-levels"
            + f"\nTotal: {len(ALL_SINGLE_LEVEL_VARIABLES)} variables\n"
            + single_level_lines
            + "\n\n--- PRESSURE-LEVEL (3D) VARIABLES ---"
            + "\nDataset: reanalysis-era5-pressure-levels"
            + f"\nAvailable levels (hPa): {', '.join(ALL_PRESSURE_LEVELS)}"
            + f"\nDefault levels: {', '.join(DEFAULT_PRESSURE_LEVELS)}"
            + f"\nTotal: {len(ALL_PRESSURE_LEVEL_VARIABLES)} variables\n"
            + pressure_level_lines
            + "\n\n--- MODEL-LEVEL (3D) VARIABLES ---"
            + "\nDataset: reanalysis-era5-complete"
            + "\nAvailable levels: 1-137 (137 levels)"
            + f"\nDefault levels: {', '.join(DEFAULT_MODEL_LEVELS)}"
            + f"\nTotal: {len(ALL_MODEL_LEVEL_VARIABLES)} variables\n"
            + model_level_lines
            + "\n"
        )

        logger.info(
            "\n"
            + "=" * 80
            + "\nUSAGE EXAMPLES:"
            + "\n"
            + "=" * 80
            + "\n\n1. Single-level variables only:"
            + "\n   python scripts/weather/era5_download.py -y 2020 -m 01 -v 2m_temperature surface_pressure"
            + "\n\n2. Pressure-level variables with default levels:"
            + "\n   python scripts/weather/era5_download.py -y 2020 -m 01 -v temperature u_component_of_wind -pl"
            + "\n\n3. Model-level variables with custom levels:"
            + "\n   python scripts/weather/era5_download.py -y 2020 -m 01 -v temperature -ml 135 136 137"
            + "\n"
            + "=" * 80
            + "\n"
        )
