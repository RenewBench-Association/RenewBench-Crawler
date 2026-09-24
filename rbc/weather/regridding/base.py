"""BASE.

Shared abstract base class for source-specific HEALPix regridders.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import grid_doctor as gd
import pandas as pd
import xarray as xr
from loguru import logger

from rbc.weather.regridding.store import (
    DEFAULT_BLOCK_MB,
    TIME_CHUNK,
    bytes_per_timestep,
)
from rbc.weather.utils import (
    exclusive_lock,
    is_marked_done,
    mark_done,
    marker_dir,
    migrate_checkpoint,
)


class GridRegridder(ABC):
    """Abstract base for source-specific HEALPix regridders.

    Subclasses implement `tasks()`, `_discover_variables()`,
    `_load_source_chunk()`, `_grid_metadata_path()`, and `_variable_mapping()`.
    `regrid()` handles the checkpoint loop, weights, and pyramid construction;
    override `_regrid_chunk()` only if a source needs something other than
    the generic path (e.g. BARRA2's regional coverage).

    One variable is loaded, regridded, and written at a time, and each is
    streamed in time blocks, so peak memory follows `block_memory_mb`.

    Attributes:
        block_bytes (int): Memory budget for one time block, from `block_memory_mb`.
        markers (Path): Directory of one marker file per finished key.
        time_freq (str): This source's temporal resolution, as a pandas
            offset alias; sets what `expected_times()` reserves.
    """

    time_freq = "1h"

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
        block_memory_mb: int = DEFAULT_BLOCK_MB,
    ) -> None:
        """Initializes the instance.

        Args:
            raw_dir (Path): Path to this source's already-downloaded raw files.
            source_name (str): Canonical short name for this source (e.g. "era5",
                "icon_dream_global"), used as the per-source subdirectory name
                in the combined store.
            weights_cache_dir (Path): Path to the directory for grid-doctor's
                cached ESMF weight files.
            checkpoint_path (Path): Path to the checkpoint file for resuming.
                Normally `HealpixZarrWriter.checkpoint_path(model_name,
                time_res)`, so it lives alongside the Zarr store this
                source/model variant writes into.
            min_level (int): Coarsest HEALPix pyramid level to retain. Shared
                across all sources feeding the same store, so cross-source
                comparison always has a common level.
            max_level (int): Finest HEALPix pyramid level to compute directly
                from native data. Chosen per source, close to its own native
                resolution, not shared across sources.
            variables (list[str]): List of canonical variable names to regrid.
            years (list[int]): List of years to regrid.
            months (list[str] | None): List of zero-padded months (01-12). If
                None, defaults to all months.
            dry_run (bool): If True, resolve inputs and weights but skip the
                actual regrid.
            resume (bool): If True, load an existing checkpoint on init.
            block_memory_mb (int): Memory budget for one time block; matches
                the writer's own (see `_chunk_along_time()`).

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
        # Sorted, like years: the store's time axis can only be extended
        # forwards, so tasks have to run chronologically whatever order the
        # caller passed them in. Zero-padded, so a plain sort is chronological.
        self.months = sorted(months) if months else [f"{i:02d}" for i in range(1, 13)]
        self.dry_run = dry_run
        self.resume = resume
        self.block_bytes = block_memory_mb * 1024**2

        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        # One marker file per finished key, so several processes can regrid
        # different variables of one store without overwriting each other.
        self.markers = marker_dir(self.checkpoint_path)
        migrate_checkpoint(self.checkpoint_path, self.markers)
        # Filled by subclasses' _load_source_chunk(); see quantization_step().
        self._quantization_steps: dict[str, float | None] = {}

    def pending_keys(self) -> list[tuple]:
        """Return every `(*task, variable)` key still to be regridded.

        The caller's full picture of the work: a manager hands these out to
        workers, and a single-process run walks them in order.

        Returns:
            list[tuple]: Unfinished keys, chronological by task.
        """
        keys = []
        for task in self.tasks():
            for variable in self._variables_for_task(task):
                key = (*task, variable)
                if self.resume and is_marked_done(self.markers, key):
                    logger.info(f"Task {key}: previously regridded. Skipping.")
                    continue
                keys.append(key)
        return keys

    def expected_times(self, task: tuple) -> pd.DatetimeIndex:
        """Return the timestamps this source will write for one task.

        Lets a manager reserve the store's whole time axis before any worker
        runs, so workers only ever fill regions. Override where a source's
        stamps don't sit on a plain `time_freq` grid from the month's start.

        Args:
            task (tuple): (year, month) task identifier.

        Returns:
            pd.DatetimeIndex: One entry per timestep of that month.
        """
        year, month = task
        start = pd.Timestamp(year=int(year), month=int(month), day=1)
        end = start + pd.offsets.MonthBegin(1)
        return pd.date_range(start, end, freq=self.time_freq, inclusive="left")

    def regrid_key(self, key: tuple) -> dict[int, xr.Dataset]:
        """Regrid one `(*task, variable)` key into a lazy pyramid.

        The pyramid is a dask graph, so `HealpixZarrWriter.append()` computes
        and writes it a block at a time rather than materializing a month.
        Call `mark_done(key)` only once that write succeeds.

        Args:
            key (tuple): A key from `pending_keys()`.

        Returns:
            dict[int, xr.Dataset]: Pyramid keyed by HEALPix level, or an empty
                dict on a dry run.
        """
        *head, variable = key
        task = tuple(head)

        logger.info(f"Task {key}: loading source data...")
        ds = self._chunk_along_time(
            self._rename_to_canonical(self._load_source_chunk(task, variable))
        )
        weights = self._get_weights(ds)

        if self.dry_run:
            logger.info(f"Task {key}: DRY RUN - resolved inputs and weights.")
            return {}

        logger.info(
            f"Task {key}: pyramid from level {self.max_level} down to "
            f"{self.min_level}, computed block-wise while writing."
        )
        return self._regrid_chunk(ds, weights)

    def regrid(self) -> Iterator[tuple[tuple, dict[int, xr.Dataset]]]:
        """Regrid every unfinished key in turn, one variable at a time.

        Args:
            None

        Yields:
            tuple[tuple, dict[int, xr.Dataset]]: (key, pyramid) pairs, where
                key is `(*task, variable)` and pyramid is keyed by HEALPix
                level from min_level to max_level.
        """
        for key in self.pending_keys():
            pyramid = self.regrid_key(key)
            if pyramid:
                yield key, pyramid
        logger.info(f"All regridding tasks completed for '{self.source_name}'!")

    def mark_done(self, key: tuple) -> None:
        """Mark a (task, variable) key done and persist the checkpoint.

        Call only after `HealpixZarrWriter.append()` for this key succeeds, so
        that a crash between yield and write leaves the key unfinished.

        Args:
            key (tuple): The `(*task, variable)` key that was successfully written.
        """
        mark_done(self.markers, key)

    def tasks(self) -> list[tuple]:
        """Return (year, month) tasks for every configured year/month.

        Every source uses the same task granularity; override only if one
        needs a different task shape.

        Returns:
            list[tuple]: (year, month) tuples in chronological order, since
                the destination store's time axis only extends forwards.
        """
        return [(year, month) for year in self.years for month in self.months]

    def _variables_for_task(self, task: tuple) -> list[str]:
        """Return canonical variable names to process for one task.

        Returns `self.variables` if the user requested specific ones;
        otherwise discovers what's actually available via
        `_discover_variables()`.

        Args:
            task (tuple): Task identifier returned by `tasks()`.

        Returns:
            list[str]: Canonical variable names to process for this task.
        """
        return self.variables or self._discover_variables(task)

    @abstractmethod
    def _discover_variables(self, task: tuple) -> list[str]:
        """Return every canonical variable actually available for one task.

        Filename-only where possible, cheaply enough to leave the real load
        to `_load_source_chunk()`. Only used when the user didn't request
        specific variables via `self.variables`.

        Args:
            task (tuple): Task identifier returned by `tasks()`.

        Returns:
            list[str]: Canonical variable names found for this task.
        """

    @abstractmethod
    def _load_source_chunk(self, task: tuple, variable: str) -> xr.Dataset:
        """Load the raw source file(s) for one task, for exactly one variable.

        Args:
            task (tuple): Task identifier returned by `tasks()`.
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

    def _trim_to_month(self, ds: xr.Dataset, year: int, month: str) -> xr.Dataset:
        """Drop timestamps outside the exact calendar month.

        Args:
            ds (xr.Dataset): Dataset that may span past month boundaries,
                as forecast-cycle spillover does.
            year (int): Task year.
            month (str): Task month, zero-padded.

        Returns:
            xr.Dataset: Dataset holding only this month's timestamps.
        """
        in_month = (ds.time.dt.year == year) & (ds.time.dt.month == int(month))
        return ds.isel(time=in_month.values)

    @abstractmethod
    def encoding_for(self, variable: str) -> dict | None:
        """Return a `to_zarr()` encoding dict for one canonical variable.

        Passed straight through to `HealpixZarrWriter.append()`. Regridding
        produces float64 whatever the source carried, so every source states
        the precision worth keeping -- a dtype (e.g. {"dtype": "float32"}) or
        the source's own packing, as BARRA2 reuses its int32 +
        scale_factor/add_offset.

        Args:
            variable (str): Canonical variable name.

        Returns:
            dict | None: Encoding for this variable, or None to write it as
                regridded.
        """

    def quantization_step(self, variable: str) -> float | None:
        """Return the source's own precision step for one canonical variable.

        Regridding averages the source's evenly spaced values into arbitrary
        floats; `HealpixZarrWriter` snaps them back onto this step, dropping
        mantissa bits the source never carried. Subclasses record it in
        `self._quantization_steps` while loading.

        Args:
            variable (str): Canonical variable name.

        Returns:
            float | None: The step, or None to write values unchanged -- as
                for BARRA2, whose int32 packing already rounds onto its step.
        """
        return self._quantization_steps.get(variable)

    def _get_weights(self, ds: xr.Dataset) -> Path:
        """Compute or load cached HEALPix weights for this source.

        For unstructured sources, computes from the grid file alone
        (grid-doctor's ICON recipe), not from `ds`. Locked, so that parallel
        workers starting cold generate the cached file once instead of
        writing over each other's.

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
        if grid_path is not None and not grid_path.exists():
            raise FileNotFoundError(
                f"Grid metadata file not found at '{grid_path}'. "
                f"Run the '{self.source_name}' downloader's download_metadata() "
                "first."
            )
        source = ds if grid_path is None else xr.open_dataset(grid_path)
        with exclusive_lock(Path(self.weights_cache_dir, f"level_{self.max_level}")):
            return gd.cached_weights(
                source, level=self.max_level, cache_path=self.weights_cache_dir
            )

    def _chunk_along_time(self, ds: xr.Dataset) -> xr.Dataset:
        """Group the source's single-timestep chunks into ones that fit the budget.

        Sources open one timestep per chunk, safe for any variable but a task
        per timestep; merging them up to `block_memory_mb` regrids more of the
        month in parallel while each read stays within the budget.

        Args:
            ds (xr.Dataset): Renamed source dataset.

        Returns:
            xr.Dataset: Same data, chunked along time.
        """
        if "time" not in ds.dims:
            return ds
        steps = max(1, int(self.block_bytes // max(bytes_per_timestep(ds), 1)))
        return ds.chunk({"time": min(steps, TIME_CHUNK)})

    def _regrid_chunk(self, ds: xr.Dataset, weights: Path) -> dict[int, xr.Dataset]:
        """Regrid `ds` to the full pyramid, max_level down to min_level.

        Handles lat-lon and unstructured global sources; regional sources
        override it (see rbc.weather.regridding.regional).

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
        )
