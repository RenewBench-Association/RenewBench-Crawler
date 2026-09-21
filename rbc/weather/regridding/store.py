"""STORE.

Zarr writer for regridded HEALPix pyramids, per the weather Zarr contract
(modeled on DKRZ's Waterpark).
"""

import time
from collections.abc import Hashable
from pathlib import Path
from typing import Literal

import dask
import dask.array
import numpy as np
import pandas as pd
import xarray as xr
from loguru import logger
from tqdm import tqdm
from zarr.codecs import BloscCodec, GzipCodec, ZstdCodec

# Vertical dimensions the contract uses, in the order they appear between
# "time" and "cell". A store holds one coordinate array per dimension name,
# so variables whose level sets differ get numbered siblings
# ("level", "level_1", ...) -- see _resolve_vertical_dim().
_VERTICAL_DIMS = ("level", "height", "model_level")

# Target uncompressed bytes per Zarr chunk. Chunks are otherwise inherited
# from the incoming dask array, which for GRIB sources is one monolithic
# chunk per month (cfgrib doesn't chunk natively) -- that overruns the
# codecs' hard 2 GiB buffer limit on anything but the smallest domains
# ("Codec does not support buffers of > 2147483647 bytes"), and left BARRA2
# only just under it at 1.7 GB.
_TARGET_CHUNK_BYTES = 64 * 1024**2

# Timesteps per chunk. Divides every real month length (hourly months are
# multiples of 24, 20-minute months multiples of 72), so a month written as
# one region always starts on a chunk boundary. GridRegridder chunks sources
# by it too, so dask chunks line up with Zarr chunks.
TIME_CHUNK = 24

# Default megabytes one time block of the pyramid may occupy, before the
# source chunk, the float64 regrid intermediates and the lattice-rounding
# temporaries that are live alongside it. A whole month of a 3D global
# variable at level 9 would be ~250 GB, which is what blocking it bounds.
# GridRegridder sizes its source chunks by the same budget.
DEFAULT_BLOCK_MB = 512

# Source chunks a single block may pull through the regrid. Each one is
# already sized to the memory budget by GridRegridder._chunk_along_time(), so
# this is what keeps the input side bounded when the written pyramid is small
# enough that the budget alone would allow a whole month per block.
_MAX_CHUNKS_PER_BLOCK = 4


