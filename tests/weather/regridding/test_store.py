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
    """Provide a HealpixZarrWriter rooted at a fresh temporary base directory.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        HealpixZarrWriter: Writer with min_level=4.
    """
    return HealpixZarrWriter(base_dir=Path(tmp_path, "processed"), min_level=4)


# ----------------------------------
# HealpixZarrWriter._normalize_dim_order
# ----------------------------------
class TestNormalizeDimOrder:
    """Tests for HealpixZarrWriter._normalize_dim_order().

    Confirmed against real BARRA2 data that xr.concat() (used to build the
    level/height dims) prepends the new dim first, giving "(level, time,
    cell)" rather than the contract's required "(time, level, cell)" -- this
    normalization step is what fixes that before writing.
    """

    def test_reorders_pressure_level_variable(self, writer: HealpixZarrWriter) -> None:
        """A "(level, time, cell)" variable becomes "(time, level, cell)".

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        ds = xr.Dataset(
            {"temperature": (("level", "time", "cell"), np.zeros((3, 2, 5)))}
        )

        result = writer._normalize_dim_order(ds)

        assert result["temperature"].dims == ("time", "level", "cell")

    def test_surface_variable_unaffected(self, writer: HealpixZarrWriter) -> None:
        """A plain "(time, cell)" variable (no vertical dim) is left as-is.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        ds = xr.Dataset({"t2m": (("time", "cell"), np.zeros((2, 5)))})

        result = writer._normalize_dim_order(ds)

        assert result["t2m"].dims == ("time", "cell")

    def test_surface_and_pressure_level_coexist_correctly(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Mixed surface + pressure-level variables both end up correctly ordered.

        Independent of each other, within one Dataset.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        ds = xr.Dataset(
            {
                "t2m": (("time", "cell"), np.zeros((2, 5))),
                "temperature": (("level", "time", "cell"), np.zeros((3, 2, 5))),
            }
        )

        result = writer._normalize_dim_order(ds)

        assert result["t2m"].dims == ("time", "cell")
        assert result["temperature"].dims == ("time", "level", "cell")

    def test_height_and_model_level_also_reordered(
        self, writer: HealpixZarrWriter
    ) -> None:
        """The same fix applies to "height" and "model_level" dims, not just "level".

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        ds = xr.Dataset(
            {
                "ta_height": (("height", "time", "cell"), np.zeros((2, 2, 5))),
                "t_model": (("model_level", "time", "cell"), np.zeros((4, 2, 5))),
            }
        )

        result = writer._normalize_dim_order(ds)

        assert result["ta_height"].dims == ("time", "height", "cell")
        assert result["t_model"].dims == ("time", "model_level", "cell")


# ----------------------------------
# HealpixZarrWriter.append
# ----------------------------------
class TestAppend:
    """Tests for HealpixZarrWriter.append().

    Covers first-write/append, multi-level pyramids, the shared min_level
    guard, duplicate-timestamp rejection, healpix attr consistency, and
    independence between different (model_name, time_res) combinations.
    """

    def test_creates_store_on_first_write(self, writer: HealpixZarrWriter) -> None:
        """First write to a (model, time_res, level) creates its own store.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([4, 7], start=0, n=3)
        writer.append("era5", "1h", (2025, 1), pyramid)

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_7.zarr"), consolidated=False
        )
        assert list(opened["time"].values) == [0, 1, 2]

    def test_appends_to_existing_store(self, writer: HealpixZarrWriter) -> None:
        """A second write with disjoint timestamps grows the store.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        writer.append("era5", "1h", (2025, 2), _make_pyramid([4, 7], start=3, n=2))

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_7.zarr"), consolidated=False
        )
        assert list(opened["time"].values) == [0, 1, 2, 3, 4]

    def test_writes_every_level_in_pyramid(self, writer: HealpixZarrWriter) -> None:
        """Every level in the pyramid gets its own store, not just one.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 1), _make_pyramid([4, 5, 7], start=0, n=2))

        for level in (4, 5, 7):
            opened = xr.open_zarr(
                Path(writer.base_dir, "era5", "1h", f"level_{level}.zarr"),
                consolidated=False,
            )
            assert list(opened["time"].values) == [0, 1]

    def test_missing_min_level_raises(self, writer: HealpixZarrWriter) -> None:
        """A pyramid missing the shared min_level raises ValueError.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([7], start=0, n=2)  # writer.min_level is 4
        with pytest.raises(ValueError, match="min_level"):
            writer.append("era5", "1h", (2025, 1), pyramid)

    def test_duplicate_timestamp_raises(self, writer: HealpixZarrWriter) -> None:
        """Re-appending overlapping timestamps raises ValueError.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        with pytest.raises(ValueError, match="already present"):
            writer.append("era5", "1h", (2025, 1), _make_pyramid([4, 7], start=0, n=3))

    def test_mismatched_healpix_attrs_raises(self, writer: HealpixZarrWriter) -> None:
        """Appending data with a different healpix_order raises ValueError.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append(
            "era5",
            "1h",
            (2025, 1),
            _make_pyramid([4, 7], start=0, n=3, healpix_order="ring"),
        )
        mismatched = _make_pyramid([4, 7], start=3, n=2, healpix_order="nested")
        with pytest.raises(ValueError, match="healpix_order"):
            writer.append("era5", "1h", (2025, 2), mismatched)

    def test_different_models_stay_independent(self, writer: HealpixZarrWriter) -> None:
        """Appending to one model_name never touches another's data.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        writer.append(
            "barra2_c2", "1h", (2025, 1), _make_pyramid([4, 7], start=100, n=2)
        )

        writer.append("era5", "1h", (2025, 2), _make_pyramid([4, 7], start=3, n=2))

        barra_opened = xr.open_zarr(
            Path(writer.base_dir, "barra2_c2", "1h", "level_7.zarr"),
            consolidated=False,
        )
        assert list(barra_opened["time"].values) == [100, 101]

    def test_different_time_res_stay_independent(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Same model_name, different time_res, writes to different stores.

        Models barra2_c2 (1h) and barra2_c2_20min (20min) share one
        model_name but not their store, since time_res distinguishes them.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("barra2_c2", "1h", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        writer.append(
            "barra2_c2", "20min", (2025, 1), _make_pyramid([4, 7], start=100, n=2)
        )

        hourly = xr.open_zarr(
            Path(writer.base_dir, "barra2_c2", "1h", "level_7.zarr"),
            consolidated=False,
        )
        twenty_min = xr.open_zarr(
            Path(writer.base_dir, "barra2_c2", "20min", "level_7.zarr"),
            consolidated=False,
        )
        assert list(hourly["time"].values) == [0, 1, 2]
        assert list(twenty_min["time"].values) == [100, 101]


# ----------------------------------
# HealpixZarrWriter.already_written
# ----------------------------------
class TestAlreadyWritten:
    """Tests for HealpixZarrWriter.already_written()."""

    def test_returns_empty_for_nonexistent_store(
        self, writer: HealpixZarrWriter
    ) -> None:
        """A (model, time_res, level) nobody has written yet returns an empty set.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        assert writer.already_written("era5", "1h", 7) == set()

    def test_returns_correct_timestamps_after_write(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Returns exactly the timestamps that were written.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        written = writer.already_written("era5", "1h", 7)
        assert written == set(pd.to_datetime(np.array([0, 1, 2])))
