"""BARRA2 REANALYSIS DATA DOWNLOADER.

Download BARRA2 reanalysis data (R2, C2, or C2_20min) from National Computational Infrastructure (NCI) THREDDS server.
"""

from pathlib import Path

import requests
from loguru import logger

from rbc.weather.barra.mappings import (
    C2_20MIN_SINGLE_LEVEL_VARIABLES,
    C2_DEFAULT_PRESSURE_LEVELS,
    C2_PRESSURE_LEVEL_VARIABLES,
    C2_SINGLE_LEVEL_VARIABLES,
    DEFAULT_VARIABLES,
    INVARIANT_VARIABLES,
    MODEL_CONFIG,
    R2_DEFAULT_PRESSURE_LEVELS,
    R2_PRESSURE_LEVEL_VARIABLES,
    R2_SINGLE_LEVEL_VARIABLES,
    VARIABLE_TO_SHORT_PARAM,
)
from rbc.weather.utils import (
    WeatherDownloader,
    download_file_streaming,
    get_short_param,
    raw_data_dir,
)


def _normalize_model(model: str) -> str:
    """Normalize model name to standard uppercase form.

    Args:
        model (str): Model name string (case-insensitive).

    Returns:
        str: Normalized model name ("R2", "C2", or "C2_20min").

    Raises:
        ValueError: If the model name is not recognized.
    """
    normalized_lookup = {key.lower(): key for key in MODEL_CONFIG}
    model_key = model.strip().lower()
    if model_key not in normalized_lookup:
        raise ValueError(
            f"Unknown BARRA2 model '{model}'. "
            f"Choose from: {', '.join(MODEL_CONFIG.keys())}"
        )
    return normalized_lookup[model_key]


def _get_available_codes(model_name: str) -> set[str]:
    """Return the set of BARRA2 codes available for a given model.

    Args:
        model_name (str): Normalized model key ("R2", "C2", or "C2_20min").

    Returns:
        set[str]: Set of BARRA2 parameter codes available for the model.
    """
    if model_name == "R2":
        return (
            R2_SINGLE_LEVEL_VARIABLES
            | R2_PRESSURE_LEVEL_VARIABLES
            | INVARIANT_VARIABLES
        )
    elif model_name == "C2":
        return (
            C2_SINGLE_LEVEL_VARIABLES
            | C2_PRESSURE_LEVEL_VARIABLES
            | INVARIANT_VARIABLES
        )
    else:
        return C2_20MIN_SINGLE_LEVEL_VARIABLES | INVARIANT_VARIABLES


