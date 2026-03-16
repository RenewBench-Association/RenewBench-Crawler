"""ICON-DREAM NWP data downloader.

Download ICON-DREAM reanalysis data (Global or EU) from DWD open data portal.
"""

import pickle
import re
from pathlib import Path
from typing import Optional

import requests
from loguru import logger
from tqdm import tqdm

from rbc.weather.icon_dream.mappings import (
    ALL_MODEL_LEVEL_VARIABLES,
    ALL_SINGLE_LEVEL_VARIABLES,
    DEFAULT_VARIABLES,
    MODEL_CONFIG,
    VARIABLE_TO_DWD_PARAM,
)


def _normalize_region(region: str) -> str:
    region_key = region.strip().lower()
    if region_key == "europe":
        return "eu"
    return region_key


def _get_region_config(region: str) -> dict:
    if region not in MODEL_CONFIG:
        raise ValueError(
            f"Unknown region '{region}'. Choose from: {', '.join(MODEL_CONFIG)}"
        )
    return MODEL_CONFIG[region]


class IconDreamDownloader:
    """ICON-DREAM NWP data downloader.

    Downloads hourly ICON-DREAM weather data from DWD open data portal.

    Attributes:
        region (str): Region identifier ("global" or "eu").
        years (list[int]): List of years to download data for.
        months (list[str]): List of months to download data for (01-12).
        variables (list[str]): List of variables to download.
        output_path (Path): Path to the output directory.
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (np.ndarray): Array tracking download status (0=not done, 1=done).
        dry_run (bool): If True, print requests without downloading.
        resume (bool): If True, resume from previous checkpoint.
        available_variables (set[str]): Set of available variables from DWD.
        available_dates (dict): Dict of variables to available year-months.
    """

    def __init__(
        self,
        output_path: Path,
        years: list[int],
        months: Optional[list[str]] = None,
        variables: Optional[list[str]] = None,
        region: str = "global",
        dry_run: bool = False,
        resume: bool = True,
    ) -> None:
        """Initialize the IconDreamDownloader.

        Args:
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to download.
            months (list[str], optional): List of months (01-12). Defaults to all months.
            variables (list[str], optional): List of variables. Defaults to common variables.
            region (str, optional): Region ("global" or "eu"). Defaults to "global".
            dry_run (bool, optional): If True, print requests without downloading. Defaults to False.
            resume (bool, optional): If True, resume from checkpoint. Defaults to False.

        Raises:
            ValueError: If invalid parameters are provided.
        """
        self.region = _normalize_region(region)
        self.region_config = _get_region_config(self.region)
        self.years = years
        self.months = (
            months if months is not None else [f"{i:02d}" for i in range(1, 13)]
        )
        self.variables = variables if variables is not None else DEFAULT_VARIABLES
        self.dry_run = dry_run
        self.resume = resume

        self.output_path = Path(output_path)
        self.checkpoint_path = Path(self.output_path, "status.pickle")

        # Create output directory if it doesn't exist
        self.output_path.mkdir(parents=True, exist_ok=True)

        dry_run_str = " [DRY RUN - NO DATA WILL BE DOWNLOADED]" if self.dry_run else ""
        logger.info(
            f"ICON-DREAM Downloader initialized for:{dry_run_str}"
            f"\n- region:\t\t{self.region}"
            f"\n- years:\t\t{years}"
            f"\n- months:\t\t{self.months}"
            f"\n- variables:\t\t{self.variables}"
        )

        # Discover available data from DWD
        logger.info("Discovering available data from DWD...")
        self.available_variables = self._discover_available_variables()
        logger.info(f"Found {len(self.available_variables)} available variables")

        # Validate variables
        self._validate_variables()

        # Initialize or load checkpoint
        if resume and self.checkpoint_path.is_file():
            with open(self.checkpoint_path, "rb") as f:
                self.checkpoint = pickle.load(f)
            logger.info(f"Resuming from checkpoint: {self.checkpoint_path}")
        else:
            self.checkpoint = {}
            logger.info("Starting fresh download (no checkpoint found).")

    def _discover_available_variables(self) -> set[str]:
        """Discover available variables from DWD open data portal.

        Returns:
            set[str]: Set of available variable codes (e.g., {'T', 'U', 'V', 'T_2M', ...}).
        """
        try:
            # List directory to find available variables
            response = requests.get(self.region_config["base_url"], timeout=30)
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

        except Exception as e:
            logger.warning(f"Error discovering variables: {e}, using defaults")
            return ALL_MODEL_LEVEL_VARIABLES | ALL_SINGLE_LEVEL_VARIABLES

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
                f"Run 'print_available_variables()' to see available variables."
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

    def download_data(self) -> None:
        """Download ICON-DREAM data for all specified years, months, and variables."""
        for year in self.years:
            logger.info(f"Processing year {year}...")

            for month in self.months:
                for var in self.variables:
                    task = (year, month, var)

                    # check if task was previously run and was unsuccessful before (= 0)
                    if self.checkpoint.get(task, 0) == 0:
                        success_code = self._download_variables(
                            year=year, month=month, variable=var
                        )
                        if not self.dry_run:
                            self.checkpoint[task] = success_code
                            with open(self.checkpoint_path, "wb") as f:
                                pickle.dump(self.checkpoint, f)
                    else:
                        logger.info(
                            f"{year}-{month} ({var}): Data previously downloaded."
                        )

        logger.info("All downloads completed!")

    def _download_variables(self, year: int, month: str, variable: str) -> int:
        """Download a single data file.

        Args:
            year (int): Year to download.
            month (str): Month to download (format: '01' to '12').
            variable (str): Variable name (e.g., 'temperature', '2m_temperature').

        Returns:
            int: 1 if successful, 0 if failed.
        """
        # Translate variable name to DWD parameter code
        dwd_code = self._get_dwd_param(variable)

        # Build filename and URL
        filename = f"{self.region_config['label']}_{year}{month}_{dwd_code}_hourly.grb"
        url = f"{self.region_config['base_url']}/{dwd_code}/{filename}"
        output_file = Path(self.output_path, filename)

        # Check if file already exists
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
            logger.info(f"{year}-{month} ({variable}): Downloading {filename}...")

            # Download with streaming
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            # Get total file size
            total_size = int(response.headers.get("content-length", 0))
            size_gb = total_size / (1024**3)

            logger.info(f"{year}-{month} ({variable}): File size: {size_gb:.2f} GB")

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

    def download_metadata(self, dry_run: Optional[bool] = None) -> None:
        """Download ICON-DREAM grid metadata files.

        Downloads the grid definition and connectivity information for the
        selected ICON-DREAM region.

        Args:
            dry_run (bool, optional): If True, print download info without downloading.
                If None, uses the downloader's dry_run setting.
        """
        if dry_run is None:
            dry_run = self.dry_run

        metadata_dir = Path(self.output_path, "metadata")
        metadata_dir.mkdir(parents=True, exist_ok=True)

        metadata_files = self.region_config["metadata_files"]

        logger.info(f"Downloading {self.region_config['label']} metadata files...")
        logger.info(f"Metadata destination: {metadata_dir}")

        for filename, (url, description) in metadata_files.items():
            output_file = metadata_dir / filename

            if dry_run:
                logger.info(
                    f"Metadata DRY RUN: Would download {description} from {url}"
                )
                continue

            try:
                # Check if file already exists with the expected size
                if output_file.exists():
                    try:
                        head_response = requests.head(url, timeout=30)
                        head_response.raise_for_status()
                        remote_size = int(
                            head_response.headers.get("content-length", 0)
                        )
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

                # Download with streaming
                response = requests.get(url, stream=True, timeout=300)
                response.raise_for_status()

                # Get total file size
                total_size = int(response.headers.get("content-length", 0))
                size_mb = total_size / (1024**2)

                logger.info(f"Metadata: File size: {size_mb:.2f} MB")

                # Download with progress tracking using tqdm
                chunk_size = 8192  # 8KB chunks
                progress_bar = tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    desc=f"Metadata: {description}",
                    unit_divisor=1024,
                )

                with open(output_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            progress_bar.update(len(chunk))
                progress_bar.close()

                logger.info(
                    f"Metadata: Successfully downloaded {description} to {output_file}"
                )

            except requests.exceptions.RequestException as e:
                logger.error(f"Metadata: Download failed for {description}: {e}")
                # Clean up partial file
                if output_file.exists():
                    output_file.unlink()
            except Exception as e:
                logger.error(f"Metadata: Error downloading {description}: {e}")
                if output_file.exists():
                    output_file.unlink()

        logger.info("Metadata download completed!")

    @staticmethod
    def print_available_variables(region: str = "global") -> None:
        """Print all available ICON-DREAM variables for a region.

        Args:
            region (str): Region identifier ("global", "eu", or "all").
        """
        region_key = _normalize_region(region)
        regions = ["global", "eu"] if region_key == "all" else [region_key]

        for region_name in regions:
            region_config = _get_region_config(region_name)
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
                + f"\nAVAILABLE {region_config['label']} VARIABLES"
                + "\n"
                + "=" * 80
                + "\n\n--- SINGLE-LEVEL (2D) VARIABLES ---"
                + f"\nDataset: {region_config['dataset']}"
                + f"\nResolution: {region_config['resolution']}"
                + "\nTemporal: Hourly data"
                + "\nTime period: 2010-01 to present"
                + f"\nTotal: {len(ALL_SINGLE_LEVEL_VARIABLES)} variables\n"
                + single_level_lines
                + "\n\n--- MODEL-LEVEL (3D) VARIABLES ---"
                + f"\nDataset: {region_config['dataset']}"
                + f"\nResolution: {region_config['resolution']}"
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
            + "\n   python scripts/weather/icon_dream_download.py --region global -y 2020 -m 01 -v 2m_temperature surface_pressure"
            + "\n\n2. Download EU data without metadata:"
            + "\n   python scripts/weather/icon_dream_download.py --region eu -y 2020 -m 01 -v temperature --no-metadata"
            + "\n\n3. Download metadata for both regions:"
            + "\n   python scripts/weather/icon_dream_download.py"
            + "\n\n4. Download data for both regions:"
            + "\n   python scripts/weather/icon_dream_download.py --region all -y 2020 -m 01 -v temperature"
            + "\n"
            + "=" * 80
            + "\n"
        )
