# tests/weather/regridding/test_store.py
"""Tests for rbc.weather.regridding.store: HealpixZarrWriter."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from rbc.weather.regridding.store import HealpixZarrWriter


# ----------------------------------
# Synthetic data helpers
# ----------------------------------
def _make_ds(
    start: int, n: int, healpix_level: int = 7, healpix_order: str = "ring"
) -> xr.Dataset:
    """Build a tiny synthetic HEALPix-shaped Dataset for one level.

    Args:
        start (int): First time index value.
        n (int): Number of timesteps.
        healpix_level (int): Value for the healpix_level attr.
        healpix_order (str): Value for the healpix_order attr.

    Returns:
        xr.Dataset: Dataset with "time"/"cell" dims and one data variable.
    """
    time = np.arange(start, start + n)
    data = np.random.rand(n, 5)
    return xr.Dataset(
        {"T": (("time", "cell"), data)},
        coords={"time": time},
        attrs={"healpix_level": healpix_level, "healpix_order": healpix_order},
    )


def _make_pyramid(
    levels: list[int], start: int, n: int, **attrs
) -> dict[int, xr.Dataset]:
    """Build a small pyramid dict spanning multiple levels, same time range.

    Args:
        levels (list[int]): HEALPix levels to include.
        start (int): First time index value.
        n (int): Number of timesteps.
        **attrs: Overrides forwarded to _make_ds (healpix_level/healpix_order);
            healpix_level defaults to the level itself unless overridden.

    Returns:
        dict[int, xr.Dataset]: Pyramid keyed by level.
    """
    return {
        level: _make_ds(
            start,
            n,
            healpix_level=attrs.get("healpix_level", level),
            healpix_order=attrs.get("healpix_order", "ring"),
        )
        for level in levels
    }


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def writer(tmp_path: Path) -> HealpixZarrWriter:
    """Provide a HealpixZarrWriter rooted at a fresh temporary store.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        HealpixZarrWriter: Writer with min_level=4.
    """
    return HealpixZarrWriter(store_path=Path(tmp_path, "store.zarr"), min_level=4)


# ----------------------------------
# HealpixZarrWriter.append
# ----------------------------------
class TestAppend:
    """Tests for HealpixZarrWriter.append().

    Covers first-write/append, multi-level pyramids, the shared min_level
    guard, duplicate-timestamp rejection, healpix attr consistency, and
    independence between different sources.
    """

    def test_creates_group_on_first_write(self, writer: HealpixZarrWriter) -> None:
        """First write to a (source, level) creates the group with matching content.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([4, 7], start=0, n=3)
        writer.append("era5", (2025, 1), pyramid)

        opened = xr.open_zarr(
            writer.store_path, group="era5/level_7", consolidated=False
        )
        assert list(opened["time"].values) == [0, 1, 2]

    def test_appends_to_existing_group(self, writer: HealpixZarrWriter) -> None:
        """A second write with disjoint timestamps grows the group.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        writer.append("era5", (2025, 2), _make_pyramid([4, 7], start=3, n=2))

        opened = xr.open_zarr(
            writer.store_path, group="era5/level_7", consolidated=False
        )
        assert list(opened["time"].values) == [0, 1, 2, 3, 4]

    def test_writes_every_level_in_pyramid(self, writer: HealpixZarrWriter) -> None:
        """Every level in the pyramid gets its own group, not just one.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", (2025, 1), _make_pyramid([4, 5, 7], start=0, n=2))

        for level in (4, 5, 7):
            opened = xr.open_zarr(
                writer.store_path, group=f"era5/level_{level}", consolidated=False
            )
            assert list(opened["time"].values) == [0, 1]

    def test_missing_min_level_raises(self, writer: HealpixZarrWriter) -> None:
        """A pyramid missing the shared min_level raises ValueError.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([7], start=0, n=2)  # writer.min_level is 4
        with pytest.raises(ValueError, match="min_level"):
            writer.append("era5", (2025, 1), pyramid)

    def test_duplicate_timestamp_raises(self, writer: HealpixZarrWriter) -> None:
        """Re-appending overlapping timestamps raises ValueError.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        with pytest.raises(ValueError, match="already present"):
            writer.append("era5", (2025, 1), _make_pyramid([4, 7], start=0, n=3))

    def test_mismatched_healpix_attrs_raises(self, writer: HealpixZarrWriter) -> None:
        """Appending data with a different healpix_order raises ValueError.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append(
            "era5", (2025, 1), _make_pyramid([4, 7], start=0, n=3, healpix_order="ring")
        )
        mismatched = _make_pyramid([4, 7], start=3, n=2, healpix_order="nested")
        with pytest.raises(ValueError, match="healpix_order"):
            writer.append("era5", (2025, 2), mismatched)

    def test_different_sources_stay_independent(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Appending to one source never touches another source's data.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        writer.append("barra2_c2", (2025, 1), _make_pyramid([4, 7], start=100, n=2))

        writer.append("era5", (2025, 2), _make_pyramid([4, 7], start=3, n=2))

        barra_opened = xr.open_zarr(
            writer.store_path, group="barra2_c2/level_7", consolidated=False
        )
        assert list(barra_opened["time"].values) == [100, 101]


# ----------------------------------
# HealpixZarrWriter.already_written
# ----------------------------------
class TestAlreadyWritten:
    """Tests for HealpixZarrWriter.already_written()."""

    def test_returns_empty_for_nonexistent_group(
        self, writer: HealpixZarrWriter
    ) -> None:
        """A source/level nobody has written yet returns an empty set.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        assert writer.already_written("era5", 7) == set()

    def test_returns_correct_timestamps_after_write(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Returns exactly the timestamps that were written.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        written = writer.already_written("era5", 7)
        assert written == set(pd.to_datetime(np.array([0, 1, 2])))
