"""ICON-DREAM NWP data downloader.

Download ICON-DREAM reanalysis data (Global or EU) from DWD open data portal.
"""

import re
from pathlib import Path

import requests
from loguru import logger

from rbc.weather.icon_dream.mappings import (
    ALL_MODEL_LEVEL_VARIABLES,
    ALL_SINGLE_LEVEL_VARIABLES,
    DEFAULT_VARIABLES,
    MODEL_CONFIG,
    VARIABLE_TO_DWD_PARAM,
)
from rbc.weather.utils import WeatherDownloader, download_file_streaming


def _normalize_model(model: str) -> str:
    """Normalize model name to internal ICON-DREAM model key.

    Args:
        model (str): Model name string (case-insensitive).

    Returns:
        str: Normalized model name ("global" or "eu").
    """
    model_key = model.strip().lower()
    if model_key == "europe":
        return "eu"
    return model_key


def _get_model_config(model: str) -> dict:
    """Return the configuration mapping for a normalized ICON-DREAM model.

    Args:
        model (str): Normalized model key.

    Returns:
        dict: Model-specific downloader configuration.

    Raises:
        ValueError: If the model is not defined in the model configuration.
    """
    if model not in MODEL_CONFIG:
        raise ValueError(
            f"Unknown model '{model}'. Choose from: {', '.join(MODEL_CONFIG)}"
        )
    return MODEL_CONFIG[model]


