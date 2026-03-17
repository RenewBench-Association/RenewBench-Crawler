"""BARRA2 REANALYSIS DATA DOWNLOADER.

Download BARRA2 reanalysis data (R2, C2, or C2_20min) from National Computational Infrastructure (NCI) THREDDS server.
"""

import datetime
import pickle
from pathlib import Path

import requests
from loguru import logger
from tqdm import tqdm

from rbc.weather.barra.mappings import (
    C2_20MIN_SINGLE_LEVEL_VARIABLES,
    C2_PRESSURE_LEVEL_VARIABLES,
    C2_PRESSURE_LEVELS,
    C2_SINGLE_LEVEL_VARIABLES,
    DEFAULT_VARIABLES,
    INVARIANT_VARIABLES,
    MODEL_CONFIG,
    R2_PRESSURE_LEVEL_VARIABLES,
    R2_PRESSURE_LEVELS,
    R2_SINGLE_LEVEL_VARIABLES,
    VARIABLE_TO_BARRA2_PARAM,
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


class Barra2Downloader:
    """BARRA2 reanalysis data downloader.

    Downloads BARRA2 NWP reanalysis data from NCI THREDDS server.
    Supports three model keys: R2 (11 km, 1 hr), C2 (4 km, 1 hr),
    and C2_20min (4 km, 20 min).

    Attributes:
        available_codes (set[str]): Set of BARRA2 parameter codes available for the model.
        available_variables (set[str]): Known available variables for this model.
        checkpoint (dict): Dict tracking download status per (year, month, variable).
        checkpoint_path (Path): Path to checkpoint file for resume capability.
        config (dict): Model-specific configuration from MODEL_CONFIG.
        dry_run (bool): If True, print requests without downloading.
        include_invariants (bool): If True, invariant variables are included in the download.
        invariant_output_path (Path): Directory for invariant variable outputs.
        model (str): Model key ("R2", "C2", or "C2_20min").
        months (list[str]): List of months to download (01-12).
        output_path (Path): Path to output directory.
        pressure_levels (list[int]): Pressure levels for 3D variables (hPa).
        resume (bool): If True, resume from previous checkpoint.
        temporal_res (str): Temporal resolution (from MODEL_CONFIG).
        variables (list[str]): List of variables to download.
        years (list[int]): List of years to download.
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
                Defaults to all months.
            variables (list[str] | None, optional): Variables to download.
                Defaults to model-specific defaults.
            pressure_levels (list[int] | None, optional): Pressure levels for
                3D variables (in hPa). Defaults to all levels for the model.
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
        """
        self.model = _normalize_model(model)
        self.config = MODEL_CONFIG[self.model]
        self.temporal_res: str = self.config["temporal_res"]
        self.years = sorted(years)
        self.months = (
            months if months is not None else [f"{i:02d}" for i in range(1, 13)]
        )
        self.include_invariants = include_invariants
        self.dry_run = dry_run
        self.resume = resume

        # Output path setup
        base_output_path = Path(output_path)
        if base_output_path.name == self.model:
            self.output_path = base_output_path
        else:
            self.output_path = Path(base_output_path, self.model)
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = Path(self.output_path, "status.pickle")
        self.invariant_output_path = Path(self.output_path, "invariant")

        # Check if years are within valid range (1979 to current year)
        current_year = datetime.date.today().year
        invalid_years = [y for y in self.years if not (1979 <= y <= current_year)]
        if invalid_years:
            raise ValueError(
                f"Invalid years: {invalid_years}. Years must be between 1979 and {current_year}."
            )

        # Build available BARRA2 codes for selected model
        self.available_codes = _get_available_codes(self.model)
        # Build set of descriptive names available for this model key
        self.available_variables = {
            name
            for name, code in VARIABLE_TO_BARRA2_PARAM.items()
            if code in self.available_codes
        }

        # Setup variables (use defaults if none provided)
        base_variables = (
            list(variables) if variables is not None else list(DEFAULT_VARIABLES)
        )
        if self.include_invariants:
            invariant_variable_names = sorted(
                [
                    name
                    for name, code in VARIABLE_TO_BARRA2_PARAM.items()
                    if code in INVARIANT_VARIABLES
                ]
            )
            self.variables: list[str] = list(
                dict.fromkeys([*base_variables, *invariant_variable_names])
            )
        else:
            self.variables = base_variables

        # Setup pressure levels (use model defaults if none provided)
        if pressure_levels is not None:
            self.pressure_levels = pressure_levels
        elif self.model == "R2":
            self.pressure_levels = list(R2_PRESSURE_LEVELS)
        elif self.model == "C2":
            self.pressure_levels = list(C2_PRESSURE_LEVELS)
        else:
            self.pressure_levels = []

        dry_run_str = " [DRY RUN - NO DATA WILL BE DOWNLOADED]" if self.dry_run else ""
        logger.info(
            f"BARRA2 Downloader initialized for:{dry_run_str}"
            f"\n- model:\t\t{self.config['label']} ({self.config['resolution']})"
            f"\n- years:\t\t{self.years}"
            f"\n- months:\t\t{self.months}"
            f"\n- variables:\t\t{self.variables}"
        )

        # Validate model-variable compatibility
        self._validate_variables()

        # Initialize or load checkpoint
        self.checkpoint: dict[tuple[int | str, str, str], int] = {}
        if resume and self.checkpoint_path.is_file():
            with open(self.checkpoint_path, "rb") as f:
                self.checkpoint = pickle.load(f)
            logger.info(f"Resuming from checkpoint: {self.checkpoint_path}")
        else:
            logger.info("Starting fresh download (no checkpoint found).")

        try:
            for url in [
                self.config["catalog_url"],
                self.config["invariant_catalog_url"],
            ]:
                requests.head(url, timeout=10).raise_for_status()
        except Exception as e:
            logger.error("Initialization BARRA2 connectivity check failed!")
            raise ConnectionError(f"One or more BARRA2 endpoints are unreachable: {e}")

    @staticmethod
    def _get_barra2_param(variable: str) -> str:
        """Convert descriptive variable name to BARRA2 parameter code.

        Args:
            variable (str): Descriptive variable name (e.g. "10m_u_component_of_wind").

        Returns:
            str: BARRA2 parameter code (e.g. "uas").
        """
        if variable in VARIABLE_TO_BARRA2_PARAM:
            return VARIABLE_TO_BARRA2_PARAM[variable]
        # Fallback: use variable name directly (e.g. already a BARRA2 code)
        return variable

    def _validate_variables(self) -> None:
        """Validate that requested variables are available for this model.

        Checks that all requested variables exist in VARIABLE_TO_BARRA2_PARAM
        and that the resolved BARRA2 codes are available for this model.

        Raises:
            ValueError: If any requested variable is not recognized or not
                available for this model.
        """
        # Check that all requested variables exist in our mapping or is already a BARRA2 code
        all_known_vars = set(VARIABLE_TO_BARRA2_PARAM.keys()) | set(
            VARIABLE_TO_BARRA2_PARAM.values()
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
            if self._get_barra2_param(v) not in self.available_codes
        ]

        if unavailable_vars:
            barra2_codes = [self._get_barra2_param(v) for v in unavailable_vars]
            raise ValueError(
                f"Variables not available for BARRA2-{self.model}: "
                f"{', '.join(unavailable_vars)} "
                f"(BARRA2 codes: {', '.join(barra2_codes)}).\n"
                f"Run 'python scripts/weather/barra_download.py "
                f"--list-variables --model {self.model}' to see available variables."
            )
        logger.info(f"All {len(self.variables)} requested variables are available.")

    def download_data(self) -> None:
        """Download BARRA2 data for all specified years, months, and variables.

        Fetches files from NCI THREDDS server and downloads them according to
        checkpoint status. Supports resume capability.
        Invariant (time-independent) variables are downloaded once before the
        temporal loop.
        """
        logger.info(
            f"Starting BARRA2 {self.config['label']} download "
            f"({self.temporal_res} frequency)"
        )

        # Split variables into invariant (time-independent) and temporal
        invariant_vars = [
            v
            for v in self.variables
            if self._get_barra2_param(v) in INVARIANT_VARIABLES
        ]
        temporal_vars = [
            v
            for v in self.variables
            if self._get_barra2_param(v) not in INVARIANT_VARIABLES
        ]

        # Download invariant variables once (not per year/month)
        for variable in invariant_vars:
            task: tuple[int | str, str, str] = ("fx", "fx", variable)

            if self.checkpoint.get(task, 0) == 1:
                logger.info(f"({variable}): Invariant already downloaded. Skipping.")
                continue

            success_code = self._download_variable(
                year=0, month="fx", variable=variable
            )

            if not self.dry_run:
                self.checkpoint[task] = success_code
                with open(self.checkpoint_path, "wb") as f:
                    pickle.dump(self.checkpoint, f)

        # Download temporal variables per year/month
        for year in self.years:
            logger.info(f"Processing year {year}...")

            for month in self.months:
                for variable in temporal_vars:
                    task = (year, month, variable)

                    # Check if task was previously run and was unsuccessful before (= 0)
                    if self.checkpoint.get(task, 0) == 0:
                        success_code = self._download_variable(
                            year=year, month=month, variable=variable
                        )
                        if not self.dry_run:
                            self.checkpoint[task] = success_code
                            with open(self.checkpoint_path, "wb") as f:
                                pickle.dump(self.checkpoint, f)
                    else:
                        logger.info(
                            f"{year}-{month} ({variable}): Data previously downloaded."
                        )

        logger.info("All downloads completed!")

    def _download_variable(self, year: int, month: str, variable: str) -> int:
        """Download a single BARRA2 data file from the NCI THREDDS server.

        Args:
            year (int): Year to download.
            month (str): Month to download (format: "01" to "12").
            variable (str): Variable name (e.g. "tas", "pr", "ta500").

        Returns:
            int: 1 if successful, 0 if failed.
        """
        url = self._build_opendap_url(year, month, variable)
        output_file = self._construct_file_path(year, month, variable)

        # Check if file already exists locally
        if output_file.exists():
            logger.info(
                f"{year}-{month} ({variable}): File already exists locally, skipping"
            )
            return 1

        if self.dry_run:
            logger.info(
                f"{year}-{month} ({variable}): DRY RUN - Would download from {url}"
            )
            return 0

        try:
            logger.info(
                f"{year}-{month} ({variable}): Downloading {output_file.name}..."
            )

            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Download with streaming
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            # Get total file size
            total_size = int(response.headers.get("content-length", 0))
            size_mb = total_size / (1024**2)

            logger.info(f"{year}-{month} ({variable}): File size: {size_mb:.2f} MB")

            # Download with progress tracking using tqdm
            progress_bar = tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                desc=f"{year}-{month} ({variable})",
                unit_divisor=1024,
            )

            with open(output_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):  # 8KB chunks
                    if chunk:
                        f.write(chunk)
                        progress_bar.update(len(chunk))
            progress_bar.close()

            logger.info(
                f"{year}-{month} ({variable}): Successfully downloaded to {output_file}"
            )
            return 1

        except requests.exceptions.RequestException as e:
            logger.error(f"{year}-{month} ({variable}): Download failed: {e}")
            # Clean up partial file
            if output_file.exists():
                output_file.unlink()
            return 0
        except Exception as e:
            logger.error(f"{year}-{month} ({variable}): Error: {e}")
            if output_file.exists():
                output_file.unlink()
            return 0

    def _build_opendap_url(self, year: int, month: str, variable: str) -> str:
        """Build OPeNDAP URL for a specific file on the NCI THREDDS server.

        The URL structure follows the NCI THREDDS catalog layout for BARRA2 data.

        Args:
            year (int): Year as integer.
            month (str): Month as string (01-12).
            variable (str): Variable name.

        Returns:
            str: Full OPeNDAP URL for accessing the file.
        """
        base_url = str(self.config["opendap_url"]).replace("/dodsC/", "/fileServer/")
        barra2_code = self._get_barra2_param(variable)
        grid = str(self.config["grid"])
        dataset_label = str(self.config["label"])

        if barra2_code in INVARIANT_VARIABLES:
            invariant_path = str(self.config.get("invariant_path", "fx"))
            dataset_file = (
                f"{barra2_code}_{grid}_ERA5_historical_hres_BOM_{dataset_label}_v1.nc"
            )
            url = f"{base_url}/{invariant_path}/{barra2_code}/latest/{dataset_file}"
        else:
            year_month = f"{year}{month}"
            dataset_file = (
                f"{barra2_code}_{grid}_ERA5_historical_hres_BOM_"
                f"{dataset_label}_v1_{self.temporal_res}_{year_month}-{year_month}.nc"
            )
            url = f"{base_url}/{self.temporal_res}/{barra2_code}/latest/{dataset_file}"
        return url

    def _construct_file_path(self, year: int, month: str, variable: str) -> Path:
        """Construct the local file path for a BARRA2 data file.

        Args:
            year (int): Year as integer.
            month (str): Month as string (01-12).
            variable (str): Variable name.

        Returns:
            Path: Full local file path for the data file.
        """
        barra2_code = self._get_barra2_param(variable)
        if barra2_code in INVARIANT_VARIABLES:
            filename = f"barra2_{self.model}_fx_{barra2_code}.nc"
            return Path(self.invariant_output_path, filename)
        else:
            filename = f"barra2_{self.model}_{self.temporal_res}_{year}{month}_{barra2_code}.nc"
            return Path(self.output_path, filename)

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

            single_level_vars = [
                name
                for name, code in sorted(VARIABLE_TO_BARRA2_PARAM.items())
                if code in single_level_codes
            ]
            pressure_level_vars = [
                name
                for name, code in sorted(VARIABLE_TO_BARRA2_PARAM.items())
                if code in pressure_level_codes
            ]
            invariant_vars = [
                name
                for name, code in sorted(VARIABLE_TO_BARRA2_PARAM.items())
                if code in INVARIANT_VARIABLES
            ]

            single_level_lines = "\n".join(
                (
                    f"  - {name} ({VARIABLE_TO_BARRA2_PARAM[name]})"
                    f"{' [DEFAULT]' if name in DEFAULT_VARIABLES else ''}"
                )
                for name in single_level_vars
            )
            pressure_level_lines = "\n".join(
                (
                    f"  - {name} ({VARIABLE_TO_BARRA2_PARAM[name]})"
                    f"{' [DEFAULT]' if name in DEFAULT_VARIABLES else ''}"
                )
                for name in pressure_level_vars
            )
            invariant_lines = "\n".join(
                f"  - {name} ({VARIABLE_TO_BARRA2_PARAM[name]})"
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
