"""Region checking.

Verifies that a matched coordinate lies inside the region the operator declares for its
EGE (e.g. ONS' `nom_estado`), backed by Natural Earth's admin-1 (states/provinces) data.
Used as a veto in name matching (see ``matcher._compare_region``) and as a final check
on all matched EGEs (see ``BasePipeline._step_validate_region``).
"""

from pathlib import Path

import geopandas as gpd
from loguru import logger
from shapely.geometry import Point
from shapely.prepared import PreparedGeometry, prep

from rbc.coordinates.utils.resources import fetch_resource
from rbc.coordinates.utils.values import normalize_name, strip_str

# Natural Earth admin-1 (states/provinces): public domain, ~4600 regions worldwide.
NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/"
NE_ADMIN1_FILE = "ne_10m_admin_1_states_provinces.zip"
NE_ADMIN1_ZIP_URL = NE_URL + NE_ADMIN1_FILE
# Tolerance for boundary imprecision (e.g. offshore wind, hydro plants on border rivers)
BUFFER_KM = 20.0


class RegionRegistry:
    """Admin-1 region lookup, telling whether a coordinate lies in a named region.

    Built once per run and shared across a run's directories (see
    `build_shared_resources`), so the Natural Earth data is read once and every
    country's prepared polygons are reused. Nothing is read or downloaded until the
    first check that actually names a region, which most operators never do.

    Attributes:
        cache_dir (Path | None): Directory of the local admin-1 zip. If None, the
            data is read straight from `NE_ADMIN1_ZIP_URL`.
        update (bool): Whether to download a fresh copy of the admin-1 zip.
    """

    def __init__(self, cache_dir: Path | None = None, update: bool = False) -> None:
        """Initialize RegionRegistry (no data is read until the first region check).

        Args:
            cache_dir (Path | None, optional): Directory of the local admin-1 zip.
                Defaults to None, in which case the data is read from its URL.
            update (bool, optional): Download a fresh copy of the admin-1 zip, even
                if one exists locally. Defaults to False.
        """
        self.cache_dir = cache_dir
        self.update = update

        self.df_admin1: gpd.GeoDataFrame | None = None  # the whole admin-1 dataset
        self.cache_country_index: dict[
            str, dict[str, tuple[PreparedGeometry, PreparedGeometry]]
        ] = {}  # cache for prepared polygons per country, built on first use

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def classify_match(
        self, country: str, target_region: str | None, cand_coord: tuple[float, float]
    ) -> str:
        """Whether the candidate coordinate (lat, lon) lies within the target region.

        Args:
            country (str): The target's country.
            target_region (str | None): The target's region.
            cand_coord (tuple[float, float]): The candidate coordinate (lat, lon).

        Returns:
            str: Position of the candidate coordinate relative to the target region.
                ``"unknown"``        — no region given, or its name has no polygon.
                ``"within_borders"`` — inside the region.
                ``"within_bounds"``  — outside, but within BUFFER_KM of it.
                ``"mismatch"``       — clearly elsewhere.
        """
        region = normalize_name(target_region)
        if not region:
            return "unknown"  # no info

        polys = self._get_country_polys(country).get(region)
        if polys is None:
            return "unknown"  # unresolvable name must never veto

        point = Point(cand_coord[1], cand_coord[0])  # shapely is (x=lon, y=lat)
        exact, buffered = polys
        if exact.contains(point):
            return "within_borders"
        if buffered.contains(point):
            return "within_bounds"

        return "mismatch"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_country_polys(
        self, country: str
    ) -> dict[str, tuple[PreparedGeometry, PreparedGeometry]]:
        """Map normalized region names of a country to their (exact, buffered) polygons.

        Calculated once per country for fast point-in-polygon checks. Defines an exact and
        buffered polygon, so `classify_match` can tell "inside" from "just over the border".

        Args:
            country (str): The country to map to.

        Returns:
            dict[str, tuple[PreparedGeometry, PreparedGeometry]]: A dictionary mapping
                the region name to its geometry (exact, buffered).
        """
        if country in self.cache_country_index:
            return self.cache_country_index[country]

        index: dict[str, tuple[PreparedGeometry, PreparedGeometry]] = {}
        self.cache_country_index[country] = index

        # 1. filter to the country ("Amazonas" exists in BR, CO, PE and VE)
        gdf = self._get_admin1_df()
        gdf = gdf[gdf["admin"].map(normalize_name) == normalize_name(country)]
        if gdf.empty:
            logger.warning(
                f"No admin-1 regions found for '{country}'. Region check disabled."
            )
            return index

        # 2. buffer in a metric CRS (tolerance in km, not °); then back to lat/lon
        centroid = gdf.geometry.union_all().centroid
        metric_crs = (
            f"+proj=ortho +lat_0={centroid.y} +lon_0={centroid.x} "
            f"+datum=WGS84 +units=m +no_defs"
        )
        gdf["buffered"] = (
            gdf.to_crs(metric_crs).buffer(BUFFER_KM * 1000).to_crs(gdf.crs)
        )

        for _, row in gdf.iterrows():
            polys = (prep(row["geometry"]), prep(row["buffered"]))

            for col in ("name", "name_en", "name_alt"):  # "name_alt" vals "|"-separated
                for alt in (strip_str(row.get(col)) or "").split("|"):
                    if name := normalize_name(alt):
                        index.setdefault(name, polys)

        return index

    def _get_admin1_df(self) -> gpd.GeoDataFrame:
        """Get the Natural Earth admin-1 dataset, reading it only on the first call.

        Read from the local copy in `cache_dir` (downloaded on first use), or straight
        from the URL if no `cache_dir` was given.

        Returns:
            gpd.GeoDataFrame: The NE admin 1 geodataframe.
        """
        if self.df_admin1 is None:
            source: Path | str = NE_ADMIN1_ZIP_URL
            if self.cache_dir is not None:
                cache_path = Path(self.cache_dir, NE_ADMIN1_FILE)
                local = fetch_resource(NE_ADMIN1_ZIP_URL, cache_path, self.update)
                source = local if local is not None else NE_ADMIN1_ZIP_URL

            self.df_admin1 = gpd.read_file(source)

        return self.df_admin1