class HealpixZarrWriter:
    """Writes regridded HEALPix pyramids into per-(model, time_res, level) Zarr stores.

    Layout: "<base_dir>/<model_name>/<time_res>/level_<N>.zarr" -- one
    independent Zarr store per (model_name, time_res, level). Surface,
    pressure-level, height-level, and model-level variables coexist as
    differently-shaped variables within the same store (distinguished by
    their own dimensions, e.g. [time, cell] vs. [time, level, cell]), per
    the contract's "separation... as standard in other Zarr stores" clause.

    Every write uses `consolidated=False`, since Zarr itself still flags
    consolidated metadata as not yet part of the v3 spec. Compression is one
    writer-wide codec pipeline (see `_build_compressors()`), applied on
    every variable's first write.

    Attributes:
        base_dir (Path): Root directory the per-(model, time_res, level)
            Zarr stores are written under.
        min_level (int): Shared coarsest HEALPix level, validated against
            every incoming pyramid.
        compressors (tuple | None): Zarr codec pipeline applied on every
            variable's first write; None writes raw bytes.
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
            base_dir (Path): Root directory for the per-(model, time_res,
                level) Zarr stores. `to_zarr` creates the full nested path
                on first write.
            min_level (int): Shared coarsest HEALPix level across sources.
            compressor (str): "zlib", "zstd", or "none". Defaults to "zlib".
            compression_level (int): Codec level, >= 1 -- Blosc treats 0 as
                "no compression". Defaults to 1.
            shuffle (bool): Byte-shuffle before compressing, the filter NetCDF
                itself uses (measured ~1.4x smaller on packed int32). Ignored
                for "none". Defaults to True.
            block_memory_mb (int): How much of the pyramid to compute and
                write at a time (see `_block_timesteps()`). Peak RSS runs
                roughly 3.5x this; lower it on a memory-tight node, raise it
                to regrid more of the month in parallel.

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
        through Blosc (which bundles it with zlib/zstd); unshuffled ones use
        the plain Gzip/Zstd codecs. Measured on real BARRA2 data: shuffle is
        what makes packed int32 compress well (the level barely matters),
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
                f"compression_level must be >= 1, got {level} (Blosc treats 0 as "
                "no compression)."
            )
        if shuffle:
            # Annotated ternary rather than passing `compressor` straight
            # through, so the already-validated value narrows to the Literal
            # BloscCodec expects.
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

        Each `ds` in `pyramid` carries exactly one data variable. Every
        level's store is first reserved over the time range it needs, all NaN
        (`_reserve()`), growing the shared time axis for every variable at
        once where the store already exists (`_extend_time_axis()`). The
        values are then filled in one time block at a time, every level from
        the same computation (`_fill_blocks()`) -- a whole month of a 3D
        global pyramid is hundreds of GB and never fits in memory. The store
        stays shape-consistent and readable after every single write.

        `encoding` (e.g. from `GridRegridder.encoding_for()`) is merged with
        this writer's compression pipeline, and only applies when a variable
        is written for the first time -- appending new timestamps to an
        existing variable writes into its already-fixed on-disk schema.

        A vertical dimension is renamed to a numbered sibling when its level
        values differ from the store's existing ones (see
        `_resolve_vertical_dim()`), so variables on different pressure/height
        level sets can coexist.

        Not fully crash-atomic — call `GridRegridder.mark_done()` only after
        this returns successfully.

        Args:
            model_name (str): Contract "model_name" (e.g. "barra2_c2" --
                shared by barra2_c2 and barra2_c2_20min, distinguished by
                time_res instead).
            time_res (str): "1h" or "20min".
            task (tuple): Task identifier, used only for logging/errors here.
            pyramid (dict[int, xr.Dataset]): HEALPix pyramid to write, keyed
                by level.
            encoding (dict | None): Packing encoding for this pyramid's one
                variable (e.g. `{"dtype": "int32", "scale_factor": ...}`),
                applied only on that variable's first write. None packs
                nothing; compression still applies.
            quantization_step (float | None): The source's own precision step
                (see `GridRegridder.quantization_step()`). Values are snapped
                onto that lattice before writing, discarding mantissa bits
                the source never carried. None writes values unchanged.

        Raises:
            ValueError: If the pyramid is missing the shared `min_level`; if
                an existing store's `healpix_level`/`healpix_order` don't
                match the incoming data; if the new timestamps start before
                the store's existing range; or if the slice being written
                already holds data.
        """
        if self.min_level not in pyramid:
            raise ValueError(
                f"Pyramid for task {task} does not include the shared min_level "
                f"({self.min_level}); got levels {sorted(pyramid)}."
            )

        task_start = time.time()
        chunk, block = self._block_timesteps(pyramid)
        plans: list[tuple[Path, xr.Dataset, Hashable, int]] = []
        for level, ds in pyramid.items():
            ds = self._normalize_dim_order(ds)
            ds = self._snap_to_lattice(ds, quantization_step)
            (variable,) = ds.data_vars
            store_path = self._store_path(model_name, time_res, level)
            var_encoding: dict = {**(encoding or {}), "compressors": self.compressors}
            var_encoding["chunks"] = self._chunk_shape(
                ds[variable], var_encoding, chunk
            )
            zarr_encoding = {variable: var_encoding}

            if self._store_exists(store_path):
                existing = xr.open_zarr(store_path, consolidated=False)
                self._validate_consistency(store_path, ds, existing=existing)
                ds = self._align_vertical_dims(ds, existing, store_path)
                existing = self._extend_time_axis(store_path, existing, ds, task)

                if variable not in existing.data_vars:
                    logger.info(
                        f"{store_path}: adding new variable '{variable}' for task "
                        f"{task}..."
                    )
                    # Reserve the variable across the store's full time axis so
                    # every variable spans one shared "time" axis, NaN for the
                    # months it has no data for.
                    self._reserve(
                        store_path, ds, existing["time"], zarr_encoding, chunk, "a"
                    )
                    existing = xr.open_zarr(store_path, consolidated=False)
                start = self._region_start(store_path, ds, variable, existing, task)
            else:
                logger.info(f"{store_path}: creating store for task {task}...")
                self._reserve(store_path, ds, ds["time"], zarr_encoding, chunk, "w")
                start = 0

            plans.append((store_path, ds, variable, start))

        self._fill_blocks(plans, block, task)
        logger.info(
            f"'{model_name}/{time_res}' task {task}: all {len(pyramid)} levels "
            f"written ({time.time() - task_start:.1f}s total)."
        )

    def already_written(self, model_name: str, time_res: str, level: int) -> set:
        """Return the timestamps a (model, time_res, level) store's time axis spans.

        This is the store-wide axis, not a per-variable record: since
        variables are NaN-padded to a shared time range, a timestamp here
        doesn't mean every variable has data for it. `GridRegridder`'s
        checkpoint, keyed by `(year, month, variable)`, is what actually
        tracks regridded work.

        Args:
            model_name (str): Contract "model_name".
            time_res (str): "1h" or "20min".
            level (int): HEALPix level.

        Returns:
            set: `pandas.Timestamp` values on the store's time axis; empty if
                the store doesn't exist yet.
        """
        store_path = self._store_path(model_name, time_res, level)
        if not self._store_exists(store_path):
            return set()
        existing = xr.open_zarr(store_path, consolidated=False)
        return set(pd.to_datetime(existing["time"].values))

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
        """Return the checkpoint file path for one (model_name, time_res) combination.

        Checkpointing tracks what a `GridRegridder` has actually finished
        writing to this destination store, so it lives alongside the Zarr
        stores it corresponds to.

        Args:
            model_name (str): Contract "model_name".
            time_res (str): "1h" or "20min".

        Returns:
            Path: "<base_dir>/<model_name>/<time_res>/status.pickle".
        """
        return Path(self.base_dir, model_name, time_res, "status.pickle")

    def weights_cache_dir(self, model_name: str) -> Path:
        """Return the ESMF weight-cache directory for one model_name.

        Keyed by model_name only, because weights depend solely on
        horizontal grid geometry (grid-doctor's own cache key is derived from
        the actual coordinate arrays), which is identical across temporal
        resolutions of the same physical grid.

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

    def _normalize_dim_order(self, ds: xr.Dataset) -> xr.Dataset:
        """Enforce the contract's dimension order: time, then a vertical dim, then cell.

        Upstream regridding steps (e.g. xr.concat() prepending a new vertical
        dimension) don't reliably produce "(time, level, cell)" order --
        confirmed on real BARRA2 data coming out as "(level, time, cell)"
        instead. Applies uniformly regardless of which vertical dim (level,
        height, model_level) or none a given variable has.

        Args:
            ds (xr.Dataset): Dataset about to be written.

        Returns:
            xr.Dataset: Same data, with every variable's dims reordered.
        """
        return ds.transpose(
            "time", "level", "height", "model_level", "cell", missing_dims="ignore"
        )

    def _snap_to_lattice(self, ds: xr.Dataset, step: float | None) -> xr.Dataset:
        """Round values onto the source's own precision lattice.

        `round(x / step) * step`, which is exact in float32 for the
        power-of-two steps every source uses (confirmed on real data: BARRA2
        scale factors and the GRIB binary scale factors are all powers of
        two). Error is at most half a step, so the result stays within what
        the source itself could represent -- the discarded bits are
        regridding artefacts, not information.

        Args:
            ds (xr.Dataset): Dataset about to be written.
            step (float | None): Source precision step; None leaves `ds`
                untouched.

        Returns:
            xr.Dataset: Same data, snapped onto the lattice.
        """
        if not step:
            return ds
        # keep_attrs: _validate_consistency() reads healpix_level/order off
        # the Dataset, and variable attrs (units, cell_methods) must survive.
        with xr.set_options(keep_attrs=True):
            return (ds / step).round() * step

    def _chunk_shape(
        self, da: xr.DataArray, encoding: dict, time_chunk: int
    ) -> tuple[int, ...]:
        """Return a chunk shape bounded by `_TARGET_CHUNK_BYTES`.

        Keeps vertical levels whole (there are few of them, and they're
        usually read together) and splits "cell" to fit the remaining budget.
        Sized from the *encoded* dtype, since that's what the codec actually
        sees.

        Args:
            da (xr.DataArray): The variable about to be written, already in
                the contract's dimension order.
            encoding (dict): This variable's encoding, read for its "dtype"
                when the variable is packed.
            time_chunk (int): Timesteps per chunk, from `_block_timesteps()`,
                so that each written block covers whole chunks.

        Returns:
            tuple[int, ...]: Chunk size per dimension, in `da.dims` order.
        """
        itemsize = np.dtype(encoding.get("dtype", da.dtype)).itemsize
        sizes = dict(da.sizes)
        time_chunk = min(time_chunk, sizes.get("time", 1))

        vertical = 1
        for dim, size in sizes.items():
            if dim != "time" and dim != "cell":
                vertical *= size

        budget = _TARGET_CHUNK_BYTES // (itemsize * time_chunk * vertical)
        cell_chunk = max(1, min(budget, sizes.get("cell", 1)))

        return tuple(
            time_chunk if dim == "time" else cell_chunk if dim == "cell" else sizes[dim]
            for dim in da.dims
        )

    def _extend_time_axis(
        self, store_path: Path, existing: xr.Dataset, ds: xr.Dataset, task: tuple
    ) -> xr.Dataset:
        """Grow the store's shared time axis to cover `ds`'s new timestamps.

        "time" is one dimension shared by every variable in a store, so it
        has to grow for all of them at once -- extending it while writing
        only one variable leaves the others short, and the store then can't
        be opened at all. Every variable is therefore extended together here
        (NaN over the new range, written lazily), and the real values are
        filled in per variable afterwards by `_write_region()`.

        Args:
            store_path (Path): Path from `_store_path()`.
            existing (xr.Dataset): The store's current contents.
            ds (xr.Dataset): Incoming Dataset for one variable.
            task (tuple): Task identifier, for logging/errors.

        Returns:
            xr.Dataset: The store's contents, re-opened if it was extended.

        Raises:
            ValueError: If the new timestamps start before the store's last
                one, which would need inserting rather than extending.
        """
        # pd.Index, not pd.to_datetime: the time coordinate's own dtype is
        # what has to line up with the store when reindexing.
        existing_times = pd.Index(existing["time"].values)
        incoming_times = pd.Index(ds["time"].values)
        new_times = incoming_times.difference(existing_times)
        if new_times.empty:
            return existing

        if len(existing_times) and new_times.min() < existing_times.max():
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
        template = existing.isel(time=slice(0, 0))
        template.reindex(time=new_times).to_zarr(
            store_path, mode="a", append_dim="time", consolidated=False
        )
        return xr.open_zarr(store_path, consolidated=False)

    def _block_timesteps(self, pyramid: dict[int, xr.Dataset]) -> tuple[int, int]:
        """Return the Zarr time chunk and how many timesteps to write at a time.

        One block of every level is in memory at once, so the block is sized
        to keep that under `block_bytes` -- a whole month of a 3D global
        variable is hundreds of GB and never fits. A block is a whole number
        of the incoming dask chunks, so each source chunk is read once rather
        than re-read by every block overlapping it, and so regions stay
        aligned with the Zarr chunks written here.

        Args:
            pyramid (dict[int, xr.Dataset]): The pyramid about to be written.

        Returns:
            tuple[int, int]: (timesteps per Zarr chunk, timesteps per block).
        """
        per_step = 0
        incoming = 0
        for ds in pyramid.values():
            for da in ds.data_vars.values():
                cells = int(np.prod([s for d, s in da.sizes.items() if d != "time"]))
                per_step += cells * da.dtype.itemsize
                incoming = max(incoming, max(da.chunksizes.get("time", (0,))))
        budget = max(1, int(self.block_bytes // max(per_step, 1)))
        # An eagerly computed pyramid (the regional path) has no chunks to
        # follow, so the contract's own time chunk applies.
        unit = min(incoming or TIME_CHUNK, TIME_CHUNK, budget)
        # The budget above only covers what is written. The source feeding a
        # block costs memory too, and can dwarf it where the target is much
        # coarser than the source (a regional pyramid's compact levels), so a
        # block also holds only a few of the regridder's already budget-sized
        # source chunks.
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

        The NaN array is built chunked and lazily, so this writes the store's
        chunks without computing any regridded value and without ever holding
        the variable in memory; `_fill_blocks()` fills them in afterwards.
        (`reindex()` on a 0-length array would look simpler but materializes
        the whole span as one NumPy array -- tens of GB for a 3D global
        variable.)

        Args:
            store_path (Path): Path from `_store_path()`.
            ds (xr.Dataset): Incoming Dataset for one variable.
            times (xr.DataArray): Time axis the variable should span.
            encoding (dict): Zarr encoding for the one variable.
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
            # Coordinates along time belong to the incoming slice, not to the
            # span being reserved, so only the others carry over.
            coords={
                **{k: v for k, v in ds.coords.items() if "time" not in v.dims},
                "time": times,
            },
            attrs=ds.attrs,
        )
        template.to_zarr(store_path, mode=mode, encoding=encoding, consolidated=False)

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
            task (tuple): Task identifier, for logging/errors.

        Returns:
            int: Index of `ds`'s first timestamp on the store's time axis.

        Raises:
            ValueError: If the incoming timestamps aren't a contiguous run in
                the store, or if that slice already holds data.
        """
        store_times = pd.Index(existing["time"].values)
        incoming_times = pd.Index(ds["time"].values)
        positions = store_times.get_indexer(incoming_times)
        start, stop = int(positions.min()), int(positions.max()) + 1
        if stop - start != len(positions):
            raise ValueError(
                f"'{store_path}', task {task}: '{variable}' timestamps aren't a "
                "contiguous run in the store, so they can't be written as one region."
            )

        written = existing[variable].isel(time=slice(start, stop))
        if bool(written.notnull().any()):
            raise ValueError(
                f"'{store_path}', task {task}: '{variable}' is already present for "
                f"{store_times[start]}..{store_times[stop - 1]}. Refusing to "
                "overwrite it."
            )
        return start

    def _fill_blocks(
        self,
        plans: list[tuple[Path, xr.Dataset, Hashable, int]],
        block: int,
        task: tuple,
    ) -> None:
        """Fill every level's reserved region, one time block at a time.

        Each block is computed for all levels in one `dask.compute()` call:
        the coarser levels derive from the finer ones, so computing them
        separately would repeat the regrid per level.

        Args:
            plans (list): One (store_path, ds, variable, start) per level.
            block (int): Timesteps per block, from `_block_timesteps()`.
            task (tuple): Task identifier, for the progress bar.
        """
        steps = plans[0][1].sizes["time"]
        # region= writes only the data variable; the store already owns every
        # coordinate, and xarray rejects ones that lack the region dimension.
        slabs = [
            ds[[variable]].drop_vars(ds[[variable]].coords)
            for _, ds, variable, _ in plans
        ]
        for t0 in tqdm(range(0, steps, block), desc=f"Writing {task}", unit="block"):
            stop = min(t0 + block, steps)
            computed = dask.compute(
                *[slab.isel(time=slice(t0, stop)) for slab in slabs]
            )
            for (store_path, _, _, start), done in zip(plans, computed):
                done.to_zarr(
                    store_path,
                    region={"time": slice(start + t0, start + stop)},
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
        variables whose level sets differ can't share one (confirmed on real
        BARRA2 data: "ta" has pressure levels [1000, 950] but "ua" only
        [1000]). Variables with identical levels share a coordinate;
        otherwise the first free numbered sibling is used.

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
            store_path (Path): Path from `_store_path()`, used only for the
                error message.
            ds (xr.Dataset): Incoming Dataset about to be appended.
            existing (xr.Dataset): The store's current contents, already
                opened by the caller (avoids opening it twice).

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
