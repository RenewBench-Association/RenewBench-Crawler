"""BARRA REANALYSIS DATA DOWNLOADER.

Download BARRA2 reanalysis data (R2, C2, or C2_20min) from National Computational Infrastructure (NCI) THREDDS server.
"""

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
    VARIABLE_TO_BARRA_PARAM,
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
            f"Unknown BARRA model '{model}'. "
            f"Choose from: {', '.join(MODEL_CONFIG.keys())}"
        )
    return normalized_lookup[model_key]


class BarraDownloader:
    """BARRA reanalysis data downloader.

    Downloads BARRA2 NWP reanalysis data from NCI THREDDS server.
    Supports three model keys: R2 (11 km, 1 hr), C2 (4 km, 1 hr),
    and C2_20min (4 km, 20 min).

    Attributes:
        model (str): Model key ("R2", "C2", or "C2_20min").
        config (dict): Model-specific configuration from MODEL_CONFIG.
        temporal_res (str): Temporal resolution (from MODEL_CONFIG).
        years (list[int]): List of years to download.
        months (list[str]): List of months to download (01-12).
        variables (list[str]): List of variables to download.
        pressure_levels (list[int]): Pressure levels for 3D variables (hPa).
        available_variables (set[str]): Known available variables for this model.
        output_path (Path): Path to output directory.
        checkpoint_path (Path): Path to checkpoint file for resume capability.
        checkpoint (dict): Dict tracking download status per (year, month, variable).
        dry_run (bool): If True, print requests without downloading.
        resume (bool): If True, resume from previous checkpoint.
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
            model (str): BARRA model key ("R2", "C2", or "C2_20min").
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
            ValueError: If model name is not recognized.
        """
        self.model = _normalize_model(model)

        base_output_path = Path(output_path)
        if base_output_path.name == self.model:
            self.output_path = base_output_path
        else:
            self.output_path = base_output_path / self.model
        self.output_path.mkdir(parents=True, exist_ok=True)

        self.invariant_output_path = self.output_path / "invariant"

        self.config = MODEL_CONFIG[self.model]
        self.temporal_res: str = self.config["temporal_res"]

        self.years = sorted(years)
        self.months: list[str] = months or [f"{i:02d}" for i in range(1, 13)]
        self.include_invariants = include_invariants
        self.dry_run = dry_run
        self.resume = resume

        # Build available BARRA codes for selected model
        if self.model == "R2":
            available_codes = (
                R2_SINGLE_LEVEL_VARIABLES
                | R2_PRESSURE_LEVEL_VARIABLES
                | INVARIANT_VARIABLES
            )
        elif self.model == "C2":
            available_codes = (
                C2_SINGLE_LEVEL_VARIABLES
                | C2_PRESSURE_LEVEL_VARIABLES
                | INVARIANT_VARIABLES
            )
        else:
            available_codes = C2_20MIN_SINGLE_LEVEL_VARIABLES | INVARIANT_VARIABLES

        # Build set of descriptive names available for this model key
        self.available_variables = {
            name
            for name, code in VARIABLE_TO_BARRA_PARAM.items()
            if code in available_codes
        }

        # Setup variables (use defaults if none provided)
        if variables is None:
            base_variables: list[str] = list(DEFAULT_VARIABLES)
        else:
            base_variables = list(variables)

        if self.include_invariants:
            invariant_variable_names = sorted(
                [
                    name
                    for name, code in VARIABLE_TO_BARRA_PARAM.items()
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

        # Validate model-variable compatibility
        self._validate_variables()

        # Setup checkpoint
        self.checkpoint_path = self.output_path / "status.pickle"

        # Initialize or load checkpoint
        self.checkpoint: dict[tuple[int, str, str], int] = {}
        if resume and self.checkpoint_path.is_file():
            with open(self.checkpoint_path, "rb") as f:
                self.checkpoint = pickle.load(f)
            logger.info(f"Resuming from checkpoint: {self.checkpoint_path}")
        else:
            logger.info("Starting fresh download (no checkpoint found).")

        dry_run_str = " [DRY RUN - NO DATA WILL BE DOWNLOADED]" if self.dry_run else ""
        logger.info(
            f"BARRA Downloader initialized for:{dry_run_str}"
            f"\n- model:\t\t{self.config['label']} ({self.config['resolution']})"
            f"\n- years:\t\t{self.years}"
            f"\n- months:\t\t{self.months}"
            f"\n- variables:\t\t{self.variables}"
        )

    def _get_barra_param(self, variable: str) -> str:
        """Convert descriptive variable name to BARRA parameter code.

        Args:
            variable (str): Descriptive variable name (e.g. "10m_u_component_of_wind").

        Returns:
            str: BARRA parameter code (e.g. "uas").
        """
        if variable in VARIABLE_TO_BARRA_PARAM:
            return VARIABLE_TO_BARRA_PARAM[variable]
        # Fallback: use variable name directly (e.g. already a BARRA code)
        return variable

    def _validate_variables(self) -> None:
        """Validate that requested variables are available for this model.

        Checks that all requested variables exist in VARIABLE_TO_BARRA_PARAM
        and that the resolved BARRA codes are available for this model.

        Raises:
            ValueError: If any requested variable is not recognized or not
                available for this model.
        """
        # Check that all requested variables exist in our mapping
        invalid_vars = [v for v in self.variables if v not in VARIABLE_TO_BARRA_PARAM]

        if invalid_vars:
            raise ValueError(
                f"Invalid variables: {', '.join(invalid_vars)}.\n"
                f"Run 'python scripts/weather/barra_download.py "
                f"--list-variables --region {self.model}' to see available variables."
            )

        # Check that the BARRA codes are available for this model
        unavailable_vars = [
            v for v in self.variables if v not in self.available_variables
        ]

        if unavailable_vars:
            barra_codes = [self._get_barra_param(v) for v in unavailable_vars]
            raise ValueError(
                f"Variables not available for BARRA-{self.model}: "
                f"{', '.join(unavailable_vars)} "
                f"(BARRA codes: {', '.join(barra_codes)}).\n"
                f"Run 'python scripts/weather/barra_download.py "
                f"--list-variables --region {self.model}' to see available variables."
            )

    def download_data(self) -> None:
        """Download BARRA data for all specified years, months, and variables.

        Fetches files from NCI THREDDS server and downloads them according to
        checkpoint status. Supports resume capability.
        """
        logger.info(
            f"Starting BARRA {self.config['label']} download "
            f"({self.temporal_res} frequency)"
        )

        for year in self.years:
            logger.info(f"Processing year {year}...")

            for month in self.months:
                for variable in self.variables:
                    task = (year, month, variable)

                    # Check if task was previously completed
                    if self.checkpoint.get(task, 0) == 1:
                        logger.info(
                            f"{year}-{month} ({variable}): Data previously downloaded."
                        )
                        continue

                    success_code = self._download_variable(
                        year=year, month=month, variable=variable
                    )

                    self.checkpoint[task] = success_code
                    with open(self.checkpoint_path, "wb") as f:
                        pickle.dump(self.checkpoint, f)

        logger.info("All downloads completed!")

    def _construct_file_path(self, year: int, month: str, variable: str) -> Path:
        """Construct the local file path for a BARRA data file.

        Args:
            year (int): Year as integer.
            month (str): Month as string (01-12).
            variable (str): Variable name.

        Returns:
            Path: Full local file path for the data file.
        """
        barra_code = self._get_barra_param(variable)
        if barra_code in INVARIANT_VARIABLES:
            filename = f"barra_{self.model}_fx_{barra_code}.nc"
            return self.invariant_output_path / filename
        else:
            filename = (
                f"barra_{self.model}_{self.temporal_res}_{year}{month}_{barra_code}.nc"
            )
        return self.output_path / filename

    def _download_variable(self, year: int, month: str, variable: str) -> int:
        """Download a single BARRA data file from the NCI THREDDS server.

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
            return 1

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
            chunk_size = 8192  # 8KB chunks
            progress_bar = tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                desc=f"{year}-{month} ({variable})",
                unit_divisor=1024,
            )

            with open(output_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
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

        The URL structure follows the NCI THREDDS catalog layout for BARRA data.

        Args:
            year (int): Year as integer.
            month (str): Month as string (01-12).
            variable (str): Variable name.

        Returns:
            str: Full OPeNDAP URL for accessing the file.
        """
        base_url = str(self.config["opendap_url"]).replace("/dodsC/", "/fileServer/")
        barra_code = self._get_barra_param(variable)
        grid = str(self.config["grid"])
        dataset_label = str(self.config["label"])

        if barra_code in INVARIANT_VARIABLES:
            invariant_path = str(self.config.get("invariant_path", "fx"))
            dataset_file = (
                f"{barra_code}_{grid}_ERA5_historical_hres_BOM_{dataset_label}_v1.nc"
            )
            url = f"{base_url}/{invariant_path}/{barra_code}/latest/{dataset_file}"
        else:
            year_month = f"{year}{month}"
            dataset_file = (
                f"{barra_code}_{grid}_ERA5_historical_hres_BOM_"
                f"{dataset_label}_v1_{self.temporal_res}_{year_month}-{year_month}.nc"
            )
            url = f"{base_url}/{self.temporal_res}/{barra_code}/latest/{dataset_file}"
        return url

    def list_variables(self) -> list[str]:
        """List all available variables for this model.

        Returns:
            list[str]: Sorted list of variable names.
        """
        return sorted(self.available_variables)

    @staticmethod
    def print_available_variables(model: str = "R2") -> None:
        """Print all available BARRA variables for a model.

        Args:
            model (str): Model key ("R2", "C2", "C2_20min", or "all").
        """
        models = (
            list(MODEL_CONFIG.keys())
            if model.lower() == "all"
            else [_normalize_model(model)]
        )

        for idx, model_name in enumerate(models):
            config = MODEL_CONFIG[model_name]
            if model_name == "R2":
                available_codes = (
                    R2_SINGLE_LEVEL_VARIABLES
                    | R2_PRESSURE_LEVEL_VARIABLES
                    | INVARIANT_VARIABLES
                )
            elif model_name == "C2":
                available_codes = (
                    C2_SINGLE_LEVEL_VARIABLES
                    | C2_PRESSURE_LEVEL_VARIABLES
                    | INVARIANT_VARIABLES
                )
            else:
                available_codes = C2_20MIN_SINGLE_LEVEL_VARIABLES | INVARIANT_VARIABLES

            all_vars = {
                name
                for name, code in VARIABLE_TO_BARRA_PARAM.items()
                if code in available_codes
            }

            if idx:
                print("\n")
            print("\n" + "=" * 80)
            print(f"AVAILABLE BARRA-{model_name} VARIABLES")
            print("=" * 80)
            print(f"Dataset: {config['description']}")
            print(f"Resolution: {config['resolution']}")
            print(f"Temporal: {config['temporal_res']}")
            print(f"Total: {len(all_vars)} variables\n")

            for name in sorted(all_vars):
                code = VARIABLE_TO_BARRA_PARAM.get(name, name)
                marker = " [DEFAULT]" if name in DEFAULT_VARIABLES else ""
                print(f"  • {name} ({code}){marker}")

        print("\n" + "=" * 80)
        print("USAGE EXAMPLES:")
        print("=" * 80)
        print("\n1. Download default variables for R2 model:")
        print("   python scripts/weather/barra_download.py --region R2 -y 2020 2021\n")
        print("2. Download specific variables for C2:")
        print(
            "   python scripts/weather/barra_download.py "
            "-r C2 -y 2022 -v 1.5m_temperature 10m_u_component_of_wind 10m_v_component_of_wind CAPE\n"
        )
        print("3. Dry run to see what would be downloaded:")
        print(
            "   python scripts/weather/barra_download.py "
            "--region R2 -y 2020 --months 01 02 --dry-run\n"
        )
        print("=" * 80 + "\n")
