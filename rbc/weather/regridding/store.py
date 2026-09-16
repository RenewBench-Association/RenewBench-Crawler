"""STORE.

Zarr writer for regridded HEALPix pyramids, per the weather Zarr contract
(modeled on DKRZ's Waterpark).
"""

import time
from collections.abc import Hashable
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import xarray as xr
from loguru import logger
from tqdm.dask import TqdmCallback
from zarr.codecs import BloscCodec, GzipCodec, ZstdCodec

# Vertical dimensions the contract uses, in the order they appear between
# "time" and "cell". A store holds one coordinate array per dimension name,
# so variables whose level sets differ get numbered siblings
# ("level", "level_1", ...) -- see _resolve_vertical_dim().
_VERTICAL_DIMS = ("level", "height", "model_level")


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
    """

    def __init__(
        self,
        base_dir: Path,
        min_level: int,
        compressor: str = "zlib",
        compression_level: int = 1,
        shuffle: bool = True,
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

        Raises:
            ValueError: If `compressor` is unknown or `compression_level` < 1.
        """
        self.base_dir = Path(base_dir)
        self.min_level = min_level
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
    ) -> None:
        """Write or grow each level's store for one task's single-variable pyramid.

        Each `ds` in `pyramid` carries exactly one data variable. With no
        store yet, `mode="w"` creates it. Otherwise the shared time axis is
        grown for every variable at once (`_extend_time_axis()`), then this
        one variable's slice is filled (`_write_region()`); a variable not in
        the store yet is created spanning the store's full time range, NaN
        where it has no data. The store therefore stays shape-consistent and
        readable after every single write.

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
        for level, ds in pyramid.items():
            ds = self._normalize_dim_order(ds)
            (variable,) = ds.data_vars
            store_path = self._store_path(model_name, time_res, level)
            level_start = time.time()
            zarr_encoding = {
                variable: {**(encoding or {}), "compressors": self.compressors}
            }

            if self._store_exists(store_path):
                existing = xr.open_zarr(store_path, consolidated=False)
                self._validate_consistency(store_path, ds, existing=existing)
                ds = self._align_vertical_dims(ds, existing, store_path)
                existing = self._extend_time_axis(store_path, existing, ds, task)

                if variable in existing.data_vars:
                    self._write_region(store_path, ds, variable, existing, task)
                else:
                    logger.info(
                        f"{store_path}: adding new variable '{variable}' for task "
                        f"{task}..."
                    )
                    # Pad to the store's full time range so every variable
                    # spans one shared "time" axis; reindex fills the months
                    # this variable has no data for lazily, as NaN.
                    padded = ds.reindex(time=existing["time"])
                    with TqdmCallback(desc=str(store_path)):
                        padded.to_zarr(
                            store_path,
                            mode="a",
                            consolidated=False,
                            encoding=zarr_encoding,
                        )
            else:
                logger.info(f"{store_path}: creating store for task {task}...")
                with TqdmCallback(desc=str(store_path)):
                    ds.to_zarr(
                        store_path, mode="w", consolidated=False, encoding=zarr_encoding
                    )

            logger.info(
                f"{store_path}: write finished ({time.time() - level_start:.1f}s)."
            )

        logger.info(
            f"'{model_name}/{time_res}' task {task}: all {len(pyramid)} levels "
            f"written ({time.time() - task_start:.1f}s total)."
        )

    def already_written(self, model_name: str, time_res: str, level: int) -> set:
        """Return timestamps already present in a (model, time_res, level) store.

        Args:
            model_name (str): Contract "model_name".
            time_res (str): "1h" or "20min".
            level (int): HEALPix level.

        Returns:
            set: `pandas.Timestamp` values already written; empty if the
                store doesn't exist yet.
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

    def _write_region(
        self,
        store_path: Path,
        ds: xr.Dataset,
        variable: Hashable,
        existing: xr.Dataset,
        task: tuple,
    ) -> None:
        """Fill one variable's slice of the already-extended time axis.

        Args:
            store_path (Path): Path from `_store_path()`.
            ds (xr.Dataset): Incoming Dataset for one variable.
            variable (Hashable): The variable being written, as unpacked
                from `ds.data_vars`.
            existing (xr.Dataset): The store's contents, time axis already
                covering `ds`.
            task (tuple): Task identifier, for logging/errors.

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

        logger.info(f"{store_path}: filling '{variable}' for task {task}...")
        # region= writes only the data variable; the store already owns every
        # coordinate, and xarray rejects ones that lack the region dimension.
        slab = ds[[variable]]
        slab = slab.drop_vars(list(slab.coords))
        with TqdmCallback(desc=str(store_path)):
            slab.to_zarr(
                store_path, region={"time": slice(start, stop)}, consolidated=False
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
