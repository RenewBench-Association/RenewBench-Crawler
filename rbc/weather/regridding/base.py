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
from tqdm.dask import TqdmCallback


class GridRegridder(ABC):
    """Abstract base for source-specific HEALPix regridders.

    Subclasses implement `_get_tasks()`, `_discover_variables()`,
    `_load_source_chunk()`, `_grid_metadata_path()`, and `_variable_mapping()`.
    `regrid()` handles the checkpoint loop, weights, and pyramid construction;
    override `_regrid_chunk()`/`_regrid_kwargs()` only if a source needs
    something other than the generic path (e.g. BARRA2's regional coverage).

    One variable is loaded, regridded, and written at a time, so peak memory
    scales with one variable's footprint regardless of how many were
    requested together.

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
        years (list[int]): Years to process.
        months (list[str]): Zero-padded months to process (e.g. "01").
        dry_run (bool): If True, resolve inputs/weights but skip the actual regrid
            and skip yielding data.
        resume (bool): If True, load an existing checkpoint on init.
        checkpoint (dict): Dict tracking regrid status per `(*task, variable)`
            key (1=done).
        checkpoint_path (Path): Path to the checkpoint file for resuming regridding.
    """

    def __init__(
        self,
        raw_dir: Path,
        source_name: str,
        weights_cache_dir: Path,
        checkpoint_path: Path,
        min_level: int,
        max_level: int,
        variables: list[str],
        years: list[int],
        months: list[str] | None = None,
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
            checkpoint_path (Path): Path to the checkpoint file. Normally
                `HealpixZarrWriter.checkpoint_path(model_name, time_res)`, so
                it lives alongside the Zarr store this source/model variant
                actually writes into.
            min_level (int): Coarsest HEALPix pyramid level to retain.
            max_level (int): Finest HEALPix pyramid level to compute directly
                from native data.
            variables (list[str]): Canonical variable names to regrid.
            years (list[int]): Years to process.
            months (list[str] | None, optional): Zero-padded months to
                process. Defaults to all 12 months.
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
        self.years = sorted(years)
        self.months = months or [f"{i:02d}" for i in range(1, 13)]
        self.dry_run = dry_run
        self.resume = resume

        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint: dict = self._load_checkpoint()

    def regrid(self) -> Iterator[tuple[tuple, dict[int, xr.Dataset]]]:
        """Regrid all unfinished (task, variable) pairs, one variable at a time.

        Skips checkpointed (task, variable) keys. Weights are resolved once
        per task (from whichever variable is loaded first) and reused for
        every other variable in that task, since they depend only on
        horizontal grid geometry. If `dry_run`, resolves weights but skips
        regridding and yielding. The caller writes each yielded pyramid via
        `HealpixZarrWriter.append()`, then calls `mark_done(key)`.

        Yields:
            tuple[tuple, dict[int, xr.Dataset]]: (key, pyramid) pairs, where
                key is `(*task, variable)` and pyramid is keyed by HEALPix
                level from min_level to max_level.
        """
        for task in self._get_tasks():
            weights: Path | None = None
            for variable in self._variables_for_task(task):
                key = (*task, variable)
                if self.resume and self.checkpoint.get(key, 0) == 1:
                    logger.info(f"Task {key}: previously regridded. Skipping.")
                    continue

                logger.info(f"Task {key}: loading source data...")
                ds = self._load_source_chunk(task, variable)
                ds = self._rename_to_canonical(ds)

                if weights is None:
                    logger.info(f"Task {task}: resolving HEALPix weights...")
                    weights = self._get_weights(ds)

                if self.dry_run:
                    logger.info(
                        f"Task {key}: DRY RUN - resolved inputs and weights, "
                        "skipping regrid."
                    )
                    continue

                logger.info(
                    f"Task {key}: regridding to level {self.max_level} "
                    f"(pyramid down to level {self.min_level})..."
                )
                with TqdmCallback(desc=f"Task {key}"):
                    pyramid = self._regrid_chunk(ds, weights)
                logger.info(f"Task {key}: regridding complete.")
                yield key, pyramid

        logger.info(f"All regridding tasks completed for '{self.source_name}'!")

    def mark_done(self, key: tuple) -> None:
        """Mark a (task, variable) key done and persist the checkpoint.

        Call only after `HealpixZarrWriter.append()` for this key succeeds —
        not inside `regrid()`, so a crash between yield and write can't mark a
        key done that was never actually written.

        Args:
            key (tuple): The `(*task, variable)` key that was successfully written.
        """
        self.checkpoint[key] = 1
        self._save_checkpoint()

    def _get_tasks(self) -> list[tuple]:
        """Return (year, month) tasks for every configured year/month.

        Every source uses the same task granularity, since weights depend only
        on horizontal geometry, not on which month is being processed.
        Override only if a source genuinely needs a different task shape.

        Returns:
            list[tuple]: Ordered list of (year, month) tuples.
        """
        return [(year, month) for year in self.years for month in self.months]

    def _variables_for_task(self, task: tuple) -> list[str]:
        """Return canonical variable names to process for one task.

        Returns `self.variables` if the user requested specific ones;
        otherwise discovers what's actually available via
        `_discover_variables()`.

        Args:
            task (tuple): Task identifier returned by `_get_tasks()`.

        Returns:
            list[str]: Canonical variable names to process for this task.
        """
        if self.variables:
            return self.variables
        return self._discover_variables(task)

    @abstractmethod
    def _discover_variables(self, task: tuple) -> list[str]:
        """Return every canonical variable actually available for one task.

        Filename-only where possible, cheaply enough to leave the real load
        to `_load_source_chunk()`. Only used when the user didn't request
        specific variables via `self.variables`.

        Args:
            task (tuple): Task identifier returned by `_get_tasks()`.

        Returns:
            list[str]: Canonical variable names found for this task.
        """

    @abstractmethod
    def _load_source_chunk(self, task: tuple, variable: str) -> xr.Dataset:
        """Load the raw source file(s) for one task, for exactly one variable.

        Args:
            task (tuple): Task identifier returned by `_get_tasks()`.
            variable (str): Canonical variable name to load -- one of
                `_variables_for_task(task)`.

        Returns:
            xr.Dataset: The opened source dataset for just this variable, in
                native variable and dimension names.
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

    def encoding_for(self, variable: str) -> dict | None:
        """Return a `to_zarr()` encoding dict for one canonical variable.

        Passed straight through to `HealpixZarrWriter.append()`. None by
        default (Zarr's own default dtype/compression apply); override to
        reuse a source's native on-disk packing (e.g. BARRA2's own
        int32 + scale_factor/add_offset).

        Args:
            variable (str): Canonical variable name.

        Returns:
            dict | None: None by default.
        """
        return None

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
