"""BASE.

Shared abstract base class for source-specific HEALPix regridders.
"""

import pickle
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import grid_doctor as gd
import xarray as xr
from loguru import logger


class GridRegridder(ABC):
    """Abstract base for source-specific HEALPix regridders.

    Subclasses implement `_get_tasks()`, `_load_source_chunk()`,
    `_grid_metadata_path()`, and `_variable_mapping()`. `regrid()` handles the
    checkpoint loop, weights, and pyramid construction; override
    `_regrid_chunk()`/`_regrid_kwargs()` only if a source needs something
    other than the generic path (e.g. BARRA2's regional coverage).

    Attributes:
        raw_dir (Path): Root of this source's already-downloaded raw files.
        source_name (str): Canonical short name (e.g. "era5", "icon_dream_global");
            used as the per-source subdirectory name in the combined store.
        weights_cache_dir (Path): Where grid-doctor's ESMF weight files are cached.
        min_level (int): Coarsest HEALPix pyramid level to retain — shared across
            all sources feeding the same store, so cross-source comparison always
            has a common level to compare at.
        max_level (int): Finest HEALPix level computed directly from native data —
            chosen per source, close to that source's own native resolution, not
            shared across sources.
        variables (list[str]): Canonical variable names to regrid.
        dry_run (bool): If True, resolve inputs/weights but skip the actual regrid
            and skip yielding data.
        resume (bool): If True, load an existing checkpoint on init.
        checkpoint (dict): Dict tracking regrid status per task tuple (1=done).
        checkpoint_path (Path): Path to the checkpoint file for resuming.
    """

    def __init__(
        self,
        raw_dir: Path,
        source_name: str,
        weights_cache_dir: Path,
        min_level: int,
        max_level: int,
        variables: list[str],
        dry_run: bool = False,
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Args:
            raw_dir (Path): Root of this source's already-downloaded raw files.
            source_name (str): Canonical short name for this source, used as the
                per-source subdirectory name in the combined store.
            weights_cache_dir (Path): Directory for grid-doctor's cached ESMF
                weight files.
            min_level (int): Coarsest HEALPix pyramid level to retain.
            max_level (int): Finest HEALPix pyramid level to compute directly
                from native data.
            variables (list[str]): Canonical variable names to regrid.
            dry_run (bool, optional): If True, resolve inputs/weights but skip
                the actual regrid. Defaults to False.
            resume (bool, optional): If True, load an existing checkpoint on
                init. Defaults to True.

        Raises:
            FileNotFoundError: If raw_dir does not exist.
            ValueError: If min_level is not lower than max_level.
        """
        self.raw_dir = Path(raw_dir)
        if not self.raw_dir.is_dir():
            raise FileNotFoundError(
                f"Raw data directory '{self.raw_dir}' does not exist. "
                f"Run the '{source_name}' downloader first."
            )

        if min_level >= max_level:
            raise ValueError(
                f"min_level ({min_level}) must be lower than max_level ({max_level})."
            )

        self.source_name = source_name
        self.weights_cache_dir = Path(weights_cache_dir)
        self.weights_cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_level = min_level
        self.max_level = max_level
        self.variables = variables
        self.dry_run = dry_run
        self.resume = resume

        self.checkpoint_path = Path(self.raw_dir, "regrid_status.pickle")
        self.checkpoint: dict = self._load_checkpoint()

    def regrid(self) -> Iterator[tuple[tuple, dict[int, xr.Dataset]]]:
        """Regrid all unfinished tasks, yielding a HEALPix pyramid per task.

        Skips checkpointed tasks. If `dry_run`, resolves weights but doesn't
        regrid or yield. Never writes to the store — the caller must write via
        `HealpixZarrWriter.append()`, then call `mark_done(task)`.

        Yields:
            tuple[tuple, dict[int, xr.Dataset]]: (task, pyramid) pairs, where
                pyramid is keyed by HEALPix level from min_level to max_level.
        """
        for task in self._get_tasks():
            if self.resume and self.checkpoint.get(task, 0) == 1:
                logger.info(f"Task {task}: previously regridded. Skipping.")
                continue

            ds = self._load_source_chunk(task)
            ds = self._rename_to_canonical(ds)
            weights = self._get_weights(ds)

            if self.dry_run:
                logger.info(
                    f"Task {task}: DRY RUN - resolved inputs and weights, "
                    "skipping regrid."
                )
                continue

            pyramid = self._regrid_chunk(ds, weights)
            yield task, pyramid

        logger.info(f"All regridding tasks completed for '{self.source_name}'!")

    def mark_done(self, task: tuple) -> None:
        """Mark a task done and persist the checkpoint.

        Call only after `HealpixZarrWriter.append()` for this task succeeds —
        not inside `regrid()`, so a crash between yield and write can't mark a
        task done that was never actually written.

        Args:
            task (tuple): The task that was successfully written.
        """
        self.checkpoint[task] = 1
        self._save_checkpoint()

    @abstractmethod
    def _get_tasks(self) -> list[tuple]:
        """Return ordered list of task tuples to execute.

        Returns:
            list[tuple]: List of task tuples (e.g. (year, month)).
        """

    @abstractmethod
    def _load_source_chunk(self, task: tuple) -> xr.Dataset:
        """Load and merge the raw source file(s) for a single task.

        Args:
            task (tuple): Task identifier returned by `_get_tasks()`.

        Returns:
            xr.Dataset: The opened source dataset, in native variable and
                dimension names.
        """

    @abstractmethod
    def _grid_metadata_path(self) -> Path | None:
        """Return this source's external grid definition file, if it has one.

        Returns:
            Path | None: Path to the grid definition file for unstructured
                sources (e.g. ICON-DREAM); None for lat-lon sources that already
                carry their own coordinates.
        """

    @abstractmethod
    def _variable_mapping(self) -> dict[str, str]:
        """Return the native-to-canonical variable name mapping for this source.

        Returns:
            dict[str, str]: Mapping of native variable names to canonical names.
        """

    def _rename_to_canonical(self, ds: xr.Dataset) -> xr.Dataset:
        """Rename this source's data variables to their canonical names.

        Args:
            ds (xr.Dataset): Dataset in native variable names.

        Returns:
            xr.Dataset: Dataset with variables renamed per `_variable_mapping()`.
                Variables not present in `ds` are silently skipped.
        """
        mapping = {
            k: v for k, v in self._variable_mapping().items() if k in ds.data_vars
        }
        return ds.rename_vars(mapping)

    def _regrid_kwargs(self) -> dict:
        """Extra keyword arguments forwarded to `create_healpix_pyramid()`.

        Returns:
            dict: Extra kwargs, e.g. `{"source_kind": "unstructured"}` for
                ICON-DREAM. Empty by default.
        """
        return {}

    def _get_weights(self, ds: xr.Dataset) -> Path:
        """Compute or load cached HEALPix weights for this source.

        For unstructured sources, computes from the grid file alone
        (grid-doctor's ICON recipe), not from `ds`.

        Args:
            ds (xr.Dataset): Renamed source dataset (used directly for lat-lon
                sources; only used as a fallback for unstructured sources).

        Returns:
            Path: Path to the cached NetCDF weight file.

        Raises:
            FileNotFoundError: If this source has a grid metadata file
                configured but it does not exist on disk.
        """
        grid_path = self._grid_metadata_path()
        if grid_path is None:
            return gd.cached_weights(
                ds, level=self.max_level, cache_path=self.weights_cache_dir
            )

        if not grid_path.exists():
            raise FileNotFoundError(
                f"Grid metadata file not found at '{grid_path}'. "
                f"Run the '{self.source_name}' downloader's download_metadata() "
                "first."
            )
        geometry_ds = xr.open_dataset(grid_path)
        return gd.cached_weights(
            geometry_ds, level=self.max_level, cache_path=self.weights_cache_dir
        )

    def _regrid_chunk(self, ds: xr.Dataset, weights: Path) -> dict[int, xr.Dataset]:
        """Regrid `ds` to the full pyramid, max_level down to min_level.

        Works for lat-lon and unstructured sources. BARRA2 must override this
        once the regional-source crash fix lands (Phase 2).

        Args:
            ds (xr.Dataset): Renamed source dataset to regrid.
            weights (Path): Path to the cached weight file from `_get_weights()`.

        Returns:
            dict[int, xr.Dataset]: Pyramid keyed by HEALPix level.
        """
        return gd.create_healpix_pyramid(
            ds,
            max_level=self.max_level,
            min_level=self.min_level,
            weights_path=weights,
            **self._regrid_kwargs(),
        )

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
