"""MAPPINGS.

Canonical vertical-coordinate registry and HEALPix level helpers shared across
all regridding sources. Per-source data-variable name mappings live with each
source's own regridder module, added as each is implemented (Phase 2/3).
"""

import math
from typing import Literal, TypedDict

VerticalCoordinateType = Literal["pressure_level", "height_level", "model_level"]

# Only meaningful for "model_level" entries -- physically different
# formulations despite sharing the same coordinate type (ICON: sigma-height,
# ERA5: sigma-pressure).
ModelLevelFormulation = Literal["sigma_pressure", "sigma_height"]


class VerticalCoordinateInfo(TypedDict):
    """Describes one canonical variable's vertical axis.

    Attributes:
        coordinate_type: "pressure_level", "height_level", or "model_level".
        unit: "hPa", "m", or None for model levels (ordinal, no physical unit).
        formulation: Only set for "model_level" entries.
    """

    coordinate_type: VerticalCoordinateType
    unit: str | None
    formulation: ModelLevelFormulation | None


# Populated per canonical variable as each regridder is implemented
# (Phase 2/3) -- keyed by canonical variable name.
VERTICAL_COORDINATES: dict[str, VerticalCoordinateInfo] = {}

# Mean radius used to convert a HEALPix pixel's angular size to kilometers.
EARTH_RADIUS_KM = 6371.0


def resolution_to_healpix_level(resolution_km: float) -> int:
    """Approximate the HEALPix level matching a native spatial resolution.

    Based on the mean HEALPix pixel spacing (pixel area = 4*pi / (12 *
    nside**2)) -- a sanity check against misconfigured max_level, not a
    precise grid-matching calculation.

    Args:
        resolution_km: Native grid resolution in kilometers.

    Returns:
        Nearest HEALPix level.

    Raises:
        ValueError: If resolution_km is not positive.
    """
    if resolution_km <= 0:
        raise ValueError(f"resolution_km must be positive, got {resolution_km}.")

    nside = math.sqrt(math.pi / 3) * EARTH_RADIUS_KM / resolution_km
    return round(math.log2(nside))
