"""BARRA REANALYSIS DATA DOWNLOADER.

Download BARRA reanalysis data (R2, RE2, or C2) from NCI THREDDS server.
"""

import pickle
import re
from pathlib import Path
from typing import Any

import requests
from loguru import logger
from tqdm import tqdm

from rbc.weather.barra.mappings import (
    ALL_VARIABLES_C2,
    ALL_VARIABLES_R2_RE2,
    DEFAULT_VARIABLES_C2,
    DEFAULT_VARIABLES_R2_RE2,
    MODEL_CONFIG,
    VARIABLE_AVAILABILITY,
)


def _normalize_model(model: str) -> str:
    """Normalize model name to standard uppercase form.

    Args:
        model (str): Model name string (case-insensitive).

    Returns:
        str: Normalized model name ("R2", "RE2", or "C2").

    Raises:
        ValueError: If the model name is not recognized.
    """
    model_key = model.strip().upper()
    if model_key not in MODEL_CONFIG:
        raise ValueError(
            f"Unknown BARRA model '{model}'. "
            f"Choose from: {', '.join(MODEL_CONFIG.keys())}"
        )
    return model_key


class BarraDownloader:
    """BARRA reanalysis data downloader.

    Downloads BARRA NWP reanalysis data from NCI THREDDS server.
    Supports three models: R2 (11 km), RE2 (22 km), C2 (4 km).
    Data is always downloaded at 1-hour temporal frequency.

    Attributes:
        model (str): Model identifier ("R2", "RE2", or "C2").
        config (dict): Model-specific configuration from MODEL_CONFIG.
        temporal_res (str): Temporal resolution, fixed to "1hr".
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
        dry_run: bool = False,
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            output_path (Path): Directory to save downloaded data.
            model (str): BARRA model identifier ("R2", "RE2", or "C2").
            years (list[int]): List of years to download.
            months (list[str] | None, optional): List of months (01-12).
                Defaults to all months.
            variables (list[str] | None, optional): Variables to download.
                Defaults to model-specific defaults.
            pressure_levels (list[int] | None, optional): Pressure levels for
                3D variables (in hPa). Defaults to model-specific defaults.
            dry_run (bool, optional): If True, print requests without downloading.
                Defaults to False.
            resume (bool, optional): If True, resume from checkpoint.
                Defaults to True.

        Raises:
            ValueError: If model name is not recognized.
        """
        self.output_path = Path(output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)

        self.model = _normalize_model(model)
        self.config = MODEL_CONFIG[self.model]
        self.temporal_res = "1hr"  # Fixed to 1-hour frequency
        self.years = sorted(years)
        self.months: list[str] = months or [f"{i:02d}" for i in range(1, 13)]
        self.dry_run = dry_run
        self.resume = resume

        # Setup available variables based on model
        if self.model in ["R2", "RE2"]:
            self.available_variables = ALL_VARIABLES_R2_RE2
        else:  # C2
            self.available_variables = ALL_VARIABLES_C2

        # Setup variables (use model-specific defaults if none provided)
        if variables is None:
            self.variables: list[str] = list(
                self.config["default_vars"],  # type: ignore[arg-type]
            )
        else:
            self.variables = variables

        # Setup pressure levels (use model-specific defaults if none provided)
        if pressure_levels is None:
            self.pressure_levels = self.config["pressure_levels"]
        else:
            self.pressure_levels = pressure_levels

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

    def _validate_variables(self) -> None:
        """Validate that requested variables are available for this model.

        Logs a warning for each variable that may not be available. Pressure-level
        variables (e.g. "ta500") are always accepted.

        Raises:
            ValueError: If any requested variable is not recognized at all.
        """
        pressure_level_bases = ["ta", "ua", "va", "hus", "wap", "zg", "wa"]
        invalid_vars = []

        for var in self.variables:
            # Pressure-level suffixed variables are always valid
            if any(
                var.startswith(base) and var != base for base in pressure_level_bases
            ):
                continue

            if var not in self.available_variables and var not in VARIABLE_AVAILABILITY:
                invalid_vars.append(var)

        if invalid_vars:
            raise ValueError(
                f"Invalid variables for BARRA-{self.model}: "
                f"{', '.join(invalid_vars)}.\n"
                f"Run 'python scripts/weather/barra_download.py "
                f"--list-variables --model {self.model}' to see available variables."
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
        filename = f"barra_{self.model}_{year}{month}_{variable}.nc"
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
        base_url = self.config["opendap_url"]
        year_month = f"{year}{month}"
        url = f"{base_url}/1hr/{year_month}/{variable}.nc"
        return url

    def discover_variables(self) -> dict[str, dict[str, Any]]:
        """Discover available variables from THREDDS catalog.

        Parses the NCI THREDDS HTML catalog to find available variables and their
        metadata for the configured model.

        Returns:
            dict[str, dict[str, Any]]: Dict mapping variable names to
                availability info (temporal_res, available).
        """
        logger.info("Discovering variables from THREDDS catalog...")

        try:
            catalog_url = str(self.config["catalog_url"])
            response = requests.get(catalog_url, timeout=30)
            response.raise_for_status()

            variables_info = self._parse_thredds_catalog(response.text)

            logger.info(
                f"Found {len(variables_info)} available variables "
                f"for {self.config['label']}"
            )
            return variables_info

        except Exception as e:
            logger.error(f"Failed to discover variables: {e}")
            return {}

    def _parse_thredds_catalog(self, html_content: str) -> dict[str, dict]:
        """Parse THREDDS HTML catalog to extract variable names.

        Args:
            html_content (str): HTML content from THREDDS catalog page.

        Returns:
            dict[str, dict]: Dictionary of available variables and their metadata.
        """
        variables_info: dict[str, dict] = {}

        # Pattern to match NetCDF files in THREDDS catalog
        # Typical format: BARRA_R2_YYYY_MM_VARIABLE.nc
        pattern = r"BARRA_[A-Z0-9]+_\d{6}_([a-zA-Z0-9_]+)\.nc"

        for match in re.finditer(pattern, html_content):
            var_name = match.group(1)
            variables_info[var_name] = {
                "temporal_res": self.temporal_res,
                "available": True,
            }

        return variables_info

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
            model (str): Model identifier ("R2", "RE2", "C2", or "all").
        """
        models = (
            list(MODEL_CONFIG.keys())
            if model.lower() == "all"
            else [_normalize_model(model)]
        )

        for idx, model_name in enumerate(models):
            config = MODEL_CONFIG[model_name]
            if model_name in ["R2", "RE2"]:
                all_vars = ALL_VARIABLES_R2_RE2
                default_vars = DEFAULT_VARIABLES_R2_RE2
            else:
                all_vars = ALL_VARIABLES_C2
                default_vars = DEFAULT_VARIABLES_C2

            if idx:
                print("\n")
            print("\n" + "=" * 80)
            print(f"AVAILABLE BARRA-{model_name} VARIABLES")
            print("=" * 80)
            print(f"Dataset: {config['description']}")
            print(f"Resolution: {config['resolution']}")
            print("Temporal: 1-hourly data")
            print(f"Total: {len(all_vars)} variables\n")

            for var in sorted(all_vars):
                marker = " [DEFAULT]" if var in default_vars else ""
                print(f"  • {var}{marker}")

        print("\n" + "=" * 80)
        print("USAGE EXAMPLES:")
        print("=" * 80)
        print("\n1. Download default variables for R2 model:")
        print("   python scripts/weather/barra_download.py --model R2 -y 2020 2021\n")
        print("2. Download specific variables for C2:")
        print(
            "   python scripts/weather/barra_download.py "
            "-m C2 -y 2022 -v tas uas vas CAPE\n"
        )
        print("3. Dry run to see what would be downloaded:")
        print(
            "   python scripts/weather/barra_download.py "
            "--model R2 -y 2020 --months 01 02 --dry-run\n"
        )
        print("=" * 80 + "\n")
