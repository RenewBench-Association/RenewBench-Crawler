"""GRIB.

Reads a GRIB file's own precision step, for snapping regridded values back
onto the source's lattice (see `GridRegridder.quantization_step()`).
"""

from pathlib import Path

import eccodes  # type: ignore[import-untyped]


def grib_quantization_step(path: Path, cf_var_name: str | None = None) -> float | None:
    """Return the finest precision step across a GRIB file's messages.

    GRIB packs each message (timestep/level) independently, with its own
    scale -- confirmed on real ICON-DREAM data, where one file carries
    binary scales of 2**-11, 2**-10 and 2**-9. The finest step is taken, so
    snapping to it never loses precision any single message had. Only
    message headers are read (7,440 messages of a 6.3 GB file in ~2 s).

    Args:
        path (Path): GRIB file.
        cf_var_name (str | None): Only consider messages whose `cfVarName`
            matches (cfgrib's variable name) -- needed where several
            variables share one file, as in ERA5. None considers all.

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
