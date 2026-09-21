# tests/weather/regridding/test_grib.py
"""Tests for rbc.weather.regridding.grib."""

from pathlib import Path

import eccodes
import numpy as np
import pandas as pd
import xarray as xr

from rbc.weather.regridding.grib import flatten_forecast_dims, grib_quantization_step


class TestFlattenForecastDims:
    """Tests for flatten_forecast_dims()."""

    def test_step_hypercube_collapses_onto_valid_times(self) -> None:
        """A (time, step) cube becomes one flat time dim of its valid times."""
        init = pd.to_datetime(["2020-04-01T00:00"]).values
        step = pd.to_timedelta([1, 2], unit="h").values
        ds = xr.Dataset(
            {"tp": (("time", "step"), [[0.1, 0.2]])},
            coords={
                "time": init,
                "step": step,
                "valid_time": (("time", "step"), init[:, None] + step[None, :]),
            },
        )

        flat = flatten_forecast_dims(ds)

        assert flat["tp"].dims == ("time",)
        assert list(flat["time"].values) == list(
            pd.to_datetime(["2020-04-01T01:00", "2020-04-01T02:00"])
        )

    def test_flat_hypercube_passes_through(self) -> None:
        """A cube without a "step" dim is returned unchanged."""
        ds = xr.Dataset({"t2m": ("time", [1.0, 2.0])}, coords={"time": [0, 1]})

        assert flatten_forecast_dims(ds) is ds


def _write_grib(path: Path, messages: list[tuple[str, float]]) -> list[int]:
    """Write real GRIB2 messages whose value range drives the packing scale.

    eccodes picks each message's binaryScaleFactor from its value range at a
    fixed bitsPerValue, so a wider range yields a coarser step -- the same
    per-message variation seen in real ICON-DREAM files.

    Args:
        path (Path): Output file.
        messages (list[tuple[str, float]]): (shortName, value range) per
            message; a range of 0 writes a constant field.

    Returns:
        list[int]: binaryScaleFactor eccodes chose for each message.
    """
    scales = []
    with open(path, "wb") as out:
        for short_name, value_range in messages:
            h = eccodes.codes_grib_new_from_samples("GRIB2")
            eccodes.codes_set(h, "shortName", short_name)
            eccodes.codes_set(h, "bitsPerValue", 16)
            n = eccodes.codes_get(h, "numberOfValues")
            eccodes.codes_set_values(h, 250 + value_range * np.linspace(0, 1, n))
            scales.append(eccodes.codes_get(h, "binaryScaleFactor"))
            eccodes.codes_write(h, out)
            eccodes.codes_release(h)
    return scales


class TestGribQuantizationStep:
    """Tests for grib_quantization_step()."""

    def test_takes_the_finest_step_across_messages(self, tmp_path: Path) -> None:
        """Messages packed at different scales yield the finest step.

        Real ICON-DREAM files mix binary scales within one file; taking the
        first message's would be too coarse for the rest.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        path = Path(tmp_path, "t.grb")
        scales = _write_grib(path, [("2t", 100.0), ("2t", 1.0), ("2t", 10.0)])
        assert len(set(scales)) > 1  # the fixture really does vary

        assert grib_quantization_step(path) == 2.0 ** min(scales)

    def test_filters_by_variable_in_shared_files(self, tmp_path: Path) -> None:
        """Only the requested variable's messages count, as in ERA5's shared files.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        path = Path(tmp_path, "sl.grib")
        scales = _write_grib(path, [("2t", 100.0), ("msl", 1.0)])

        assert grib_quantization_step(path, "t2m") == 2.0 ** scales[0]
        assert grib_quantization_step(path, "msl") == 2.0 ** scales[1]

    def test_no_matching_variable_returns_none(self, tmp_path: Path) -> None:
        """A filter matching no message yields None rather than a guess.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        path = Path(tmp_path, "sl.grib")
        _write_grib(path, [("2t", 100.0)])

        assert grib_quantization_step(path, "tp") is None

    def test_constant_fields_are_skipped(self, tmp_path: Path) -> None:
        """An all-constant variable (bitsPerValue 0) yields None, not its scale.

        A constant field's value lives at full precision in GRIB's reference
        value, and its binaryScaleFactor (0 here, i.e. a step of 1.0) is
        meaningless -- snapping to it would round 250.0 fine but 273.15 K to
        273 K.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        path = Path(tmp_path, "t.grb")
        _write_grib(path, [("2t", 0.0), ("2t", 0.0)])

        assert grib_quantization_step(path) is None
