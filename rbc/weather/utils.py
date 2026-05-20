"""UTILS.

Shared helper functions and abstract base class for weather data downloaders.
"""

import datetime
import pickle
from abc import ABC, abstractmethod
from pathlib import Path

import requests
from loguru import logger
from tqdm import tqdm


class WeatherDownloader(ABC):
    """Abstract base class for weather data downloaders.

    Subclasses must implement `_get_tasks()`, `_download_task()`, and
    `_validate_variables()`. The `download_data()` loop, checkpoint
    loading/saving, and common attributes are handled here.

    Attributes:
        checkpoint (dict): Dict tracking download status per task tuple (1=done, 0=failed).
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        dry_run (bool): If True, skip actual downloads.
        months (list[str]): List of months to download (01-12).
        output_path (Path): Path to the output directory.
        resume (bool): If True, load an existing checkpoint on init.
        variables (list[str]): List of variables to download.
        years (list[int]): List of years to download.
    """

    def __init__(
        self,
        output_path: Path,
        years: list[int],
        months: list[str] | None,
        variables: list[str],
        dry_run: bool,
        resume: bool,
        start_year: int | None = None,
    ) -> None:
        """Initializes the instance.

        Args:
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to download.
            months (list[str] | None): List of months (01-12). If None, defaults to all months.
            variables (list[str]): List of variables to download.
            dry_run (bool): If True, skip actual downloads.
            resume (bool): If True, load an existing checkpoint on init.
            start_year (int | None): Earliest valid year for this data source. If provided,
                years before this value are silently filtered out and a warning is logged.
        """
        if start_year is not None:
            current_year = datetime.date.today().year
            filtered_years = [y for y in years if start_year <= y <= current_year]
            invalid_years = [y for y in years if y not in filtered_years]
            if invalid_years:
                logger.info(
                    f"Filtering out {len(invalid_years)} year(s) outside the valid range "
                    f"[{start_year}, {current_year}]: {invalid_years}"
                )
            years = filtered_years

        self.years = sorted(years)
        self.months = (
            months if months is not None else [f"{i:02d}" for i in range(1, 13)]
        )
        self.variables = variables
        self.dry_run = dry_run
        self.resume = resume

        self.output_path = Path(output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = Path(self.output_path, "status.pickle")

        self.checkpoint: dict = self._load_checkpoint()

    def download_data(self) -> None:
        """Download all tasks, skipping completed ones and checkpointing each result."""
        for task in self._get_tasks():
            if self.checkpoint.get(task, 0) == 1:
                logger.info(f"Task {task}: previously downloaded. Skipping.")
                continue

            success = self._download_task(task)

            if not self.dry_run:
                self.checkpoint[task] = success
                self._save_checkpoint()

        logger.info("All downloads completed!")

    @abstractmethod
    def _get_tasks(self) -> list[tuple]:
        """Return ordered list of task tuples to execute.

        Returns:
            list[tuple]: List of task tuples (e.g. (year, month, variable)).
        """

    @abstractmethod
    def _download_task(self, task: tuple) -> int:
        """Execute a single download task.

        Args:
            task (tuple): Task identifier returned by `_get_tasks()`.

        Returns:
            int: 1 if successful, 0 if failed.
        """

    @abstractmethod
    def _validate_variables(self) -> None:
        """Validate that all requested variables are available.

        Raises:
            ValueError: If any variable is invalid or unavailable.
        """

    # ----------------------------------------------------------------
    # Checkpoint helpers
    # ----------------------------------------------------------------
    def _load_checkpoint(self) -> dict:
        """Load checkpoint from disk if resuming, otherwise return empty dict.

        Returns:
            dict: Loaded checkpoint or empty dict.
        """
        if self.resume and self.checkpoint_path.is_file():
            logger.info(f"Resuming from checkpoint: '{self.checkpoint_path}'")
            try:
                with open(self.checkpoint_path, "rb") as f:
                    return pickle.load(f)
            except (EOFError, pickle.UnpicklingError):
                logger.warning("Checkpoint file is corrupted. Starting fresh.")
                return {}

        logger.info("No checkpoint (first run or resume=False). Starting fresh.")
        return {}

    def _save_checkpoint(self) -> None:
        """Save checkpoint to disk atomically."""
        temp_path = self.checkpoint_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            pickle.dump(self.checkpoint, f)
        temp_path.replace(self.checkpoint_path)


def download_file_streaming(url: str, output_file: Path, description: str) -> int:
    """Download a file from a URL using streaming with a tqdm progress bar.

    Creates parent directories as needed. Cleans up partial files on failure.

    Args:
        url (str): URL to download from.
        output_file (Path): Local path to write the downloaded file.
        description (str): Short label shown in the tqdm progress bar and log messages.

    Returns:
        int: 1 if download succeeded, 0 if it failed.
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        logger.info(f"{description}: File size: {total_size / (1024**2):.2f} MB")

        progress_bar = tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=description,
            unit_divisor=1024,
        )

        with open(output_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    progress_bar.update(len(chunk))

        progress_bar.close()
        logger.info(f"{description}: Successfully downloaded to {output_file}")
        return 1

    except requests.exceptions.RequestException as e:
        logger.error(f"{description}: Download failed: {e}")
        if output_file.exists():
            output_file.unlink()
        return 0

    except Exception as e:
        logger.error(f"{description}: Error: {e}")
        if output_file.exists():
            output_file.unlink()
        return 0
