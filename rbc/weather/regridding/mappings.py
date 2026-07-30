"""MAPPINGS.

Canonical vertical-coordinate registry shared across all regridding sources.
Per-source data-variable name mappings live with each source's own regridder
module, added as each is implemented (Phase 2/3).
"""

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
