# tests/weather/regridding/test_store.py
"""Tests for rbc.weather.regridding.store: HealpixZarrWriter."""

import json
from pathlib import Path

import dask.array as dsa
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


def _make_level_pyramid(
    start: int,
    n: int,
    levels: list[float],
    name: str = "T",
    dim: str = "level",
    healpix_level: int = 4,
) -> dict[int, xr.Dataset]:
    """Build a single-level pyramid whose variable carries a vertical dimension.

    Args:
        start (int): First time index value.
        n (int): Number of timesteps.
        levels (list[float]): Vertical coordinate values.
        name (str): Data variable name. Defaults to "T".
        dim (str): Vertical dimension name. Defaults to "level".
        healpix_level (int): Pyramid level to key the dict by.

    Returns:
        dict[int, xr.Dataset]: Pyramid with one level.
    """
    ds = xr.Dataset(
        {name: (("time", dim, "cell"), np.random.rand(n, len(levels), 5))},
        coords={
            "time": np.arange(start, start + n),
            dim: np.asarray(levels, dtype=float),
        },
        attrs={"healpix_level": healpix_level, "healpix_order": "ring"},
    )
    return {healpix_level: ds}


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

    def test_one_checkpoint_per_model_and_time_res(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Returns "<base_dir>/<model_name>/<time_res>/status.pickle", never shared.

        Guards the bug this replaced: one checkpoint shared across model
        variants wrongly marked a variant done because another had run.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        path = writer.checkpoint_path("barra2_c2", "1h")
        assert path == Path(writer.base_dir, "barra2_c2", "1h", "status.pickle")
        assert path != writer.checkpoint_path("barra2_c2", "20min")
        assert path != writer.checkpoint_path("barra2_r2", "1h")


# ----------------------------------
# HealpixZarrWriter.weights_cache_dir
# ----------------------------------
class TestWeightsCacheDir:
    """Tests for HealpixZarrWriter.weights_cache_dir()."""

    def test_one_cache_per_model(self, writer: HealpixZarrWriter) -> None:
        """Returns "<base_dir>/<model_name>/weights_cache/", keyed by model only.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        path = writer.weights_cache_dir("barra2_c2")
        assert path == Path(writer.base_dir, "barra2_c2", "weights_cache")
        assert path != writer.weights_cache_dir("barra2_r2")


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

    def test_every_vertical_dim_moves_between_time_and_cell(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Each variable becomes (time, <vertical>, cell); surface ones are untouched.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        ds = xr.Dataset(
            {
                "t2m": (("time", "cell"), np.zeros((2, 5))),
                "ta": (("level", "time", "cell"), np.zeros((3, 2, 5))),
                "ta_height": (("height", "time", "cell"), np.zeros((2, 2, 5))),
                "t_model": (("model_level", "time", "cell"), np.zeros((4, 2, 5))),
            }
        )

        result = writer._normalize_dim_order(ds)

        assert result["t2m"].dims == ("time", "cell")
        assert result["ta"].dims == ("time", "level", "cell")
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

    def test_models_and_time_res_stay_independent(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Writes to one (model, time_res) never touch another's store.

        barra2_c2 and barra2_c2_20min share one model_name, told apart only
        by time_res.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("barra2_c2", "1h", (2025, 1), _make_pyramid([4, 7], start=0, n=3))
        writer.append(
            "barra2_c2", "20min", (2025, 1), _make_pyramid([4, 7], start=100, n=2)
        )
        writer.append("era5", "1h", (2025, 1), _make_pyramid([4, 7], start=200, n=4))

        def times(model: str, time_res: str) -> list:
            return list(
                xr.open_zarr(
                    Path(writer.base_dir, model, time_res, "level_7.zarr"),
                    consolidated=False,
                )["time"].values
            )

        assert times("barra2_c2", "1h") == [0, 1, 2]
        assert times("barra2_c2", "20min") == [100, 101]
        assert times("era5", "1h") == [200, 201, 202, 203]

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
            # zlib + shuffle is the default, covered above
            ("zstd", True, ["bytes", "blosc"]),
            ("zlib", False, ["bytes", "gzip"]),
            ("zstd", False, ["bytes", "zstd"]),
            ("none", True, ["bytes"]),  # shuffle is ignored without a compressor
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
# HealpixZarrWriter._snap_to_lattice
# ----------------------------------
class TestSnapToLattice:
    """Tests for HealpixZarrWriter._snap_to_lattice().

    Regridding averages the source's evenly spaced values into arbitrary
    floats; snapping back onto the source's own step drops mantissa bits
    the source never carried.
    """

    STEP = 2**-10

    def _ds(self, values: list[float]) -> xr.Dataset:
        """Build a dask-backed one-variable Dataset with HEALPix attrs.

        Args:
            values (list[float]): Values for a single timestep.

        Returns:
            xr.Dataset: Dataset shaped like a regridded pyramid level.
        """
        data = dsa.from_array(np.array([values]), chunks=(1, 2))
        return xr.Dataset(
            {"T": (("time", "cell"), data, {"units": "K"})},
            coords={"time": [0], "latitude": ("cell", np.arange(float(len(values))))},
            attrs={"healpix_level": 4, "healpix_order": "nested"},
        )

    def test_snaps_onto_lattice_within_half_a_step(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Values become exact multiples of the step, off by at most half a step.

        Half a step is the source's own resolution, so this is lossless
        relative to the source.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        values = list(np.random.default_rng(0).uniform(-50, 320, 50))
        snapped = writer._snap_to_lattice(self._ds(values), self.STEP)["T"].values[0]

        assert all(float(v / self.STEP).is_integer() for v in snapped)
        assert np.max(np.abs(snapped - values)) <= self.STEP / 2

    def test_sub_resolution_drizzle_becomes_exact_zero(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Values below half a step were never representable, so snap to zero.

        This is what restores the sparsity averaging destroys.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        out = writer._snap_to_lattice(self._ds([self.STEP / 4, 0.0]), self.STEP)

        assert list(out["T"].values[0]) == [0.0, 0.0]

    def test_preserves_nan_attrs_coords_and_laziness(
        self, writer: HealpixZarrWriter
    ) -> None:
        """NaN, attrs, coordinates and dask backing all survive.

        Dataset attrs matter beyond metadata: _validate_consistency() reads
        healpix_level/healpix_order off the snapped Dataset.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        out = writer._snap_to_lattice(self._ds([np.nan, 1.0]), self.STEP)

        assert np.isnan(out["T"].values[0][0])
        assert out.attrs == {"healpix_level": 4, "healpix_order": "nested"}
        assert out["T"].attrs == {"units": "K"}
        assert list(out["latitude"].values) == [0.0, 1.0]
        assert isinstance(out["T"].data, dsa.Array)

    def test_none_step_is_identity(self, writer: HealpixZarrWriter) -> None:
        """No step leaves the Dataset untouched.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        ds = self._ds([288.1234567])

        assert writer._snap_to_lattice(ds, None) is ds

    def test_append_writes_snapped_values(self, writer: HealpixZarrWriter) -> None:
        """append() applies the step to what lands on disk.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        pyramid = _make_pyramid([4], start=0, n=3)
        writer.append("era5", "1h", (2025, 1), pyramid, quantization_step=self.STEP)

        stored = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )["T"].values
        assert np.all(np.mod(stored, self.STEP) == 0)


