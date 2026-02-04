"""ERA5 REANALYSIS DATA DOWNLOADER.

Remote API access of ERA5 reanalysis data using the cdsapi package.
"""

import pickle
from calendar import monthrange
from pathlib import Path

import cdsapi  # type: ignore[import-untyped]
import numpy as np
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
    VARIABLE_TO_MARS_PARAM,
)

# CDS API base URL
URL = "https://cds.climate.copernicus.eu/api"

# MARS request constants
MARS_CLASS = "ea"
MARS_STREAM = "oper"
MARS_TYPE = "an"
MARS_EXPVER = "1"
LEVTYPE_SINGLE = "sfc"
LEVTYPE_PRESSURE = "pl"
LEVTYPE_MODEL = "ml"


class Era5Downloader:
    """ERA5 reanalysis data downloader.

    Attributes:
        years (list[int]): List of years to get data for.
        months (list[str]): List of months to get data for.
        variables (list[str]): List of ERA5 variables to download.
        area (list[float] | None): Bounding box [North, West, South, East] in degrees. None for world (all).
        pressure_levels (list[str] | None): List of pressure levels to download (for 3D variables).
        model_levels (list[str] | None): List of model levels to download (for 3D variables).
        output_path (Path): Path to the output directory.
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (np.ndarray): Array of 0 and 1 values for tracking download status.
        client (cdsapi.Client): CDS API client for retrieving data.
        dry_run (bool): If True, print requests without submitting them.
        file_format (str): Output file format ("grib" or "netcdf").
        file_extension (str): File extension based on file_format.
        resolution (str): Grid resolution (e.g., "0.25/0.25").
    """

    def __init__(
        self,
        api_key: str,
        output_path: Path,
        years: list[int],
        months: list[str] | None = None,
        variables: list[str] | None = None,
        area: list[float] | None = None,
        resolution: str = "0.25/0.25",
        pressure_levels: list[str] | None = None,
        model_levels: list[str] | None = None,
        file_format: str = "grib",
        resume: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initializes the instance.

        Args:
            api_key (str): The CDS API key.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            months (list[str], optional): List of months (01-12). Defaults to all months.
            variables (list[str], optional): List of ERA5 variables. Defaults to common variables.
            area (list[float], optional): Bounding box [N, W, S, E]. Defaults to world (None).
            resolution (str, optional): Grid resolution. Defaults to "0.25/0.25".
            pressure_levels (list[str], optional): Pressure levels (hPa). Defaults to default levels if None.
            model_levels (list[str], optional): Model levels (1-137). Defaults to default levels if None.
            file_format (str, optional): Output file format ("grib" or "netcdf"). Defaults to "grib".
            resume (bool, optional): Whether to resume from a previous download. Defaults to False.
            dry_run (bool, optional): If True, print requests without submitting them. Defaults to False.

        Raises:
            ValueError: If API credentials are invalid or invalid file_format.
        """
        if file_format.lower() not in ["grib", "netcdf"]:
            raise ValueError(
                f"file_format must be 'grib' or 'netcdf', got '{file_format}'"
            )

        self.years = years
        self.months = (
            months if months is not None else [f"{i:02d}" for i in range(1, 13)]
        )
        self.variables = variables if variables is not None else DEFAULT_VARIABLES
        self.area = area  # If None, API downloads global data (area parameter omitted from request)
        self.resolution = resolution
        self.file_format = file_format.lower()
        self.file_extension = "nc" if self.file_format == "netcdf" else "grib"
        self.dry_run = dry_run

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

        self.output_path = Path(output_path)
        self.checkpoint_path = Path(self.output_path, "status.pickle")

        # Create output directory if it doesn't exist
        self.output_path.mkdir(parents=True, exist_ok=True)

        area_str = f"{self.area}" if self.area is not None else "World (all)"
        level_info = []
        if self.pressure_levels is not None:
            level_info.append(f"Pressure levels: {len(self.pressure_levels)} levels")
        if self.model_levels is not None:
            level_info.append(f"Model levels: {len(self.model_levels)} levels")

        dry_run_str = " [DRY RUN - NO DATA WILL BE DOWNLOADED]" if self.dry_run else ""
        logger.info(
            f"ERA5 Downloader initialised for:{dry_run_str}"
            f"\n- years:\t\t{years}"
            f"\n- months:\t\t{self.months}"
            f"\n- variables:\t\t{self.variables}"
            f"\n- area (N,W,S,E):\t{area_str}"
            f"\n- resolution:\t\t{self.resolution}"
            f"\n- file_format:\t\t{self.file_format}"
            f"\n- {'; '.join(level_info) if level_info else 'No levels specified'}"
        )

        # Initialize CDS API client
        try:
            self.client = cdsapi.Client(url=URL, key=api_key)
            logger.info("CDS API client initialized successfully.")
        except Exception as e:
            raise ValueError(f"Failed to initialize CDS API client: {e}")

        # Validate requested variables
        self._validate_variables()

        # Initialize or load checkpoint
        # Determine checkpoint dimensions based on which level types are requested
        has_single = True  # Always true
        has_pressure = self.pressure_levels is not None
        has_model = self.model_levels is not None

        num_level_types = sum([has_single, has_pressure, has_model])

        if resume and self.checkpoint_path.is_file():
            with open(self.checkpoint_path, "rb") as f:
                self.checkpoint = pickle.load(f)
            logger.info(f"Resuming from checkpoint: {self.checkpoint_path}")
        else:
            if num_level_types > 1:
                # Shape: (years, months, level_types)
                self.checkpoint = np.zeros(
                    (len(years), len(self.months), num_level_types)
                )
            else:
                self.checkpoint = np.zeros((len(years), len(self.months)))
            logger.info("Starting fresh download (no checkpoint found).")

    def _validate_variables(self) -> None:
        """Validate that all requested variables are available in ERA5.

        Raises:
            ValueError: If any requested variable is not available.
        """
        invalid_single_level: list[str] = []
        invalid_pressure_level: list[str] = []
        invalid_model_level: list[str] = []

        for variable in self.variables:
            is_single_level = variable in ALL_SINGLE_LEVEL_VARIABLES

            if is_single_level:
                # Single-level variable is valid (already checked membership above)
                pass
            else:
                # Check if 3D variable is available
                if (
                    variable not in ALL_PRESSURE_LEVEL_VARIABLES
                    and variable not in ALL_MODEL_LEVEL_VARIABLES
                ):
                    invalid_pressure_level.append(variable)
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

        if invalid_single_level:
            error_messages.append(
                f"Invalid single-level variables: {', '.join(invalid_single_level)}\n"
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

    def download_data(self) -> None:
        """Download ERA5 data for all given years and months."""
        # Determine checkpoint indices for each level type
        checkpoint_idx_map = {}
        idx = 0
        if True:  # always have single-level
            checkpoint_idx_map["single"] = idx
            idx += 1
        if self.pressure_levels is not None:
            checkpoint_idx_map["pressure"] = idx
            idx += 1
        if self.model_levels is not None:
            checkpoint_idx_map["model"] = idx

        for year in self.years:
            logger.info(f"Processing year {year}...")

            for month in self.months:
                # Download single-level (2D) variables
                self._download_variables(
                    year=year,
                    month=month,
                    level_type="single",
                    checkpoint_idx=checkpoint_idx_map.get("single", 0),
                )

                # Download pressure levels if specified
                if self.pressure_levels is not None:
                    self._download_variables(
                        year=year,
                        month=month,
                        level_type="pressure",
                        checkpoint_idx=checkpoint_idx_map.get("pressure", 0),
                    )

                # Download model levels if specified
                if self.model_levels is not None:
                    self._download_variables(
                        year=year,
                        month=month,
                        level_type="model",
                        checkpoint_idx=checkpoint_idx_map.get("model", 0),
                    )

        logger.info("All downloads completed!")

    def _download_variables(
        self, year: int, month: str, level_type: str = "single", checkpoint_idx: int = 0
    ) -> int:
        """Download ERA5 variables for a specific year, month, and level type.

        Unified method for downloading single-level (2D), pressure-level (3D), and model-level (3D) variables.
        All variables of same year, month and level_type are combined into a single file.

        Args:
            year (int): Year to download data for.
            month (str): Month to download data for (format: '01' to '12').
            level_type (str): Type of levels to download ("single", "pressure", or "model").
            checkpoint_idx (int): Index in checkpoint array for tracking download status.

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

        # Check checkpoint
        year_idx = self.years.index(year)
        month_idx = self.months.index(month)

        if self.checkpoint.ndim == 3:
            if self.checkpoint[year_idx, month_idx, checkpoint_idx] != 0:
                logger.info(
                    f"{year}-{month} ({level_type}): Data previously downloaded."
                )
                return 1
        else:
            if self.checkpoint[year_idx, month_idx] != 0:
                logger.info(
                    f"{year}-{month} ({level_type}): Data previously downloaded."
                )
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
        output_file = (
            self.output_path
            / f"era5_{year}_{month}{level_suffix}_{variables_str}.{self.file_extension}"
        )

        try:
            # Build a single request with all variables combined
            request_params = self._build_mars_request_batch(
                variables=variables_to_download,
                year=year,
                month=month,
                level_type=level_type,
            )

            if self.dry_run:
                # Print request without submitting
                print("\n" + "=" * 80)
                print(
                    f"DRY RUN: {year}-{month} ({level_type}, {len(variables_to_download)} variables)"
                )
                print("=" * 80)
                print("Dataset: reanalysis-era5-complete")
                print(f"Variables: {', '.join(variables_to_download)}")
                print("Request parameters:")
                for key, value in request_params.items():
                    print(f"  {key}: {value}")
                print(f"Output file (would be): {output_file}")
                print("=" * 80 + "\n")
                logger.info(
                    f"{year}-{month} ({level_type}): DRY RUN - Request printed (not submitted)"
                )
                # Do not update checkpoint for dry runs
                return 1
            else:
                logger.info(
                    f"{year}-{month} ({level_type}, {len(variables_to_download)} variables): Starting download..."
                )
                self.client.retrieve(
                    "reanalysis-era5-complete", request_params, str(output_file)
                )
                logger.info(
                    f"{year}-{month} ({level_type}): Downloaded and saved to {output_file}"
                )

            all_success = True
        except Exception as e:
            logger.error(
                f"{year}-{month} ({level_type}): Download failed with error: {e}"
            )
            all_success = False

        # Update checkpoint
        status = 1 if all_success else 0
        if self.checkpoint.ndim == 3:
            self.checkpoint[year_idx, month_idx, checkpoint_idx] = status
        else:
            self.checkpoint[year_idx, month_idx] = status

        with open(self.checkpoint_path, "wb") as f:
            pickle.dump(self.checkpoint, f)

        return status

    def _get_mars_param(self, variable: str) -> str:
        """Convert variable name to MARS parameter code.

        Args:
            variable (str): ERA5 variable name

        Returns:
            str: MARS parameter code
        """
        if variable in VARIABLE_TO_MARS_PARAM:
            return VARIABLE_TO_MARS_PARAM[variable]
        # Fallback: try to use variable name directly
        return variable.replace("_", "")[:10]

    def _build_mars_request_batch(
        self, variables: list[str], year: int, month: str, level_type: str = "single"
    ) -> dict:
        """Build a MARS format request for multiple variables combined.

        Combines all variables into a single request with param codes joined by "/".
        This is more efficient for MARS backend processing.

        Args:
            variables (list[str]): List of ERA5 variable names
            year (int): Year
            month (str): Month (format: '01' to '12')
            level_type (str): Type of levels ("single", "pressure", or "model")

        Returns:
            dict: MARS format request parameters with combined param codes
        """
        days_in_month = monthrange(year, int(month))[1]
        date_range = f"{year}-{month}-01/to/{year}-{month}-{days_in_month:02d}"

        # Format times as HH:MM:SS separated by slashes
        times = "/".join([f"{i:02d}:00:00" for i in range(24)])

        # Format area as N/W/S/E string
        area_str = (
            f"{self.area[0]}/{self.area[1]}/{self.area[2]}/{self.area[3]}"
            if self.area
            else None
        )

        # Combine all parameter codes with "/"
        param_codes = [self._get_mars_param(var) for var in variables]
        combined_params = "/".join(param_codes)

        # Build base request
        request = {
            "class": MARS_CLASS,
            "date": date_range,
            "expver": MARS_EXPVER,
            "grid": self.resolution,
            "param": combined_params,
            "stream": MARS_STREAM,
            "time": times,
            "type": MARS_TYPE,
        }

        # Add area if specified
        if area_str:
            request["area"] = area_str

        # Add level-specific parameters
        if level_type == "single":
            # Single-level (surface) variables
            request["levtype"] = LEVTYPE_SINGLE
        elif level_type == "pressure":
            request["levtype"] = LEVTYPE_PRESSURE
            if self.pressure_levels is not None:
                request["levelist"] = "/".join(self.pressure_levels)
        elif level_type == "model":
            request["levtype"] = LEVTYPE_MODEL
            if self.model_levels is not None:
                request["levelist"] = "/".join(self.model_levels)

        return request

    @staticmethod
    def print_available_variables() -> None:
        """Print all available ERA5 variables organized by dataset type."""
        print("\n" + "=" * 80)
        print("AVAILABLE ERA5 VARIABLES")
        print("=" * 80)

        print("\n--- SINGLE-LEVEL (2D) VARIABLES ---")
        print("Dataset: reanalysis-era5-single-levels")
        print(f"Total: {len(ALL_SINGLE_LEVEL_VARIABLES)} variables\n")
        for var in sorted(ALL_SINGLE_LEVEL_VARIABLES):
            marker = " [DEFAULT]" if var in DEFAULT_VARIABLES else ""
            print(f"  • {var}{marker}")

        print("\n--- PRESSURE-LEVEL (3D) VARIABLES ---")
        print("Dataset: reanalysis-era5-pressure-levels")
        print(f"Available levels (hPa): {', '.join(ALL_PRESSURE_LEVELS)}")
        print(f"Default levels: {', '.join(DEFAULT_PRESSURE_LEVELS)}")
        print(f"Total: {len(ALL_PRESSURE_LEVEL_VARIABLES)} variables\n")
        for var in sorted(ALL_PRESSURE_LEVEL_VARIABLES):
            marker = (
                " [DEFAULT]"
                if var
                in [
                    "temperature",
                    "u_component_of_wind",
                    "v_component_of_wind",
                    "relative_humidity",
                    "geopotential",
                ]
                else ""
            )
            print(f"  • {var}{marker}")

        print("\n--- MODEL-LEVEL (3D) VARIABLES ---")
        print("Dataset: reanalysis-era5-complete")
        print("Available levels: 1-137 (137 levels)")
        print(f"Default levels: {', '.join(DEFAULT_MODEL_LEVELS)}")
        print(f"Total: {len(ALL_MODEL_LEVEL_VARIABLES)} variables\n")
        for var in sorted(ALL_MODEL_LEVEL_VARIABLES):
            marker = (
                " [DEFAULT]"
                if var
                in [
                    "temperature",
                    "u_component_of_wind",
                    "v_component_of_wind",
                    "relative_humidity",
                    "geopotential",
                ]
                else ""
            )
            print(f"  • {var}{marker}")

        print("\n" + "=" * 80)
        print("USAGE EXAMPLES:")
        print("=" * 80)
        print("\n1. Single-level variables only:")
        print(
            "   python scripts/weather/era5_download.py -y 2020 -m 01 -v 2m_temperature surface_pressure\n"
        )
        print("2. Pressure-level variables with default levels:")
        print(
            "   python scripts/weather/era5_download.py -y 2020 -m 01 -v temperature u_component_of_wind -pl\n"
        )
        print("3. Model-level variables with custom levels:")
        print(
            "   python scripts/weather/era5_download.py -y 2020 -m 01 -v temperature -ml 135 136 137\n"
        )
        print("=" * 80 + "\n")
