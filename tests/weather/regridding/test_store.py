# tests/weather/regridding/test_store.py
"""Tests for rbc.weather.regridding.store: HealpixZarrWriter."""

import json
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
# HealpixZarrWriter.checkpoint_path
# ----------------------------------
class TestCheckpointPath:
    """Tests for HealpixZarrWriter.checkpoint_path()."""

    def test_returns_model_and_time_res_specific_path(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Returns "<base_dir>/<model_name>/<time_res>/status.pickle".

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        path = writer.checkpoint_path("barra2_c2", "1h")
        assert path == Path(writer.base_dir, "barra2_c2", "1h", "status.pickle")

    def test_different_model_or_time_res_gives_different_path(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Distinct (model_name, time_res) combinations never collide.

        Directly guards against the bug this replaced: a single checkpoint
        file shared across every model variant, keyed only by (year, month),
        would wrongly mark one variant's tasks done just because another
        variant with the same raw_dir had already been regridded.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        r2 = writer.checkpoint_path("barra2_r2", "1h")
        c2 = writer.checkpoint_path("barra2_c2", "1h")
        c2_20min = writer.checkpoint_path("barra2_c2", "20min")
        assert len({r2, c2, c2_20min}) == 3


# ----------------------------------
# HealpixZarrWriter.weights_cache_dir
# ----------------------------------
class TestWeightsCacheDir:
    """Tests for HealpixZarrWriter.weights_cache_dir()."""

    def test_returns_model_specific_path(self, writer: HealpixZarrWriter) -> None:
        """Returns "<base_dir>/<model_name>/weights_cache/".

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        path = writer.weights_cache_dir("barra2_c2")
        assert path == Path(writer.base_dir, "barra2_c2", "weights_cache")

    def test_different_models_get_different_paths(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Different models never share a weights_cache_dir.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        assert writer.weights_cache_dir("barra2_c2") != writer.weights_cache_dir(
            "barra2_r2"
        )


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

    def test_encoding_applied_on_first_write(self, writer: HealpixZarrWriter) -> None:
        """A passed encoding packs the variable, and decodes back correctly.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([4], start=0, n=3)
        original = pyramid[4]["T"].values.copy()
        encoding = {
            "dtype": "int16",
            "scale_factor": 0.0001,
            "add_offset": 0.0,
            "_FillValue": -32767,
        }

        writer.append("era5", "1h", (2025, 1), pyramid, encoding=encoding)

        store_path = Path(writer.base_dir, "era5", "1h", "level_4.zarr")
        on_disk = xr.open_zarr(store_path, consolidated=False, mask_and_scale=False)
        decoded = xr.open_zarr(store_path, consolidated=False)

        assert on_disk["T"].dtype == np.dtype("int16")
        np.testing.assert_allclose(decoded["T"].values, original, atol=0.0001)

    def test_no_encoding_keeps_default_dtype(self, writer: HealpixZarrWriter) -> None:
        """Omitting encoding leaves Zarr's own default dtype untouched.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([4], start=0, n=3)
        writer.append("era5", "1h", (2025, 1), pyramid)

        store_path = Path(writer.base_dir, "era5", "1h", "level_4.zarr")
        on_disk = xr.open_zarr(store_path, consolidated=False, mask_and_scale=False)
        assert on_disk["T"].dtype == np.dtype("float64")

    def test_encoding_applied_when_adding_new_sibling_variable(
        self, writer: HealpixZarrWriter
    ) -> None:
        """A new sibling variable is packed too, independent of existing ones.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        first = _make_pyramid([4], start=0, n=3)
        writer.append("era5", "1h", (2025, 1), first)  # "T", no encoding

        second = _make_pyramid([4], start=0, n=3)
        second[4] = second[4].rename_vars({"T": "U"})
        original_u = second[4]["U"].values.copy()
        encoding = {
            "dtype": "int16",
            "scale_factor": 0.0001,
            "add_offset": 0.0,
            "_FillValue": -32767,
        }
        writer.append("era5", "1h", (2025, 1), second, encoding=encoding)

        store_path = Path(writer.base_dir, "era5", "1h", "level_4.zarr")
        on_disk = xr.open_zarr(store_path, consolidated=False, mask_and_scale=False)
        decoded = xr.open_zarr(store_path, consolidated=False)

        assert on_disk["T"].dtype == np.dtype("float64")  # untouched
        assert on_disk["U"].dtype == np.dtype("int16")
        np.testing.assert_allclose(decoded["U"].values, original_u, atol=0.0001)


# ----------------------------------
# HealpixZarrWriter — compression
# ----------------------------------
def _codecs(store_path: Path, variable: str = "T") -> list[dict]:
    """Return the codec list Zarr recorded for one variable.

    Args:
        store_path (Path): A level store path.
        variable (str): Variable name. Defaults to "T".

    Returns:
        list[dict]: The "codecs" entries from the variable's zarr.json.
    """
    with open(Path(store_path, variable, "zarr.json")) as f:
        return json.load(f)["codecs"]


class TestCompression:
    """Tests for HealpixZarrWriter's compressor/shuffle codec pipeline."""

    def test_default_is_blosc_zlib_with_shuffle(
        self, writer: HealpixZarrWriter
    ) -> None:
        """The default pipeline is Blosc zlib-1 + byte shuffle, and round-trips exactly.

        Args:
            writer (HealpixZarrWriter): Writer under test (default settings).
        """
        pyramid = _make_pyramid([4], start=0, n=3)
        original = pyramid[4]["T"].values.copy()
        writer.append("era5", "1h", (2025, 1), pyramid)

        store_path = Path(writer.base_dir, "era5", "1h", "level_4.zarr")
        codecs = _codecs(store_path)
        assert [c["name"] for c in codecs] == ["bytes", "blosc"]
        assert codecs[1]["configuration"]["cname"] == "zlib"
        assert codecs[1]["configuration"]["clevel"] == 1
        assert codecs[1]["configuration"]["shuffle"] == "shuffle"
        np.testing.assert_array_equal(
            xr.open_zarr(store_path, consolidated=False)["T"].values, original
        )

    @pytest.mark.parametrize(
        "compressor, shuffle, expected",
        [
            ("zlib", True, ["bytes", "blosc"]),
            ("zstd", True, ["bytes", "blosc"]),
            ("zlib", False, ["bytes", "gzip"]),
            ("zstd", False, ["bytes", "zstd"]),
            ("none", True, ["bytes"]),
            ("none", False, ["bytes"]),
        ],
    )
    def test_pipeline_per_setting(
        self, tmp_path: Path, compressor: str, shuffle: bool, expected: list[str]
    ) -> None:
        """Each (compressor, shuffle) choice maps to the right codecs and round-trips.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
            compressor (str): Compressor setting under test.
            shuffle (bool): Shuffle setting under test.
            expected (list[str]): Expected codec names in zarr.json.
        """
        writer = HealpixZarrWriter(
            base_dir=Path(tmp_path, "p"),
            min_level=4,
            compressor=compressor,
            shuffle=shuffle,
        )
        pyramid = _make_pyramid([4], start=0, n=3)
        original = pyramid[4]["T"].values.copy()
        writer.append("era5", "1h", (2025, 1), pyramid)

        store_path = Path(writer.base_dir, "era5", "1h", "level_4.zarr")
        assert [c["name"] for c in _codecs(store_path)] == expected
        np.testing.assert_array_equal(
            xr.open_zarr(store_path, consolidated=False)["T"].values, original
        )

    def test_compression_merges_with_packing_encoding(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Packing (dtype/scale) and the codec pipeline apply together.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([4], start=0, n=3)
        encoding = {
            "dtype": "int16",
            "scale_factor": 0.0001,
            "add_offset": 0.0,
            "_FillValue": -32767,
        }
        writer.append("era5", "1h", (2025, 1), pyramid, encoding=encoding)

        store_path = Path(writer.base_dir, "era5", "1h", "level_4.zarr")
        on_disk = xr.open_zarr(store_path, consolidated=False, mask_and_scale=False)
        assert on_disk["T"].dtype == np.dtype("int16")
        assert [c["name"] for c in _codecs(store_path)] == ["bytes", "blosc"]

    def test_level_below_one_raises(self, tmp_path: Path) -> None:
        """Level 0 is rejected, since Blosc would silently write uncompressed.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        with pytest.raises(ValueError, match="compression_level must be >= 1"):
            HealpixZarrWriter(base_dir=tmp_path, min_level=4, compression_level=0)

    def test_unknown_compressor_raises(self, tmp_path: Path) -> None:
        """An unknown compressor name is rejected.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        with pytest.raises(ValueError, match="Unknown compressor"):
            HealpixZarrWriter(base_dir=tmp_path, min_level=4, compressor="lz4")


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