# ----------------------------------
# HealpixZarrWriter._chunk_shape
# ----------------------------------
class TestChunkShape:
    """Tests for HealpixZarrWriter._chunk_shape().

    Chunks are otherwise inherited from the incoming dask array, which for
    GRIB sources is one monolithic chunk per month -- that overran the
    codecs' 2 GiB buffer limit on real ICON data.
    """

    CODEC_LIMIT = 2**31 - 1

    def test_stays_under_the_codec_buffer_limit(
        self, writer: HealpixZarrWriter
    ) -> None:
        """The largest real shape (ICON Global, 10 model levels) stays under 2 GiB.

        One month of it as a single chunk would be ~94 GB.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        shape = (744, 10, 3_145_728)  # HEALPix L9, month of hourly data
        # dask, so this real-world shape costs no memory to describe
        da = xr.DataArray(
            dsa.zeros(shape, chunks=shape), dims=("time", "model_level", "cell")
        )

        chunks = writer._chunk_shape(da, {"dtype": "float32"})

        assert np.prod(chunks) * 4 < self.CODEC_LIMIT

    def test_chunks_time_and_keeps_vertical_whole(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Time is blocked, vertical levels stay whole, cell absorbs the rest.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        da = xr.DataArray(np.zeros((744, 3, 100_000)), dims=("time", "level", "cell"))

        t_chunk, lev_chunk, cell_chunk = writer._chunk_shape(da, {"dtype": "float32"})

        assert t_chunk == 24
        assert lev_chunk == 3  # kept whole
        assert 0 < cell_chunk <= 100_000

    def test_small_arrays_are_not_over_chunked(self, writer: HealpixZarrWriter) -> None:
        """An array smaller than the budget is written as a single chunk.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        da = xr.DataArray(np.zeros((3, 5)), dims=("time", "cell"))

        assert writer._chunk_shape(da, {"dtype": "float64"}) == (3, 5)

    def test_encoded_dtype_drives_the_budget(self, writer: HealpixZarrWriter) -> None:
        """Packing to a narrower dtype allows proportionally more cells per chunk.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        da = xr.DataArray(
            dsa.zeros((744, 5_000_000), chunks=(744, 5_000_000)), dims=("time", "cell")
        )

        wide = writer._chunk_shape(da, {"dtype": "float64"})[1]
        narrow = writer._chunk_shape(da, {"dtype": "int16"})[1]

        # 4x, give or take integer-division rounding
        assert narrow == pytest.approx(wide * 4, rel=1e-6)


# ----------------------------------
# HealpixZarrWriter — shared time axis across variables
# ----------------------------------
def _named(pyramid: dict[int, xr.Dataset], name: str) -> dict[int, xr.Dataset]:
    """Rename a pyramid's single data variable.

    Args:
        pyramid (dict[int, xr.Dataset]): Pyramid to rename.
        name (str): New variable name.

    Returns:
        dict[int, xr.Dataset]: Pyramid with the variable renamed.
    """
    return {lvl: ds.rename_vars({"T": name}) for lvl, ds in pyramid.items()}


class TestSharedTimeAxis:
    """Tests for growing the store-wide time axis across several variables.

    "time" is one dimension shared by every variable, so it has to grow for
    all of them together. Extending it while writing only one variable left
    the others short and made the whole store unopenable -- these cover that
    directly, since it breaks any store with 2+ variables on its 2nd month.
    """

    def test_two_variables_across_two_months(self, writer: HealpixZarrWriter) -> None:
        """Every variable stays full length across a second month.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        for name in ("tas", "clt"):
            writer.append(
                "era5", "1h", (2025, 1), _named(_make_pyramid([4], 0, 3), name)
            )
        for name in ("tas", "clt"):
            writer.append(
                "era5", "1h", (2025, 2), _named(_make_pyramid([4], 3, 2), name)
            )

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )
        assert list(opened["time"].values) == [0, 1, 2, 3, 4]
        assert opened["tas"].sizes["time"] == 5
        assert opened["clt"].sizes["time"] == 5
        assert not opened["tas"].isnull().any()
        assert not opened["clt"].isnull().any()

    def test_store_stays_readable_between_variables(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Mid-month, before every variable is filled, the store still opens.

        The old failure mode left the store unopenable at exactly this point,
        which also broke the next variable's own consistency check.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        for name in ("tas", "clt"):
            writer.append(
                "era5", "1h", (2025, 1), _named(_make_pyramid([4], 0, 3), name)
            )
        writer.append("era5", "1h", (2025, 2), _named(_make_pyramid([4], 3, 2), "tas"))

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )
        assert opened.sizes["time"] == 5
        assert not opened["tas"].isnull().any()
        assert bool(opened["clt"].isel(time=slice(3, 5)).isnull().all())

    def test_variable_added_later_is_backfilled_with_nan(
        self, writer: HealpixZarrWriter
    ) -> None:
        """A variable added after the fact spans the store's full range.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 1), _named(_make_pyramid([4], 0, 3), "tas"))
        writer.append("era5", "1h", (2025, 2), _named(_make_pyramid([4], 3, 2), "tas"))
        writer.append("era5", "1h", (2025, 2), _named(_make_pyramid([4], 3, 2), "clt"))

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )
        assert opened["clt"].sizes["time"] == 5
        assert bool(opened["clt"].isel(time=slice(0, 3)).isnull().all())
        assert not opened["clt"].isel(time=slice(3, 5)).isnull().any()

    def test_backfilling_a_nan_gap_is_allowed(self, writer: HealpixZarrWriter) -> None:
        """A month a variable skipped can be filled in afterwards.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 1), _named(_make_pyramid([4], 0, 3), "tas"))
        writer.append("era5", "1h", (2025, 2), _named(_make_pyramid([4], 3, 2), "tas"))
        writer.append("era5", "1h", (2025, 2), _named(_make_pyramid([4], 3, 2), "clt"))

        writer.append("era5", "1h", (2025, 1), _named(_make_pyramid([4], 0, 3), "clt"))

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )
        assert not opened["clt"].isnull().any()

    def test_out_of_order_month_raises(self, writer: HealpixZarrWriter) -> None:
        """Timestamps before the store's range need inserting, so they're refused.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append("era5", "1h", (2025, 2), _named(_make_pyramid([4], 3, 2), "tas"))

        with pytest.raises(ValueError, match="chronological order"):
            writer.append(
                "era5", "1h", (2025, 1), _named(_make_pyramid([4], 0, 3), "tas")
            )


# ----------------------------------
# HealpixZarrWriter — vertical dimensions
# ----------------------------------
class TestVerticalDims:
    """Tests for vertical-dimension resolution across differing level sets.

    A store holds one coordinate array per dimension name, so variables
    whose level sets differ (confirmed on real BARRA2 data: "ta" on
    [1000, 950] but "ua" on [1000]) need numbered siblings.
    """

    def test_identical_level_sets_share_coordinate(
        self, writer: HealpixZarrWriter
    ) -> None:
        """Two variables with the same levels share one coordinate.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append(
            "era5", "1h", (2025, 1), _make_level_pyramid(0, 3, [1000.0, 950.0])
        )
        writer.append(
            "era5",
            "1h",
            (2025, 1),
            _make_level_pyramid(0, 3, [1000.0, 950.0], name="U"),
        )

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )
        assert opened["T"].dims == ("time", "level", "cell")
        assert opened["U"].dims == ("time", "level", "cell")
        assert "level_1" not in opened.sizes

    def test_differing_level_sets_get_numbered_siblings(
        self, writer: HealpixZarrWriter
    ) -> None:
        """New level sets get the next free sibling; a matching sibling is reused.

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        for name, levels in [
            ("T", [1000.0, 950.0]),  # first -> "level"
            ("U", [1000.0]),  # differs -> "level_1"
            ("V", [1000.0]),  # matches U -> reuses "level_1"
            ("W", [900.0]),  # differs again -> "level_2"
        ]:
            writer.append(
                "era5", "1h", (2025, 1), _make_level_pyramid(0, 3, levels, name=name)
            )

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )
        dims = {v: opened[v].dims[1] for v in ("T", "U", "V", "W")}
        assert dims == {"T": "level", "U": "level_1", "V": "level_1", "W": "level_2"}
        assert list(opened["level"].values) == [1000.0, 950.0]
        assert list(opened["level_1"].values) == [1000.0]
        assert list(opened["level_2"].values) == [900.0]
        assert "level_3" not in opened.sizes

    def test_height_resolved_independently_of_level(
        self, writer: HealpixZarrWriter
    ) -> None:
        """A "height" dim gets its own numbering, unaffected by "level".

        Args:
            writer (HealpixZarrWriter): Writer under test.
        """
        writer.append(
            "era5",
            "1h",
            (2025, 1),
            _make_level_pyramid(0, 3, [50.0, 100.0], dim="height"),
        )
        writer.append(
            "era5",
            "1h",
            (2025, 1),
            _make_level_pyramid(0, 3, [100.0], name="U", dim="height"),
        )

        opened = xr.open_zarr(
            Path(writer.base_dir, "era5", "1h", "level_4.zarr"), consolidated=False
        )
        assert opened["T"].dims == ("time", "height", "cell")
        assert opened["U"].dims == ("time", "height_1", "cell")
        assert "level" not in opened.sizes


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
