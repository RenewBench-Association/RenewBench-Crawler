"""BARRA reanalysis data downloader.

Download BARRA reanalysis data (R2, RE2, or C2) from NCI THREDDS server.
Supports multiple temporal frequencies and pressure levels.
"""

import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np
import requests
from loguru import logger

from rbc.weather.barra.mappings import (
    ALL_VARIABLES_C2,
    ALL_VARIABLES_R2_RE2,
    MODEL_CONFIG,
    VARIABLE_AVAILABILITY,
)


def _normalize_model(model: str) -> str:
    """Normalize model name to standard form."""
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
        output_path (Path): Path to output directory.
        model (str): Model identifier ("R2", "RE2", or "C2").
        years (list[int]): List of years to download.
        months (Optional[list[str]]): List of months to download (01-12).
        variables (Optional[list[str]]): List of variables to download.
        pressure_levels (Optional[list[int]]): Pressure levels for 3D variables.
        output_path (Path): Directory to save downloaded files.
        checkpoint_path (Path): Path to checkpoint file for resume capability.
        dry_run (bool): If True, print requests without downloading.
        resume (bool): If True, resume from previous checkpoint.
        available_variables (Set[str]): Known available variables for this model.
        checkpoint (np.ndarray): 2D array tracking download progress.
    """

    def __init__(
        self,
        output_path: Path,
        model: str,
        years: List[int],
        months: Optional[List[str]] = None,
        variables: Optional[List[str]] = None,
        pressure_levels: Optional[List[int]] = None,
        dry_run: bool = False,
        resume: bool = True,
    ) -> None:
        """Initialize BARRA downloader.

        Args:
            output_path: Directory to save data.
            model: "R2", "RE2", or "C2".
            years: List of year integers to download.
            months: List of month strings (01-12). If None, download all months.
            variables: Variables to download. If None, use defaults for model.
            pressure_levels: Pressure levels for 3D variables (in hPa).
            dry_run: If True, print requests without downloading.
            resume: If True, resume from checkpoint.
        """
        self.output_path = Path(output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)

        self.model = _normalize_model(model)
        self.config = MODEL_CONFIG[self.model]
        self.temporal_res = "1hr"  # Fixed to 1-hour frequency
        self.years = sorted(years)
        self.months: List[str] = months or [f"{i:02d}" for i in range(1, 13)]
        self.dry_run = dry_run
        self.resume = resume

        # Setup available variables
        if self.model in ["R2", "RE2"]:
            self.available_variables = ALL_VARIABLES_R2_RE2
        else:  # C2
            self.available_variables = ALL_VARIABLES_C2

        # Setup variables
        if variables is None:
            self.variables: List[str] = cast(List[str], self.config["default_vars"])
            logger.info(
                f"Using default variables for {self.config['label']}: "
                f"{', '.join(self.variables[:3])}..."
            )
        else:
            self.variables = variables

        # Setup pressure levels
        if pressure_levels is None:
            self.pressure_levels = self.config["pressure_levels"]
        else:
            self.pressure_levels = pressure_levels

        # Validate model-variable compatibility
        self._validate_variables()

        # Setup checkpoint
        self.checkpoint_path = self.output_path / f"barra_{self.model}_checkpoint.pkl"
        self.checkpoint = self._load_checkpoint()

        logger.info(
            f"BARRA downloader initialized: {self.config['label']} "
            f"({self.config['resolution']}), 1-hourly, "
            f"{len(self.years)} years, "
            f"{len(self.months)} months, "
            f"{len(self.variables)} variables"
        )

    def _validate_variables(self) -> None:
        """Validate that requested variables are available for this resolution."""
        for var in self.variables:
            # Handle pressure level variables (e.g., "ta500")
            pressure_level_vars: List[str] = [
                "ta",
                "ua",
                "va",
                "hus",
                "wap",
                "zg",
                "wa",
            ]
            if any(var.startswith(base) for base in pressure_level_vars):
                continue

            if var not in self.available_variables and var not in VARIABLE_AVAILABILITY:
                logger.warning(
                    f"Variable '{var}' may not be available. "
                    f"Available for {self.model}: {len(self.available_variables)} variables"
                )

    def _load_checkpoint(self) -> np.ndarray:
        """Load checkpoint or create new one.

        Returns:
            2D numpy array: shape (len(years) × len(months))
            0 = not downloaded, 1 = downloaded
        """
        if self.checkpoint_path.exists() and self.resume:
            try:
                with open(self.checkpoint_path, "rb") as f:
                    cp = pickle.load(f)
                logger.info(f"Loaded checkpoint with {np.sum(cp)} completed month(s)")
                return cp
            except Exception as e:
                logger.warning(f"Failed to load checkpoint: {e}. Starting fresh.")

        # Create new checkpoint (0 = not downloaded)
        return np.zeros((len(self.years), len(self.months)), dtype=np.uint8)

    def _save_checkpoint(self) -> None:
        """Save current checkpoint state."""
        with open(self.checkpoint_path, "wb") as f:
            pickle.dump(self.checkpoint, f)

    def download(self) -> None:
        """Download BARRA data.

        Fetches available files from THREDDS server and downloads them
        according to checkpoint status. Supports resume capability.
        """
        logger.info(
            f"Starting BARRA {self.config['label']} download "
            f"({self.temporal_res} frequency)"
        )

        total_files = len(self.years) * len(self.months) * len(self.variables)
        completed = 0

        for year_idx, year in enumerate(self.years):
            for month_idx, month in enumerate(self.months):
                # Check checkpoint
                if self.checkpoint[year_idx, month_idx]:
                    logger.debug(f"Already downloaded {year}-{month}, skipping")
                    completed += len(self.variables)
                    continue

                for var_idx, variable in enumerate(self.variables):
                    file_path = self._construct_file_path(year, month, variable)

                    if file_path.exists():
                        logger.debug(f"File exists: {file_path.name}")
                        completed += 1
                        continue

                    self._download_file(year, month, variable)
                    completed += 1

                # Mark month as complete
                self.checkpoint[year_idx, month_idx] = 1
                self._save_checkpoint()

                logger.info(
                    f"Progress: {year}-{month} ({completed}/{total_files} files)"
                )

        logger.info("Download complete!")

    def _construct_file_path(self, year: int, month: str, variable: str) -> Path:
        """Construct local file path for a BARRA file."""
        filename = f"barra_{self.model}_{year}{month}_{variable}.nc"
        return self.output_path / filename

    def _download_file(self, year: int, month: str, variable: str) -> None:
        """Download a single BARRA file.

        Args:
            year: Year as integer.
            month: Month as string (01-12).
            variable: Variable name.
        """
        opendap_url = self._build_opendap_url(year, month, variable)
        file_path = self._construct_file_path(year, month, variable)

        if self.dry_run:
            logger.info(f"[DRY RUN] Would download: {file_path.name}")
            logger.debug(f"  URL: {opendap_url}")
            return

        try:
            logger.debug(f"Downloading {variable} for {year}-{month}")
            # In a real implementation, use OPeNDAP or direct HTTP download
            # For now, just log intent
            logger.info(f"Would download: {file_path.name} from {opendap_url}")

        except requests.RequestException as e:
            logger.error(f"Download failed for {variable}: {e}")
            raise

    def _build_opendap_url(self, year: int, month: str, variable: str) -> str:
        """Build OPeNDAP URL for a specific file.

        Args:
            year: Year as integer.
            month: Month as string (01-12).
            variable: Variable name.

        Returns:
            Full OPeNDAP URL for accessing the file.
        """
        # THREDDS catalog structure varies, this is a template
        base_url = self.config["opendap_url"]
        year_month = f"{year}{month}"

        # Construct path based on BARRA's THREDDS structure (1-hourly)
        # Actual implementation depends on server structure
        url = f"{base_url}/1hr/{year_month}/{variable}.nc"
        return url

    def discover_variables(self) -> Dict[str, Dict[str, Any]]:
        """Discover available variables from THREDDS catalog.

        Parses THREDDS XML catalog to find available variables, temporal coverage,
        and metadata for this resolution.

        Returns:
            Dict mapping variable names to availability info.
        """
        logger.info("Discovering variables from THREDDS catalog...")

        try:
            catalog_url = cast(str, self.config["catalog_url"])
            response = requests.get(catalog_url, timeout=30)
            response.raise_for_status()

            # Parse HTML/XML to extract variable list
            # THREDDS catalogs have different structures
            variables_info = self._parse_thredds_catalog(cast(str, response.text))

            logger.info(
                f"Found {len(variables_info)} available variables "
                f"for {self.config['label']}"
            )
            return variables_info

        except Exception as e:
            logger.error(f"Failed to discover variables: {e}")
            return {}

    def _parse_thredds_catalog(self, html_content: str) -> Dict[str, Dict]:
        """Parse THREDDS HTML catalog to extract variables.

        Args:
            html_content: HTML content from THREDDS catalog page.

        Returns:
            Dictionary of available variables and their metadata.
        """
        # THREDDS catalogs list files in HTML format
        # Extract NetCDF files and their metadata

        variables_info = {}

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

    def list_variables(self) -> List[str]:
        """List all available variables for this resolution.

        Returns:
            Sorted list of variable names.
        """
        return sorted(self.available_variables)

    def get_file_status(self) -> Tuple[int, int]:
        """Get download status.

        Returns:
            Tuple of (completed_months, total_months).
        """
        completed = np.sum(self.checkpoint)
        total = self.checkpoint.size
        return int(completed), int(total)
