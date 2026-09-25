"""STORE.

Zarr writer for regridded HEALPix pyramids, per the weather Zarr contract
(modeled on DKRZ's Waterpark).
"""

import time
from collections.abc import Hashable, Iterable
from pathlib import Path
from typing import Literal, NamedTuple

import dask
import dask.array
import numpy as np
import pandas as pd
import xarray as xr
from loguru import logger
from tqdm import tqdm
from zarr.codecs import BloscCodec, GzipCodec, ZstdCodec

from rbc.weather.utils import exclusive_lock

# Vertical dimensions the contract uses, in the order they appear between
# "time" and "cell". A store holds one coordinate array per dimension name, so
# variables whose level sets differ get numbered siblings ("level",
# "level_1", ...) -- see _resolve_vertical_dim().
_VERTICAL_DIMS = ("level", "height", "model_level", "model_level_half")

# Uncompressed bytes per Zarr chunk, kept well inside the codecs' 2 GiB
# buffer limit.
_TARGET_CHUNK_BYTES = 64 * 1024**2

# Cell-ordering scheme grid-doctor stamps on every pyramid it builds. Used
# when reserving a store before any pyramid exists; a divergence surfaces at
# the first write, in _validate_consistency().
HEALPIX_ORDER = "nested"

# Timesteps per chunk. Divides every real month length (hourly months are
# multiples of 24, 20-minute months multiples of 72), so a month written as
# one region starts on a chunk boundary.
TIME_CHUNK = 24

# Default megabytes of pyramid computed and written at a time; GridRegridder
# sizes its source chunks by the same budget.
DEFAULT_BLOCK_MB = 512

# Source chunks one block may pull through the regrid. Each is already sized
# to the memory budget, so this bounds the input side for pyramids small
# enough that the budget alone would allow a whole month per block.
_MAX_CHUNKS_PER_BLOCK = 4


def bytes_per_timestep(ds: xr.Dataset) -> int:
    """Return the bytes one timestep of `ds` occupies in memory.

    Args:
        ds (xr.Dataset): Dataset to measure.

    Returns:
        int: Bytes per timestep, summed over the data variables.
    """
    total = 0
    for da in ds.data_vars.values():
        cells = int(np.prod([s for d, s in da.sizes.items() if d != "time"]))
        total += cells * da.dtype.itemsize
    return total


class _LevelPlan(NamedTuple):
    """One level's reserved store, waiting for its values.

    Attributes:
        store_path (Path): Store this level is written to.
        ds (xr.Dataset): Single-variable Dataset to write.
        variable (Hashable): That variable's name.
        start (int): Index on the store's time axis where `ds` begins.
    """

    store_path: Path
    ds: xr.Dataset
    variable: Hashable
    start: int


