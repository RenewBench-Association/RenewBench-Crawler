"""GRIB.

Helpers shared by the GRIB-backed sources (ERA5, ICON-DREAM): reading a
file's own precision step, for snapping regridded values back onto the
source's lattice (see `GridRegridder.quantization_step()`), and flattening
cfgrib's forecast hypercubes.
"""

from pathlib import Path

import eccodes  # type: ignore[import-untyped]
import xarray as xr


def flatten_forecast_dims(ds: xr.Dataset) -> xr.Dataset:
    """Flatten a (time, step) forecast hypercube onto its valid times.

    Args:
        ds (xr.Dataset): One cfgrib hypercube.

    Returns:
        xr.Dataset: The same data on a flat "time" dim, unchanged if the
            hypercube has no "step" dim.
    """
    if "step" not in ds.dims:
        return ds
    return (
        ds.stack(_flat=("time", "step"))
        .swap_dims({"_flat": "valid_time"})
        .drop_vars(["time", "step", "_flat"])
        .rename({"valid_time": "time"})
    )


def grib_quantization_step(path: Path, cf_var_name: str | None = None) -> float | None:
    """Return the finest precision step across a GRIB file's messages.

    GRIB packs each message (timestep/level) independently with its own
    scale: one real ICON-DREAM file carries binary scales of 2**-11, 2**-10
    and 2**-9. Taking the finest keeps whatever precision any single message
    had. Only message headers are read (7,440 of a 6.3 GB file in ~2 s).

    Args:
        path (Path): GRIB file.
        cf_var_name (str | None): Only consider messages whose cfgrib
            `cfVarName` matches, for files sharing several variables as
            ERA5's do. None considers all.

    Returns:
        float | None: `2**binaryScaleFactor * 10**-decimalScaleFactor` of
            the finest message, or None if no packed message matches.
    """
    finest: float | None = None
    with open(path, "rb") as f:
        while (h := eccodes.codes_grib_new_from_file(f, headers_only=True)) is not None:
            try:
                if cf_var_name and eccodes.codes_get(h, "cfVarName") != cf_var_name:
                    continue
                # bitsPerValue 0 marks a constant field: no scale to speak of.
                if eccodes.codes_get(h, "bitsPerValue") == 0:
                    continue
                step = 2.0 ** eccodes.codes_get(h, "binaryScaleFactor") * 10.0 ** (
                    -eccodes.codes_get(h, "decimalScaleFactor")
                )
                finest = step if finest is None else min(finest, step)
            finally:
                eccodes.codes_release(h)
    return finest