class Barra2Downloader(WeatherDownloader):
    """BARRA2 reanalysis data downloader.

    Downloads BARRA2 NWP reanalysis data from NCI THREDDS server.
    Supports three model keys: R2 (11 km, 1 hr), C2 (4 km, 1 hr),
    and C2_20min (4 km, 20 min).

    Attributes:
        available_codes (set[str]): Set of BARRA2 parameter codes available for the model.
        model_config (dict): Model-specific configuration from MODEL_CONFIG.
        include_invariants (bool): If True, invariant variables are included in the download.
        invariant_output_path (Path): Directory for invariant variable outputs.
        model (str): Model key ("R2", "C2", or "C2_20min").
        pressure_levels (list[int]): Pressure levels for 3D variables (hPa).
        temporal_res (str): Temporal resolution (from MODEL_CONFIG).
    """

    def __init__(
        self,
        output_path: Path,
        model: str,
        years: list[int],
        months: list[str] | None = None,
        variables: list[str] | None = None,
        pressure_levels: list[int] | None = None,
        include_invariants: bool = False,
        dry_run: bool = False,
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            output_path (Path): Directory to save downloaded data.
            model (str): BARRA2 model key ("R2", "C2", or "C2_20min").
            years (list[int]): List of years to download.
            months (list[str] | None, optional): List of months (01-12).
                If None, defaults to all months.
            variables (list[str] | None, optional): Variables to download.
                If None, defaults to model-specific DEFAULT_VARIABLES.
            pressure_levels (list[int] | None, optional): Pressure levels for 3D variables (in hPa).
                If None, defaults to model-specific pressure levels.
            include_invariants (bool, optional): If True, include invariant
                variables (orography, land-sea mask) in download set.
                Defaults to False.
            dry_run (bool, optional): If True, print requests without downloading.
                Defaults to False.
            resume (bool, optional): If True, resume from checkpoint.
                Defaults to True.

        Raises:
            ValueError: If model name is not recognized, any year is invalid,
                or any month is out of range (01-12).
            ConnectionError: If one or more BARRA2 endpoints are unreachable.
        """
        self.model = _normalize_model(model)
        self.model_config = MODEL_CONFIG[self.model]
        self.temporal_res: str = self.model_config["temporal_res"]
        self.include_invariants = include_invariants

        # base_dir is the shared raw-data root
        self.base_dir = Path(output_path)
        resolved_output_path = raw_data_dir(
            self.base_dir,
            self.model_config["raw_folder"],
            self.model_config["temporal_res_folder"],
        )
        self.invariant_output_path = raw_data_dir(
            self.base_dir, self.model_config["raw_folder"], "invariant"
        )

        # Build available BARRA2 codes and variable names for selected model
        self.available_codes = _get_available_codes(self.model)

        # Setup variables (use defaults if none provided)
        if variables is not None:
            base_variables = list(variables)
        else:
            base_variables = [
                v
                for v in DEFAULT_VARIABLES
                if VARIABLE_TO_SHORT_PARAM.get(v, v) in self.available_codes
            ]
        if self.include_invariants:
            invariant_variable_names = sorted(
                name
                for name, code in VARIABLE_TO_SHORT_PARAM.items()
                if code in INVARIANT_VARIABLES
            )
            resolved_variables: list[str] = list(
                dict.fromkeys([*base_variables, *invariant_variable_names])
            )
        else:
            resolved_variables = base_variables

        # Setup pressure levels (use model defaults if none provided)
        if pressure_levels is not None:
            self.pressure_levels = list(map(str, pressure_levels))
        elif self.model == "R2":
            self.pressure_levels = list(map(str, R2_DEFAULT_PRESSURE_LEVELS))
        elif self.model == "C2":
            self.pressure_levels = list(map(str, C2_DEFAULT_PRESSURE_LEVELS))
        else:
            self.pressure_levels = []

        try:
            for url in [
                self.model_config["catalog_url"],
                self.model_config["invariant_catalog_url"],
            ]:
                requests.head(url, timeout=10).raise_for_status()
        except Exception as e:
            logger.error("Initialization BARRA2 connectivity check failed!")
            raise ConnectionError(f"One or more BARRA2 endpoints are unreachable: {e}")

        super().__init__(
            output_path=resolved_output_path,
            years=years,
            months=months,
            variables=resolved_variables,
            dry_run=dry_run,
            resume=resume,
            start_year=int(self.model_config["start_year"]),
        )

        dry_run_str = " [DRY RUN - NO DATA WILL BE DOWNLOADED]" if self.dry_run else ""
        logger.info(
            f"BARRA2 Downloader initialized for:{dry_run_str}"
            f"\n- model:\t\t{self.model_config['label']} ({self.model_config['resolution']})"
            f"\n- years:\t\t{self.years}"
            f"\n- months:\t\t{self.months}"
            f"\n- variables:\t\t{self.variables}"
        )

        self._validate_variables()

    def _get_tasks(self) -> list[tuple]:
        """Return all download tasks: invariant variables first, then temporal.

        Invariant tasks use the sentinel key ("fx", "fx", variable, "").
        Single-level tasks use (year, month, variable, "").
        Pressure-level tasks use (year, month, variable, level) for each pressure level.

        Returns:
            list[tuple]: Ordered list of task tuples.
        """
        logger.info(
            f"Starting BARRA2 {self.model_config['label']} download "
            f"({self.temporal_res} frequency)"
        )

        pressure_codes = (
            R2_PRESSURE_LEVEL_VARIABLES
            if self.model == "R2"
            else C2_PRESSURE_LEVEL_VARIABLES
            if self.model == "C2"
            else set()
        )

        invariant_tasks: list[tuple] = [
            ("fx", "fx", v, "")
            for v in self.variables
            if get_short_param(v, VARIABLE_TO_SHORT_PARAM) in INVARIANT_VARIABLES
        ]
        single_tasks: list[tuple] = [
            (year, month, v, "")
            for year in self.years
            for month in self.months
            for v in self.variables
            if get_short_param(v, VARIABLE_TO_SHORT_PARAM) not in INVARIANT_VARIABLES
            and get_short_param(v, VARIABLE_TO_SHORT_PARAM) not in pressure_codes
        ]
        pressure_tasks: list[tuple] = [
            (year, month, v, str(level))
            for year in self.years
            for month in self.months
            for v in self.variables
            if get_short_param(v, VARIABLE_TO_SHORT_PARAM) in pressure_codes
            for level in self.pressure_levels
        ]

        return invariant_tasks + single_tasks + pressure_tasks

    def _download_task(self, task: tuple) -> int:
        """Download a single BARRA2 data file.

        Args:
            task (tuple): Task tuple of (year, month, variable, level).
                Invariant variables use ("fx", "fx", variable, "").
                Single-level variables use (year, month, variable, "").
                Pressure-level variables use (year, month, variable, "pressure").

        Returns:
            int: 1 if successful, 0 if failed.
        """
        year, month, variable, level = task
        return self._download_variables(
            year=year, month=month, variable=variable, level=level
        )

    def _download_variables(
        self, year: int | str, month: str, variable: str, level: str
    ) -> int:
        """Download a single BARRA2 data file.

        Args:
            year (int | str): Year to download, or "fx" for invariant variables.
            month (str): Month to download (format: '01' to '12'), or "fx" for invariant variables.
            variable (str): Variable name (e.g., 'temperature', '10m_u_component_of_wind').
            level (str): Pressure level as string (e.g. "1000"), or "" for single-level/invariant variables.

        Returns:
            int: 1 if successful, 0 if failed.
        """
        url = self._build_opendap_url(year, month, variable, level)
        output_file = self._construct_file_path(year, month, variable, level)
        description = f"{year}-{month} ({variable})"

        if output_file.exists():
            logger.info(f"{description}: File already exists locally, skipping")
            return 1

        if self.dry_run:
            logger.info(f"{description}: DRY RUN - Would download from {url}")
            return 1

        logger.info(f"{description}: Downloading {output_file.name}...")
        return download_file_streaming(
            url=url, output_file=output_file, description=description
        )

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    def _build_opendap_url(
        self, year: int | str, month: str, variable: str, level: str
    ) -> str:
        """Build OPeNDAP URL for a specific file on the NCI THREDDS server.

        The URL structure follows the NCI THREDDS catalog layout for BARRA2 data.

        Args:
            year (int | str): Year as integer, or "fx" for invariant variables.
            month (str): Month as string (01-12), or "fx" for invariant variables.
            variable (str): Variable name.
            level (str): Pressure level as string (e.g. "1000"), or "" for single-level/invariant variables.

        Returns:
            str: Full OPeNDAP URL for accessing the file.
        """
        base_url = self.model_config["opendap_url"].replace("/dodsC/", "/fileServer/")
        barra2_code = get_short_param(variable, VARIABLE_TO_SHORT_PARAM)
        grid = self.model_config["grid"]
        dataset_label = self.model_config["label"]

        if barra2_code in INVARIANT_VARIABLES:
            invariant_path = self.model_config.get("invariant_path", "fx")
            dataset_file = (
                f"{barra2_code}_{grid}_ERA5_historical_hres_BOM_{dataset_label}_v1.nc"
            )
            url = f"{base_url}/{invariant_path}/{barra2_code}/latest/{dataset_file}"
        else:
            year_month = f"{year}{month}"
            dataset_file = (
                f"{barra2_code}{level}_{grid}_ERA5_historical_hres_BOM_"
                f"{dataset_label}_v1_{self.temporal_res}_{year_month}-{year_month}.nc"
            )
            url = f"{base_url}/{self.temporal_res}/{barra2_code}{level}/latest/{dataset_file}"
        return url

    def _construct_file_path(
        self, year: int | str, month: str, variable: str, level: str
    ) -> Path:
        """Construct the local file path for a BARRA2 data file.

        Args:
            year (int | str): Year as integer, or "fx" for invariant variables.
            month (str): Month as string (01-12), or "fx" for invariant variables.
            variable (str): Variable name.
            level (str): Pressure level as string (e.g. "1000"), or "" for single-level/invariant variables.

        Returns:
            Path: Full local file path for the data file.
        """
        barra2_code = get_short_param(variable, VARIABLE_TO_SHORT_PARAM)
        if barra2_code in INVARIANT_VARIABLES:
            filename = f"barra2_{self.model}_fx_{barra2_code}.nc"
            return Path(self.invariant_output_path, filename)
        else:
            filename = f"barra2_{self.model}_{self.temporal_res}_{year}{month}_{barra2_code}{level}.nc"
            return Path(self.output_path, filename)

    def _validate_variables(self) -> None:
        """Validate that requested variables are available for this model.

        Checks that all requested variables exist in VARIABLE_TO_BARRA2_PARAM
        and that the resolved BARRA2 codes are available for this model.

        Raises:
            ValueError: If any requested variable is not recognized or not
                available for this model.
        """
        # Check that all requested variables exist in our mapping or is already a BARRA2 code
        all_known_vars = set(VARIABLE_TO_SHORT_PARAM.keys()) | set(
            VARIABLE_TO_SHORT_PARAM.values()
        )
        invalid_vars = [v for v in self.variables if v not in all_known_vars]

        if invalid_vars:
            raise ValueError(
                f"Invalid variables: {', '.join(invalid_vars)}.\n"
                f"Run 'python scripts/weather/barra_download.py "
                f"--list-variables --model {self.model}' to see available variables."
            )

        # Check that the BARRA2 codes are available for this model
        unavailable_vars = [
            v
            for v in self.variables
            if get_short_param(v, VARIABLE_TO_SHORT_PARAM) not in self.available_codes
        ]

        if unavailable_vars:
            barra2_codes = [
                get_short_param(v, VARIABLE_TO_SHORT_PARAM) for v in unavailable_vars
            ]
            raise ValueError(
                f"Variables not available for BARRA2-{self.model}: "
                f"{', '.join(unavailable_vars)} "
                f"(BARRA2 codes: {', '.join(barra2_codes)}).\n"
                f"Run 'python scripts/weather/barra_download.py "
                f"--list-variables --model {self.model}' to see available variables."
            )
        logger.info(f"All {len(self.variables)} requested variables are available.")

    @staticmethod
    def print_available_variables(model: str = "R2") -> None:
        """Print all available BARRA2 variables for a model.

        Args:
            model (str): Model key ("R2", "C2", "C2_20min", or "all").
        """
        models = (
            list(MODEL_CONFIG.keys())
            if model.lower() == "all"
            else [_normalize_model(model)]
        )

        for model_name in models:
            config = MODEL_CONFIG[model_name]
            single_level_codes = (
                R2_SINGLE_LEVEL_VARIABLES
                if model_name == "R2"
                else C2_SINGLE_LEVEL_VARIABLES
                if model_name == "C2"
                else C2_20MIN_SINGLE_LEVEL_VARIABLES
            )
            pressure_level_codes = (
                R2_PRESSURE_LEVEL_VARIABLES
                if model_name == "R2"
                else C2_PRESSURE_LEVEL_VARIABLES
                if model_name == "C2"
                else set()
            )

            var_items = sorted(VARIABLE_TO_SHORT_PARAM.items())
            single_level_vars = [n for n, c in var_items if c in single_level_codes]
            pressure_level_vars = [n for n, c in var_items if c in pressure_level_codes]
            invariant_vars = [n for n, c in var_items if c in INVARIANT_VARIABLES]

            single_level_lines = "\n".join(
                (
                    f"  - {name} ({VARIABLE_TO_SHORT_PARAM[name]})"
                    f"{' [DEFAULT]' if name in DEFAULT_VARIABLES else ''}"
                )
                for name in single_level_vars
            )
            pressure_level_lines = "\n".join(
                (
                    f"  - {name} ({VARIABLE_TO_SHORT_PARAM[name]})"
                    f"{' [DEFAULT]' if name in DEFAULT_VARIABLES else ''}"
                )
                for name in pressure_level_vars
            )
            invariant_lines = "\n".join(
                f"  - {name} ({VARIABLE_TO_SHORT_PARAM[name]})"
                for name in invariant_vars
            )

            total_vars = (
                len(single_level_vars) + len(pressure_level_vars) + len(invariant_vars)
            )

            pressure_section = (
                "\n\n--- PRESSURE-LEVEL (3D) VARIABLES ---"
                + f"\nDataset: {config['description']}"
                + f"\nResolution: {config['resolution']}"
                + f"\nTemporal: {config['temporal_res']}"
                + f"\nTotal: {len(pressure_level_vars)} variables"
                + (
                    f"\n\n{pressure_level_lines}"
                    if pressure_level_lines
                    else "\n\n  - None for this model"
                )
            )

            logger.info(
                "\n"
                + "=" * 80
                + f"\nAVAILABLE BARRA2-{model_name} VARIABLES"
                + "\n"
                + "=" * 80
                + f"\nDataset: {config['description']}"
                + f"\nResolution: {config['resolution']}"
                + f"\nTemporal: {config['temporal_res']}"
                + f"\nTotal: {total_vars} variables"
                + "\n\n--- SINGLE-LEVEL (2D) VARIABLES ---"
                + f"\nDataset: {config['description']}"
                + f"\nResolution: {config['resolution']}"
                + f"\nTemporal: {config['temporal_res']}"
                + f"\nTotal: {len(single_level_vars)} variables\n"
                + single_level_lines
                + pressure_section
                + "\n\n--- INVARIANT VARIABLES ---"
                + f"\nTotal: {len(invariant_vars)} variables\n\n"
                + invariant_lines
                + "\n"
            )

        logger.info(
            "\n"
            + "=" * 80
            + "\nUSAGE EXAMPLES:"
            + "\n"
            + "=" * 80
            + "\n\n1. Download default variables for R2 model:"
            + "\n   python scripts/weather/barra_download.py --model R2 -y 2020 2021"
            + "\n\n2. Download specific variables for C2:"
            + "\n   python scripts/weather/barra_download.py "
            + "-M C2 -y 2022 -v 1.5m_temperature 10m_u_component_of_wind 10m_v_component_of_wind CAPE"
            + "\n\n3. Dry run to see what would be downloaded:"
            + "\n   python scripts/weather/barra_download.py "
            + "--model R2 -y 2020 --months 01 02 --dry-run"
            + "\n"
            + "=" * 80
            + "\n"
        )