class HealpixZarrWriter:
    """Writes regridded HEALPix pyramids into per-(model, time_res, level) Zarr stores.

    Layout: "<base_dir>/<model_name>/<time_res>/level_<N>.zarr". Surface,
    pressure-level, height-level, and model-level variables coexist in one
    store, distinguished by their own dimensions (e.g. [time, cell] vs.
    [time, level, cell]).

    Every write uses `consolidated=False`, since Zarr still flags consolidated
    metadata as not part of the v3 spec.

    Attributes:
        base_dir (Path): Root directory the stores are written under.
        min_level (int): Shared coarsest HEALPix level, validated against
            every incoming pyramid.
        compressors (tuple | None): Codec pipeline applied on a variable's
            first write; None writes raw bytes.
        block_bytes (int): Memory budget for one time block of the pyramid.
    """

    def __init__(
        self,
        base_dir: Path,
        min_level: int,
        compressor: str = "zlib",
        compression_level: int = 1,
        shuffle: bool = True,
        block_memory_mb: int = DEFAULT_BLOCK_MB,
    ) -> None:
        """Initializes the instance.

        Args:
            base_dir (Path): Root directory for the stores; `to_zarr` creates
                the full nested path on first write.
            min_level (int): Shared coarsest HEALPix level across sources.
            compressor (str): "zlib", "zstd", or "none". Defaults to "zlib".
            compression_level (int): Codec level, >= 1. Defaults to 1.
            shuffle (bool): Byte-shuffle before compressing, the filter NetCDF
                itself uses (measured ~1.4x smaller on packed int32). Ignored
                for "none". Defaults to True.
            block_memory_mb (int): How much of the pyramid to compute and
                write at a time (see `_block_timesteps()`). Lower it on a
                memory-tight node, raise it for longer Zarr time chunks and
                fewer blocks per task.

        Raises:
            ValueError: If `compressor` is unknown or `compression_level` < 1.
        """
        self.base_dir = Path(base_dir)
        self.min_level = min_level
        self.block_bytes = block_memory_mb * 1024**2
        self.compressors = self._build_compressors(
            compressor, compression_level, shuffle
        )

    @staticmethod
    def _build_compressors(compressor: str, level: int, shuffle: bool) -> tuple | None:
        """Build the Zarr codec pipeline for one (compressor, level, shuffle) choice.

        Shuffle isn't a standalone Zarr v3 codec, so shuffled pipelines go
        through Blosc (which bundles it with zlib/zstd) and unshuffled ones
        use the plain Gzip/Zstd codecs. Measured on real BARRA2 data: shuffle
        is what makes packed int32 compress well (the level barely matters),
        and Blosc's zstd needs a higher level than zlib to match it.

        Args:
            compressor (str): "zlib", "zstd", or "none".
            level (int): Codec level, >= 1.
            shuffle (bool): Whether to byte-shuffle before compressing.

        Returns:
            tuple | None: Codecs for `to_zarr()`'s "compressors" encoding;
                None for "none".

        Raises:
            ValueError: If `compressor` is unknown or `level` < 1.
        """
        if compressor == "none":
            return None
        if compressor not in ("zlib", "zstd"):
            raise ValueError(
                f"Unknown compressor {compressor!r}; expected 'zlib', 'zstd' or 'none'."
            )
        if level < 1:
            raise ValueError(
                f"compression_level must be >= 1, got {level}; pass "
                "compressor='none' to write uncompressed."
            )
        if shuffle:
            cname: Literal["zlib", "zstd"] = "zlib" if compressor == "zlib" else "zstd"
            return (BloscCodec(cname=cname, clevel=level, shuffle="shuffle"),)
        if compressor == "zlib":
            return (GzipCodec(level=level),)
        return (ZstdCodec(level=level),)

    def append(
        self,
        model_name: str,
        time_res: str,
        task: tuple,
        pyramid: dict[int, xr.Dataset],
        encoding: dict | None = None,
        quantization_step: float | None = None,
    ) -> None:
        """Write or grow each level's store for one task's single-variable pyramid.

        Every level's store is first reserved over the time range it needs,
        all NaN, growing the shared time axis for every variable at once where
        the store exists already. The values are filled in afterwards one time
        block at a time, every level from the same computation, so a whole
        month's pyramid is never in memory at once. The store stays
        shape-consistent and readable after every write, but is not
        crash-atomic: call `GridRegridder.mark_done()` only once this returns.

        Args:
            model_name (str): Contract "model_name" (e.g. "barra2_c2", shared
                by barra2_c2 and barra2_c2_20min and distinguished by
                time_res).
            time_res (str): "1h" or "20min".
            task (tuple): Task identifier, used for logging and errors.
            pyramid (dict[int, xr.Dataset]): HEALPix pyramid to write, keyed
                by level, each level carrying exactly one data variable.
            encoding (dict | None): Packing for that variable (e.g.
                `{"dtype": "int32", "scale_factor": ...}`), merged with this
                writer's compression and applied on its first write only.
            quantization_step (float | None): Source precision step to snap
                values onto (see `GridRegridder.quantization_step()`). None
                writes values unchanged.

        Raises:
            ValueError: If the pyramid is missing the shared `min_level`; if
                an existing store's `healpix_level`/`healpix_order` don't
                match the incoming data; or if the new timestamps start before
                the store's existing range.
        """
        if self.min_level not in pyramid:
            raise ValueError(
                f"Pyramid for task {task} does not include the shared min_level "
                f"({self.min_level}); got levels {sorted(pyramid)}."
            )

        task_start = time.time()
        chunk, block = self._block_timesteps(pyramid)
        # Only reserving a level takes a lock (see `_reserve_level()`); the
        # fill afterwards writes this variable's own region and runs free of
        # the other workers.
        plans = [
            self._reserve_level(
                self._store_path(model_name, time_res, level),
                self._snap_to_lattice(self._normalize_dim_order(ds), quantization_step),
                task,
                encoding,
                chunk,
            )
            for level, ds in pyramid.items()
        ]
        self._fill_blocks(plans, block, task)
        logger.info(
            f"'{model_name}/{time_res}' task {task}: all {len(pyramid)} levels "
            f"written ({time.time() - task_start:.1f}s total)."
        )

    def reserve_time_axis(
        self,
        model_name: str,
        time_res: str,
        times: pd.DatetimeIndex,
        levels: Iterable[int],
    ) -> None:
        """Create or extend each level's store to span `times`, before any fill.

        Reserving the whole run's axis up front is what lets workers write
        months in any order: the axis can only grow forwards, so a worker
        reaching February first would otherwise lock January out. Each store
        is created holding the time coordinate alone -- variables add
        themselves on first write -- and reserved timesteps cost almost
        nothing, since unwritten chunks equal the fill value and Zarr does
        not store them.

        Args:
            model_name (str): Contract "model_name".
            time_res (str): "1h" or "20min".
            times (pd.DatetimeIndex): Every timestamp the run will write.
            levels (Iterable[int]): HEALPix levels to reserve.

        Raises:
            ValueError: If an existing store already holds timestamps after
                `times`, which would need inserting rather than appending.
        """
        for level in levels:
            store_path = self._store_path(model_name, time_res, level)
            axis = xr.Dataset(
                coords={"time": times},
                attrs={"healpix_level": level, "healpix_order": HEALPIX_ORDER},
            )
            if not self._store_exists(store_path):
                axis.to_zarr(store_path, mode="w", consolidated=False)
                logger.info(f"{store_path}: reserved {times.size} timesteps.")
                continue
            self._extend_time_axis(
                store_path, self._open(store_path), axis, ("reserve",)
            )

    def emit_stac_item(
        self,
        model_name: str,
        time_res: str,
        task: tuple,
        pyramid: dict[int, xr.Dataset],
    ) -> None:
        """No-op hook for future STAC item generation (Phase 5).

        Args:
            model_name (str): Contract "model_name".
            time_res (str): "1h" or "20min".
            task (tuple): Task identifier.
            pyramid (dict[int, xr.Dataset]): The pyramid just written.
        """
        return None

    def checkpoint_path(self, model_name: str, time_res: str) -> Path:
        """Return the checkpoint file path for one (model_name, time_res).

        Checkpointing tracks what a `GridRegridder` has finished writing to
        this destination, so it lives alongside the stores it belongs to.

        Args:
            model_name (str): Contract "model_name".
            time_res (str): "1h" or "20min".

        Returns:
            Path: "<base_dir>/<model_name>/<time_res>/status.pickle".
        """
        return Path(self.base_dir, model_name, time_res, "status.pickle")

    def weights_cache_dir(self, model_name: str) -> Path:
        """Return the ESMF weight-cache directory for one model_name.

        Keyed by model_name only: weights depend solely on horizontal grid
        geometry, which is identical across temporal resolutions of the same
        physical grid.

        Args:
            model_name (str): Contract "model_name".

        Returns:
            Path: "<base_dir>/<model_name>/weights_cache/".
        """
        return Path(self.base_dir, model_name, "weights_cache")

    def _store_path(self, model_name: str, time_res: str, level: int) -> Path:
        """Return the Zarr store path for one (model_name, time_res, level).

        Args:
            model_name (str): Contract "model_name".
            time_res (str): "1h" or "20min".
            level (int): HEALPix level.

        Returns:
            Path: "<base_dir>/<model_name>/<time_res>/level_<level>.zarr".
        """
        return Path(self.base_dir, model_name, time_res, f"level_{level}.zarr")

    @staticmethod
    def _open(store_path: Path) -> xr.Dataset:
        """Open a store's current contents.

        Args:
            store_path (Path): Path from `_store_path()`.

        Returns:
            xr.Dataset: The store, lazily.
        """
        return xr.open_zarr(store_path, consolidated=False)

    def _reserve_level(
        self,
        store_path: Path,
        ds: xr.Dataset,
        task: tuple,
        encoding: dict | None,
        chunk: int,
    ) -> _LevelPlan:
        """Create or grow one level's store and reserve this variable's range.

        Args:
            store_path (Path): Path from `_store_path()`.
            ds (xr.Dataset): Single-variable Dataset, already normalized and
                snapped.
            task (tuple): Task identifier, for logging and errors.
            encoding (dict | None): Packing for the variable, merged with this
                writer's compression.
            chunk (int): Timesteps per Zarr chunk.

        Returns:
            _LevelPlan: Where and at which offset the values go.
        """
        (variable,) = ds.data_vars
        var_encoding: dict = {**(encoding or {}), "compressors": self.compressors}
        var_encoding["chunks"] = self._chunk_shape(ds[variable], var_encoding, chunk)
        # Reserved chunks are never written, so a packed variable's gaps read
        # back as Zarr's own fill (0, a real measurement) unless it is told
        # which value stands for "missing". Floats already default to NaN.
        if "_FillValue" in var_encoding:
            var_encoding.setdefault("fill_value", var_encoding["_FillValue"])
        zarr_encoding = {variable: var_encoding}

        # Locked: a variable's own array is its own, but everything around it
        # here is shared -- the "cell"/"latitude"/"longitude"/"crs" coordinates
        # that come with every pyramid, the vertical coordinate
        # _align_vertical_dims() picks by reading the store, and the time axis.
        # Whichever variable arrives first creates them, so two workers adding
        # their first variable at once would otherwise both try to.
        with exclusive_lock(store_path):
            if not self._store_exists(store_path):
                logger.info(f"{store_path}: creating store for task {task}...")
                self._reserve(store_path, ds, ds["time"], zarr_encoding, chunk, "w")
                return _LevelPlan(store_path, ds, variable, 0)

            existing = self._open(store_path)
            self._validate_consistency(store_path, ds, existing=existing)
            ds = self._align_vertical_dims(ds, existing, store_path)
            existing = self._extend_time_axis(store_path, existing, ds, task)

            if variable not in existing.data_vars:
                logger.info(
                    f"{store_path}: adding new variable '{variable}' for {task}..."
                )
                # Spans the store's full axis so every variable shares one
                # "time", NaN for the months this one has no data for.
                self._reserve(
                    store_path, ds, existing["time"], zarr_encoding, chunk, "a"
                )
                existing = self._open(store_path)

        # Outside the lock: this reads only the variable's own region, and the
        # store's timestamps keep their positions however it grows.
        start = self._region_start(store_path, ds, variable, existing, task)
        return _LevelPlan(store_path, ds, variable, start)

    def _normalize_dim_order(self, ds: xr.Dataset) -> xr.Dataset:
        """Enforce the contract's dimension order: time, vertical dim, cell.

        Applies to whichever of `_VERTICAL_DIMS` a variable has, or none.

        Args:
            ds (xr.Dataset): Dataset about to be written.

        Returns:
            xr.Dataset: Same data, with every variable's dims reordered.
        """
        return ds.transpose("time", *_VERTICAL_DIMS, "cell", missing_dims="ignore")

    def _snap_to_lattice(self, ds: xr.Dataset, step: float | None) -> xr.Dataset:
        """Round values onto the source's own precision lattice.

        `round(x / step) * step`, exact in float32 for the power-of-two steps
        every source uses. The error is at most half a step, so the result
        stays within what the source itself could represent.

        Args:
            ds (xr.Dataset): Dataset about to be written.
            step (float | None): Source precision step; None leaves `ds`
                untouched.

        Returns:
            xr.Dataset: Same data, snapped onto the lattice.
        """
        if not step:
            return ds
        # Dataset attrs carry healpix_level/order for _validate_consistency(),
        # variable attrs carry units and cell_methods.
        with xr.set_options(keep_attrs=True):
            return (ds / step).round() * step

    def _chunk_shape(
        self, da: xr.DataArray, encoding: dict, time_chunk: int
    ) -> tuple[int, ...]:
        """Return a chunk shape bounded by `_TARGET_CHUNK_BYTES`.

        Keeps vertical levels whole (there are few, and they are usually read
        together) and splits "cell" to fit the remaining budget, sized from
        the encoded dtype the codec actually sees.

        Args:
            da (xr.DataArray): The variable about to be written, in the
                contract's dimension order.
            encoding (dict): That variable's encoding, read for its "dtype".
            time_chunk (int): Timesteps per chunk, from `_block_timesteps()`.

        Returns:
            tuple[int, ...]: Chunk size per dimension, in `da.dims` order.
        """
        itemsize = np.dtype(encoding.get("dtype", da.dtype)).itemsize
        sizes = dict(da.sizes)
        time_chunk = min(time_chunk, sizes.get("time", 1))

        vertical = 1
        for dim, size in sizes.items():
            if dim not in ("time", "cell"):
                vertical *= size

        budget = _TARGET_CHUNK_BYTES // (itemsize * time_chunk * vertical)
        cell_chunk = max(1, min(budget, sizes.get("cell", 1)))

        return tuple(
            time_chunk if dim == "time" else cell_chunk if dim == "cell" else sizes[dim]
            for dim in da.dims
        )

    def _block_timesteps(self, pyramid: dict[int, xr.Dataset]) -> tuple[int, int]:
        """Return the Zarr time chunk and how many timesteps to write at a time.

        One block of every level is in memory at once, so it is sized to keep
        that under `block_bytes` -- a whole month of a 3D global variable is
        hundreds of GB. A block holds a whole number of the incoming dask
        chunks, so each source chunk is read once and regions stay aligned
        with the chunks written here.

        Args:
            pyramid (dict[int, xr.Dataset]): The pyramid about to be written.

        Returns:
            tuple[int, int]: (timesteps per Zarr chunk, timesteps per block).
        """
        per_step = sum(bytes_per_timestep(ds) for ds in pyramid.values())
        incoming = max(
            (
                max(da.chunksizes.get("time", (0,)))
                for ds in pyramid.values()
                for da in ds.data_vars.values()
            ),
            default=0,
        )
        budget = max(1, int(self.block_bytes // max(per_step, 1)))
        # An eagerly computed pyramid (the regional path) has no chunks to
        # follow, so the contract's own time chunk applies.
        unit = min(incoming or TIME_CHUNK, TIME_CHUNK, budget)
        # The budget covers what is written; the source feeding a block costs
        # memory too, and dwarfs it where the target is much coarser than the
        # source (a regional pyramid's compact levels).
        chunks = max(1, min(budget // unit, _MAX_CHUNKS_PER_BLOCK))
        return unit, unit * chunks

    def _reserve(
        self,
        store_path: Path,
        ds: xr.Dataset,
        times: xr.DataArray,
        encoding: dict,
        chunk: int,
        mode: str,
    ) -> None:
        """Write the variable's schema and coordinates over `times`, all NaN.

        The NaN array is built chunked and lazily, so the store's chunks are
        written without computing any regridded value or holding the variable
        in memory; `_fill_blocks()` fills them afterwards.

        Args:
            store_path (Path): Path from `_store_path()`.
            ds (xr.Dataset): Incoming Dataset for one variable.
            times (xr.DataArray): Time axis the variable should span.
            encoding (dict): Zarr encoding for that variable.
            chunk (int): Timesteps per chunk, from `_block_timesteps()`.
            mode (str): "w" for a new store, "a" for a new variable in one.
        """
        (variable,) = ds.data_vars
        da = ds[variable]
        rest = {d: s for d, s in da.sizes.items() if d != "time"}
        blank = dask.array.full(
            (times.size, *rest.values()),
            np.nan,
            dtype=da.dtype,
            chunks=(chunk, *rest.values()),
        )
        template = xr.Dataset(
            {variable: (("time", *rest), blank, da.attrs)},
            # Coordinates along time describe the incoming slice, not the span
            # being reserved, so only the others carry over.
            coords={
                **{k: v for k, v in ds.coords.items() if "time" not in v.dims},
                "time": times,
            },
            attrs=ds.attrs,
        )
        # compute=False writes the schema and coordinates but no data chunks.
        # Chunks nothing has filled yet are absent from the store and read
        # back as the fill value, so materializing NaN over the reserved span
        # would cost minutes per variable and change nothing.
        template.to_zarr(
            store_path,
            mode=mode,
            encoding=encoding,
            consolidated=False,
            compute=False,
        )

    def _extend_time_axis(
        self, store_path: Path, existing: xr.Dataset, ds: xr.Dataset, task: tuple
    ) -> xr.Dataset:
        """Grow the store's shared time axis to cover `ds`'s new timestamps.

        "time" is one dimension shared by every variable in a store, so all of
        them are extended together here (NaN over the new range) and the real
        values are filled in per variable afterwards.

        Args:
            store_path (Path): Path from `_store_path()`.
            existing (xr.Dataset): The store's current contents.
            ds (xr.Dataset): Incoming Dataset for one variable.
            task (tuple): Task identifier, for logging and errors.

        Returns:
            xr.Dataset: The store's contents, re-opened if it was extended.

        Raises:
            ValueError: If the new timestamps aren't on the store's axis, or
                start before its last one -- either would need inserting
                rather than extending.
        """
        existing_times = pd.Index(existing["time"].values)
        incoming_times = pd.Index(ds["time"].values)
        new_times = incoming_times.difference(existing_times)
        if new_times.empty:
            return existing

        if len(existing_times) and new_times.min() < existing_times.max():
            # Starting after the store's first stamp means these sit between
            # the store's, not before them -- a source whose clock isn't the
            # one `expected_times()` reserved reads as "out of order" otherwise.
            if new_times.min() > existing_times.min():
                raise ValueError(
                    f"'{store_path}', task {task}: timestamps {new_times.min()}.."
                    f"{new_times.max()} fall within the store's range "
                    f"({existing_times.min()}..{existing_times.max()}) but aren't on "
                    "its axis. Either this source doesn't stamp on the clock "
                    "`expected_times()` reserved for it, or this month was never "
                    "reserved."
                )
            raise ValueError(
                f"'{store_path}', task {task}: new timestamps start at "
                f"{new_times.min()}, before the store's last ({existing_times.max()}). "
                "Timestamps can only be added after the store's existing range -- "
                "regrid months in chronological order."
            )

        logger.info(
            f"{store_path}: extending shared time axis by {len(new_times)} step(s) "
            f"for task {task}..."
        )
        self._blank_extension(existing, new_times).to_zarr(
            store_path,
            mode="a",
            append_dim="time",
            consolidated=False,
            compute=False,
        )
        return self._open(store_path)

    @staticmethod
    def _blank_extension(existing: xr.Dataset, times: pd.Index) -> xr.Dataset:
        """Return every time-bearing variable of `existing` as NaN over `times`.

        Built lazily and chunked, like `_reserve()`: `reindex()` would hand
        back NumPy instead, one full array per variable, which for a store
        holding several variables at a fine level is tens of GB before a
        single byte is written.

        Args:
            existing (xr.Dataset): The store's current contents.
            times (pd.Index): Timestamps to extend the store by.

        Returns:
            xr.Dataset: One lazy all-NaN variable per time-bearing variable
                of `existing`, spanning `times`.
        """
        blanks: dict[Hashable, tuple] = {}
        for name, da in existing.data_vars.items():
            if "time" not in da.dims:
                continue
            rest = {dim: size for dim, size in da.sizes.items() if dim != "time"}
            shape = (times.size, *rest.values())
            blanks[name] = (
                ("time", *rest),
                dask.array.full(
                    shape,
                    np.nan,
                    dtype=da.dtype,
                    chunks=da.encoding.get("chunks") or shape,
                ),
                da.attrs,
            )
        # attrs carried over: writing this template is a group-level write,
        # and an empty set would clear the store's healpix_level/order.
        return xr.Dataset(blanks, coords={"time": times}, attrs=existing.attrs)

    def _region_start(
        self,
        store_path: Path,
        ds: xr.Dataset,
        variable: Hashable,
        existing: xr.Dataset,
        task: tuple,
    ) -> int:
        """Return the store index `ds`'s first timestamp belongs at.

        Args:
            store_path (Path): Path from `_store_path()`.
            ds (xr.Dataset): Incoming Dataset for one variable.
            variable (Hashable): The variable being written.
            existing (xr.Dataset): The store's contents, time axis already
                covering `ds`.
            task (tuple): Task identifier, for errors.

        Returns:
            int: Index of `ds`'s first timestamp on the store's time axis.

        Raises:
            ValueError: If the incoming timestamps aren't a contiguous run in
                the store.
        """
        store_times = pd.Index(existing["time"].values)
        positions = store_times.get_indexer(pd.Index(ds["time"].values))
        start, stop = int(positions.min()), int(positions.max()) + 1
        if stop - start != len(positions):
            raise ValueError(
                f"'{store_path}', task {task}: '{variable}' timestamps aren't a "
                "contiguous run in the store, so they can't be written as one region."
            )

        written = existing[variable].isel(time=slice(start, stop))
        if bool(written.notnull().any()):
            # Overwritten rather than refused: a key only reaches here when the
            # checkpoint doesn't hold it, which means the run that wrote this
            # died before finishing it. Rewriting the month is what fixes it.
            logger.warning(
                f"'{store_path}', task {task}: '{variable}' already holds data for "
                f"{store_times[start]}..{store_times[stop - 1]}, left by a run that "
                "never recorded the task. Overwriting it."
            )
        return start

    def _fill_blocks(self, plans: list[_LevelPlan], block: int, task: tuple) -> None:
        """Fill every level's reserved region, one time block at a time.

        Each block is computed for all levels in one `dask.compute()` call,
        since the coarser levels derive from the finer ones.

        Args:
            plans (list[_LevelPlan]): One plan per level, from
                `_reserve_level()`.
            block (int): Timesteps per block, from `_block_timesteps()`.
            task (tuple): Task identifier, for the progress bar.
        """
        steps = plans[0].ds.sizes["time"]
        # region= writes the data variable alone: the store owns every
        # coordinate already, and xarray rejects ones without the region dim.
        slabs = [p.ds[[p.variable]].drop_vars(p.ds[[p.variable]].coords) for p in plans]
        for t0 in tqdm(range(0, steps, block), desc=f"Writing {task}", unit="block"):
            stop = min(t0 + block, steps)
            computed = dask.compute(*[s.isel(time=slice(t0, stop)) for s in slabs])
            for plan, done in zip(plans, computed):
                done.to_zarr(
                    plan.store_path,
                    region={"time": slice(plan.start + t0, plan.start + stop)},
                    consolidated=False,
                )

    def _align_vertical_dims(
        self, ds: xr.Dataset, existing: xr.Dataset, store_path: Path
    ) -> xr.Dataset:
        """Rename `ds`'s vertical dims onto the store's matching coordinates.

        Args:
            ds (xr.Dataset): Incoming Dataset, in the regridder's own base
                dimension names.
            existing (xr.Dataset): The store's current contents.
            store_path (Path): Path from `_store_path()`, for logging.

        Returns:
            xr.Dataset: Same data, with each vertical dim renamed to the
                coordinate it belongs on.
        """
        renames = {}
        for base in _VERTICAL_DIMS:
            if base not in ds.sizes:
                continue
            resolved = self._resolve_vertical_dim(base, ds[base].values, existing)
            if resolved != base:
                renames[base] = resolved
                if resolved not in existing.sizes:
                    logger.info(
                        f"{store_path}: level set {ds[base].values.tolist()} differs "
                        f"from the store's '{base}'; adding '{resolved}'."
                    )
        return ds.rename(renames) if renames else ds

    def _resolve_vertical_dim(
        self, base: str, values: np.ndarray, existing: xr.Dataset
    ) -> str:
        """Return the store dimension name one variable's vertical levels belong on.

        A store holds a single coordinate array per dimension name, so
        variables whose level sets differ can't share one. Variables with
        identical levels share a coordinate; otherwise the first free numbered
        sibling is used.

        Args:
            base (str): Base dimension name, e.g. "level".
            values (np.ndarray): The incoming variable's level values.
            existing (xr.Dataset): The store's current contents.

        Returns:
            str: "<base>" if free or matching, else "<base>_<n>".
        """
        suffix = 0
        while True:
            candidate = base if suffix == 0 else f"{base}_{suffix}"
            if candidate not in existing.sizes:
                return candidate
            if candidate in existing.coords and np.array_equal(
                existing[candidate].values, values
            ):
                return candidate
            suffix += 1

    def _store_exists(self, store_path: Path) -> bool:
        """Whether a store has already been written to disk.

        Args:
            store_path (Path): Path from `_store_path()`.

        Returns:
            bool: True if the store has been written to disk.
        """
        return Path(store_path, "zarr.json").exists()

    def _validate_consistency(
        self, store_path: Path, ds: xr.Dataset, existing: xr.Dataset
    ) -> None:
        """Validate an incoming Dataset's HEALPix attrs against an existing store.

        Args:
            store_path (Path): Path from `_store_path()`, for the error message.
            ds (xr.Dataset): Incoming Dataset about to be appended.
            existing (xr.Dataset): The store's current contents, already
                opened by the caller.

        Raises:
            ValueError: If `healpix_level` or `healpix_order` don't match.
        """
        for attr in ("healpix_level", "healpix_order"):
            existing_value = existing.attrs.get(attr)
            new_value = ds.attrs.get(attr)
            if existing_value != new_value:
                raise ValueError(
                    f"'{attr}' mismatch for store '{store_path}': store has "
                    f"{existing_value!r}, incoming data has {new_value!r}."
                )