class IconDreamDownloader(WeatherDownloader):
    """ICON-DREAM NWP data downloader.

    Downloads hourly ICON-DREAM weather data from DWD open data portal.

    Attributes:
        available_variables (set[str]): Set of available variables from DWD.
        model (str): Model identifier ("global" or "eu").
        model_config (dict): Model-specific configuration from MODEL_CONFIG.

    """

    def __init__(
        self,
        output_path: Path,
        years: list[int],
        months: list[str] | None = None,
        variables: list[str] | None = None,
        model: str = "global",
        dry_run: bool = False,
        resume: bool = True,
    ) -> None:
        """Initialize the IconDreamDownloader.

        Args:
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to download.
            months (list[str], optional): List of months (01-12). Defaults to all months.
            variables (list[str], optional): List of variables. Defaults to common variables.
            model (str, optional): Model ("global" or "eu"). Defaults to "global".
            dry_run (bool, optional): If True, print requests without downloading. Defaults to False.
            resume (bool, optional): If True, resume from checkpoint. Defaults to True.

        Raises:
            ValueError: If the model is not defined in the model configuration.
            ValueError: If any requested variable is not in the known variable mapping or
                is not available on the DWD server.
            ConnectionError: If the DWD server is unreachable during variable discovery.
        """
        self.model = _normalize_model(model)
        self.model_config = _get_model_config(self.model)

        # Output path setup: append model subdirectory if not already present
        base_output_path = Path(output_path)
        resolved_output_path = (
            base_output_path
            if self.model in base_output_path.name
            else Path(base_output_path, self.model)
        )

        # Discover available data from DWD before calling super().__init__ so that
        # _validate_variables() (called after super) can use self.available_variables.
        logger.info("Discovering available data from DWD...")
        self.available_variables = self._discover_available_variables()
        logger.info(f"Found {len(self.available_variables)} available variables")

        resolved_variables = variables if variables is not None else DEFAULT_VARIABLES

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
            f"ICON-DREAM Downloader initialized for:{dry_run_str}"
            f"\n- model:\t\t{self.model_config['label']} ({self.model_config['resolution']})"
            f"\n- years:\t\t{self.years}"
            f"\n- months:\t\t{self.months}"
            f"\n- variables:\t\t{self.variables}"
        )

        self._validate_variables()

    def _get_tasks(self) -> list[tuple]:
        """Return all download tasks as (year, month, variable) tuples.

        Returns:
            list[tuple]: Ordered list of (year, month, variable) tuples.
        """
        logger.info(f"Starting ICON-DREAM {self.model_config['label']} download")
        return [
            (year, month, var)
            for year in self.years
            for month in self.months
            for var in self.variables
        ]

    def _download_task(self, task: tuple) -> int:
        """Download a single ICON-DREAM data file.

        Args:
            task (tuple): Task tuple of (year, month, variable).

        Returns:
            int: 1 if successful, 0 if failed.
        """
        year, month, variable = task
        return self._download_variables(year=year, month=month, variable=variable)

    def _download_variables(self, year: int, month: str, variable: str) -> int:
        """Download a single data file.

        Args:
            year (int): Year to download.
            month (str): Month to download (format: '01' to '12').
            variable (str): Variable name (e.g., 'temperature', '2m_temperature').

        Returns:
            int: 1 if successful, 0 if failed.
        """
        dwd_code = self._get_dwd_param(variable)
        filename = f"{self.model_config['label']}_{year}{month}_{dwd_code}_hourly.grb"
        url = f"{self.model_config['base_url']}/{dwd_code}/{filename}"
        output_file = Path(self.output_path, filename)
        description = f"{year}-{month} ({variable})"

        if output_file.exists():
            logger.info(f"{description}: File already exists locally, skipping")
            return 1

        if self.dry_run:
            logger.info(f"{description}: DRY RUN - Would download from {url}")
            return 1

        logger.info(f"{description}: Downloading {filename}...")
        return download_file_streaming(
            url=url, output_file=output_file, description=description
        )

    def download_metadata(self, dry_run: bool | None = None) -> None:
        """Download ICON-DREAM grid metadata files.

        Downloads the grid definition and connectivity information for the
        selected ICON-DREAM model.

        Args:
            dry_run (bool, optional): If True, print download info without downloading.
                If None, uses the downloader's dry_run setting.
        """
        if dry_run is None:
            dry_run = self.dry_run

        metadata_dir = Path(self.output_path, "metadata")
        metadata_dir.mkdir(parents=True, exist_ok=True)

        metadata_files = self.model_config["metadata_files"]

        logger.info(f"Downloading {self.model_config['label']} metadata files...")
        logger.info(f"Metadata destination: {metadata_dir}")

        for filename, (url, description) in metadata_files.items():
            output_file = metadata_dir / filename

            if dry_run:
                logger.info(
                    f"Metadata DRY RUN: Would download {description} from {url}"
                )
                continue

            # Check if file already exists with the expected size
            if output_file.exists():
                try:
                    head_response = requests.head(url, timeout=30)
                    head_response.raise_for_status()
                    remote_size = int(head_response.headers.get("content-length", 0))
                    local_size = output_file.stat().st_size

                    if remote_size > 0 and local_size == remote_size:
                        logger.info(
                            f"Metadata: {description} ({filename}) already exists with matching size, skipping"
                        )
                        continue

                    logger.info(
                        f"Metadata: {description} ({filename}) exists but size differs, re-downloading"
                    )
                except requests.exceptions.RequestException as e:
                    logger.warning(
                        f"Metadata: Could not verify size for {description} ({filename}): {e}. "
                        "Keeping existing file and skipping download."
                    )
                    continue

            logger.info(f"Metadata: Downloading {description} ({filename})...")
            status = download_file_streaming(
                url=url,
                output_file=output_file,
                description=f"Metadata: {description}",
            )
            if status == 0:
                logger.error(f"Metadata: Download failed for {description}")

        logger.info("Metadata download completed!")

    # --------------------------------------------
    # Helper methods
    # --------------------------------------------
    def _validate_variables(self) -> None:
        """Validate that all requested variables are available.

        Raises:
            ValueError: If any requested variable is not available.
        """
        # Check that all requested variables exist in our mapping
        invalid_vars = [v for v in self.variables if v not in VARIABLE_TO_DWD_PARAM]

        if invalid_vars:
            raise ValueError(
                f"Invalid variables: {', '.join(invalid_vars)}. \n"
                f"Run 'python scripts/weather/icon_dream_download.py --list-variables --model {self.model}' to see available variables."
            )

        # Check that the DWD codes are available on the server
        unavailable_vars = [
            v
            for v in self.variables
            if self._get_dwd_param(v) not in self.available_variables
        ]

        if unavailable_vars:
            dwd_codes = [self._get_dwd_param(v) for v in unavailable_vars]
            raise ValueError(
                f"Variables not available on DWD server: {', '.join(unavailable_vars)} "
                f"(DWD codes: {', '.join(dwd_codes)})"
            )

        logger.info(f"All {len(self.variables)} requested variables are available.")

    def _discover_available_variables(self) -> set[str]:
        """Discover available variables from DWD open data portal.

        Returns:
            set[str]: Set of available variable codes (e.g., {'T', 'U', 'V', 'T_2M', ...}).

        Raises:
            ConnectionError: If the DWD server is unreachable.
        """
        try:
            # List directory to find available variables
            response = requests.get(self.model_config["base_url"], timeout=30)
            response.raise_for_status()

            # Extract variable folder names from HTML directory listing
            # Looking for links like: <a href="T/">T/</a>
            pattern = r'href="([A-Z0-9_]+)/"'
            matches = re.findall(pattern, response.text)
            # Filter out parent directory (..)
            variables = set(m for m in matches if m != "..")

            if not variables:
                logger.warning("No variables found in DWD directory, using defaults")
                return ALL_MODEL_LEVEL_VARIABLES | ALL_SINGLE_LEVEL_VARIABLES

            logger.info(f"Discovered {len(variables)} available variables from DWD")
            return variables

        except requests.exceptions.ConnectionError as e:
            logger.error("Initialization ICON-DREAM connectivity check failed!")
            raise ConnectionError(f"DWD server unreachable: {e}")
        except Exception as e:
            logger.warning(f"Error discovering variables: {e}, using defaults")
            return ALL_MODEL_LEVEL_VARIABLES | ALL_SINGLE_LEVEL_VARIABLES

    @staticmethod
    def _get_dwd_param(variable: str) -> str:
        """Convert variable name to DWD parameter code.

        Args:
            variable (str): ICON-DREAM variable name

        Returns:
            str: DWD parameter code
        """
        if variable in VARIABLE_TO_DWD_PARAM:
            return VARIABLE_TO_DWD_PARAM[variable]
        # Fallback: use variable name directly
        return variable

    @staticmethod
    def print_available_variables(model: str = "global") -> None:
        """Print all available ICON-DREAM variables for a model.

        Args:
            model (str): Model identifier ("global", "eu", or "all").
        """
        model_key = _normalize_model(model)
        models = ["global", "eu"] if model_key == "all" else [model_key]

        for model_name in models:
            model_config = _get_model_config(model_name)
            single_level_lines = "\n".join(
                (f"  - {name}{' [DEFAULT]' if name in DEFAULT_VARIABLES else ''}")
                for name, code in sorted(VARIABLE_TO_DWD_PARAM.items())
                if code in ALL_SINGLE_LEVEL_VARIABLES
            )
            model_level_lines = "\n".join(
                (f"  - {name}{' [DEFAULT]' if name in DEFAULT_VARIABLES else ''}")
                for name, code in sorted(VARIABLE_TO_DWD_PARAM.items())
                if code in ALL_MODEL_LEVEL_VARIABLES
            )

            logger.info(
                "\n"
                + "=" * 80
                + f"\nAVAILABLE {model_config['label']} VARIABLES"
                + "\n"
                + "=" * 80
                + "\n\n--- SINGLE-LEVEL (2D) VARIABLES ---"
                + f"\nDataset: {model_config['dataset']}"
                + f"\nResolution: {model_config['resolution']}"
                + "\nTemporal: Hourly data"
                + "\nTime period: 2010-01 to present"
                + f"\nTotal: {len(ALL_SINGLE_LEVEL_VARIABLES)} variables\n"
                + single_level_lines
                + "\n\n--- MODEL-LEVEL (3D) VARIABLES ---"
                + f"\nDataset: {model_config['dataset']}"
                + f"\nResolution: {model_config['resolution']}"
                + "\nTemporal: Hourly data"
                + "\nTime period: 2010-01 to present"
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
            + "\n\n1. Download data with metadata (default):"
            + "\n   python scripts/weather/icon_dream_download.py --model global -y 2020 -m 01 -v 2m_temperature surface_pressure"
            + "\n\n2. Download EU data without metadata:"
            + "\n   python scripts/weather/icon_dream_download.py --model eu -y 2020 -m 01 -v temperature --no-metadata"
            + "\n\n3. Download metadata for both models:"
            + "\n   python scripts/weather/icon_dream_download.py"
            + "\n\n4. Download data for both models:"
            + "\n   python scripts/weather/icon_dream_download.py --model all -y 2020 -m 01 -v temperature"
            + "\n"
            + "=" * 80
            + "\n"
        )
