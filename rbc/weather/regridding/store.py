"""STORE.

Shared Zarr store writer for regridded HEALPix pyramids.
"""

import time
from pathlib import Path

import pandas as pd
import xarray as xr
from loguru import logger
from tqdm.dask import TqdmCallback


class HealpixZarrWriter:
    """Owns the single shared Zarr store all sources write their pyramids into.

    One group per (source, level): "<source_name>/level_<n>", inside one shared
    store — not `grid_doctor.save_pyramid()`'s own default of one independent
    store per level (confirmed in the Phase 0 spike); `save_pyramid()` is not
    used here at all. Every write uses `consolidated=False`: confirmed by spike
    that xarray otherwise auto-rewrites a whole-tree metadata blob on the store
    root on every single append, regardless of zarr_format; disabling it keeps
    each group's write scoped to itself, at the cost of directory-listing opens
    instead of one metadata read (an acceptable tradeoff outside cloud object
    storage).

    Attributes:
        store_path (Path): Root Zarr store all sources write their pyramids into.
        min_level (int): Shared coarsest HEALPix level, validated against
            every incoming pyramid.
    """

    def __init__(self, store_path: Path, min_level: int) -> None:
        """Initializes the instance.

        Args:
            store_path (Path): Root Zarr store path. `to_zarr` creates it (and
                any group inside it) on first write.
            min_level (int): Shared coarsest HEALPix level across sources.
        """
        self.store_path = Path(store_path)
        self.min_level = min_level

    def append(
        self, source_name: str, task: tuple, pyramid: dict[int, xr.Dataset]
    ) -> None:
        """Write or grow each level's group for one task's pyramid.

        First write per (source, level) uses `mode="w"`; later writes append
        along time. Not fully crash-atomic — call `GridRegridder.mark_done()`
        only after this returns successfully.

        Args:
            source_name (str): Canonical source name; the top-level group name.
            task (tuple): Task identifier, used only for logging/errors here.
            pyramid (dict[int, xr.Dataset]): HEALPix pyramid to write, keyed
                by level.

        Raises:
            ValueError: If the pyramid is missing the shared `min_level`; if
                an existing group's `healpix_level`/`healpix_order` don't
                match the incoming data; or if any incoming timestamp is
                already present.
        """
        if self.min_level not in pyramid:
            raise ValueError(
                f"Pyramid for task {task} does not include the shared min_level "
                f"({self.min_level}); got levels {sorted(pyramid)}."
            )

        task_start = time.time()
        for level, ds in pyramid.items():
            group = self._group(source_name, level)
            level_start = time.time()

            if self._group_exists(group):
                self._validate_consistency(group, ds)
                incoming_times = set(pd.to_datetime(ds["time"].values))
                overlap = self.already_written(source_name, level) & incoming_times
                if overlap:
                    raise ValueError(
                        f"'{source_name}' level {level}, task {task}: "
                        f"{len(overlap)} incoming timestamp(s) already present in "
                        f"the store (e.g. {sorted(overlap)[0]}). Refusing to "
                        "append duplicates."
                    )
                logger.info(f"{group}: appending task {task}...")
                with TqdmCallback(desc=group):
                    ds.to_zarr(
                        self.store_path,
                        group=group,
                        mode="a",
                        append_dim="time",
                        consolidated=False,
                    )
            else:
                logger.info(f"{group}: creating group for task {task}...")
                with TqdmCallback(desc=group):
                    ds.to_zarr(
                        self.store_path, group=group, mode="w", consolidated=False
                    )

            logger.info(f"{group}: write finished ({time.time() - level_start:.1f}s).")

        logger.info(
            f"'{source_name}' task {task}: all {len(pyramid)} levels written "
            f"({time.time() - task_start:.1f}s total)."
        )

    def already_written(self, source_name: str, level: int) -> set:
        """Return timestamps already present in a (source, level) group.

        Args:
            source_name (str): Canonical source name.
            level (int): HEALPix level.

        Returns:
            set: `pandas.Timestamp` values already written; empty if the
                group doesn't exist yet.
        """
        group = self._group(source_name, level)
        if not self._group_exists(group):
            return set()
        existing = xr.open_zarr(self.store_path, group=group, consolidated=False)
        return set(pd.to_datetime(existing["time"].values))

    def emit_stac_item(
        self, source_name: str, task: tuple, pyramid: dict[int, xr.Dataset]
    ) -> None:
        """No-op hook for future STAC item generation (Phase 5).

        Args:
            source_name (str): Canonical source name.
            task (tuple): Task identifier.
            pyramid (dict[int, xr.Dataset]): The pyramid just written.
        """
        return None

    def _group(self, source_name: str, level: int) -> str:
        """Return the group path for one (source, level) pair.

        Args:
            source_name (str): Canonical source name.
            level (int): HEALPix level.

        Returns:
            str: `<source_name>/level_<level>`.
        """
        return f"{source_name}/level_{level}"

    def _group_exists(self, group: str) -> bool:
        """Whether a group has already been written to the store.

        Args:
            group (str): Group path, e.g. "era5/level_7".

        Returns:
            bool: True if the group has been written to disk.
        """
        return Path(self.store_path, *group.split("/"), "zarr.json").exists()

    def _validate_consistency(self, group: str, ds: xr.Dataset) -> None:
        """Validate an incoming Dataset's HEALPix attrs against an existing group.

        Args:
            group (str): Existing group path.
            ds (xr.Dataset): Incoming Dataset about to be appended.

        Raises:
            ValueError: If `healpix_level` or `healpix_order` don't match.
        """
        existing = xr.open_zarr(self.store_path, group=group, consolidated=False)
        for attr in ("healpix_level", "healpix_order"):
            existing_value = existing.attrs.get(attr)
            new_value = ds.attrs.get(attr)
            if existing_value != new_value:
                raise ValueError(
                    f"'{attr}' mismatch for group '{group}': store has "
                    f"{existing_value!r}, incoming data has {new_value!r}."
                )
