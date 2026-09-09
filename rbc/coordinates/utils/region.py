"""Region utilities.

Utility functions for verifying that a matched coordinate lies inside the region the
operator declares for its EGE (e.g. ONS' `nom_estado`). Used as a veto in name matching
(see ``matcher._compare_region``) and as a final check on all matched EGEs.
"""

from functools import lru_cache

import geopandas as gpd
from loguru import logger
from shapely.geometry import Point
from shapely.prepared import PreparedGeometry, prep

from rbc.coordinates.utils.values import normalize_name, strip_str

# Natural Earth admin-1 (states/provinces): public domain, ~4600 units worldwide.
NE_ADMIN1_URL = (
    "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip"
)
# Tolerance for boundary imprecision
BUFFER_KM = 15.0


def classify_region_match(
    country: str, target_region: str | None, cand_coord: tuple[float, float]
) -> str:
    """Whether the candidate coordinate (lat, lon) lies within the target region.

    Args:
        country (str): The target's country.
        target_region (str | None): The target's region.
        cand_coord (tuple[float, float]): The candidate coordinate (lat, lon).

    Returns:
        str: Position of the candidate coordinate relative to the target region.
            ``"unknown"``        — no region given, or its name has no known polygon.
            ``"within_borders"`` — inside the region.
            ``"within_bounds"``  — outside, but within BUFFER_KM of it.
            ``"mismatch"``       — clearly elsewhere.
    """
    region = normalize_name(target_region)
    if not region:
        return "unknown"  # no info

    polys = _region_index(country).get(region)
    if polys is None:
        return "unknown"  # unresolvable name must never veto

    point = Point(cand_coord[1], cand_coord[0])  # shapely is (x=lon, y=lat)
    exact, buffered = polys
    if exact.contains(point):
        return "within_borders"
    if buffered.contains(point):
        return "within_bounds"

    return "mismatch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8)
def _region_index(country: str) -> dict[str, tuple[PreparedGeometry, PreparedGeometry]]:
    """Map normalized region names of a country to their (exact, buffered) polygons.

    Download and prep for fast repeated point-in-polygon checks. A strict and buffered polygon
    are kept, so ``classify_region_match`` can tell "inside" from "just over the border".

    Args:
        country (str): The country to map to.

    Returns:
        dict[str, tuple[PreparedGeometry, PreparedGeometry]]: A dictionary mapping the
            region name to its geometry (exact, buffered).
    """
    gdf = gpd.read_file(NE_ADMIN1_URL)

    # 1. filter to the country ("Amazonas" exists in BR, CO, PE and VE)
    gdf = gdf[gdf["admin"].map(normalize_name) == normalize_name(country)]
    if gdf.empty:
        logger.warning(
            f"No admin-1 regions found for '{country}'. Region check disabled."
        )
        return {}

    # 2. buffer in a metric CRS (tolerance in km, not °); then back to lat/lon for the checks
    centroid = gdf.geometry.union_all().centroid
    metric_crs = (
        f"+proj=ortho +lat_0={centroid.y} +lon_0={centroid.x} "
        f"+datum=WGS84 +units=m +no_defs"
    )
    gdf["buffered"] = gdf.to_crs(metric_crs).buffer(BUFFER_KM * 1000).to_crs(gdf.crs)

    index: dict[str, tuple[PreparedGeometry, PreparedGeometry]] = {}
    for _, row in gdf.iterrows():
        polys = (prep(row["geometry"]), prep(row["buffered"]))

        for col in ("name", "name_en", "name_alt"):  # "name_alt" vals are "|"-separated
            for alt in (strip_str(row.get(col)) or "").split("|"):
                if name := normalize_name(alt):
                    index.setdefault(name, polys)
    return index
