import json
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADER = {
    "User-Agent": "RenewBench Association +("
    "+https://github.com/RenewBench-Association/RenewBench-Crawler)"
}

OUT_COLUMNS = [
    "Name",
    "Fueltype",
    "lat",
    "lon",
    "OSM_ID",
    "OSM_Type",
    "OSM_URL",
    "OSM_Geometry",
]


def _compute_centroid(el: dict) -> tuple[float | None, float | None]:
    """Compute centroid from available OSM geometry/center/point fields."""
    geometry = el.get("geometry", None)
    if isinstance(geometry, list) and geometry:
        lat_vals: list[float] = [
            float(p["lat"])
            for p in geometry
            if isinstance(p, dict) and isinstance(p.get("lat"), (int, float))
        ]
        lon_vals: list[float] = [
            float(p["lon"])
            for p in geometry
            if isinstance(p, dict) and isinstance(p.get("lon"), (int, float))
        ]
        if lat_vals and lon_vals:
            return float(sum(lat_vals) / len(lat_vals)), float(
                sum(lon_vals) / len(lon_vals)
            )

    center = el.get("center", None)
    if isinstance(center, dict):
        lat = center.get("lat", None)
        lon = center.get("lon", None)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)

    lat = el.get("lat", None)
    lon = el.get("lon", None)
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lat), float(lon)

    return None, None


def _geometry_to_geojson(el: dict) -> dict | None:
    """Convert OSM element geometry to a GeoJSON-like dictionary when possible."""
    geometry = el.get("geometry", None)
    osm_type = str(el.get("type", "")).lower()

    if not isinstance(geometry, list) or not geometry:
        lat = el.get("lat", None)
        lon = el.get("lon", None)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return {"type": "Point", "coordinates": [float(lon), float(lat)]}
        center = el.get("center", None)
        if isinstance(center, dict):
            c_lat = center.get("lat", None)
            c_lon = center.get("lon", None)
            if isinstance(c_lat, (int, float)) and isinstance(c_lon, (int, float)):
                return {"type": "Point", "coordinates": [float(c_lon), float(c_lat)]}
        return None

    coords = []
    for p in geometry:
        if not isinstance(p, dict):
            continue
        lat = p.get("lat", None)
        lon = p.get("lon", None)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            coords.append([float(lon), float(lat)])

    if not coords:
        return None

    if osm_type in {"way", "relation"} and len(coords) >= 3:
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return {"type": "Polygon", "coordinates": [coords]}

    return {"type": "LineString", "coordinates": coords}


def _empty_osm_df() -> pd.DataFrame:
    return pd.DataFrame(columns=OUT_COLUMNS)


def _cache_file(cache_dir: Path, country_code: str) -> Path:
    return cache_dir / f"overpass_{country_code.upper()}_plants.json"


def _load_cached_overpass(cache_path: Path) -> dict | None:
    try:
        with cache_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read Overpass cache '{cache_path}': {e}")
        return None


def _save_cached_overpass(cache_path: Path, data: dict) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        logger.warning(f"Could not write Overpass cache '{cache_path}': {e}")


def _elements_to_df(data: dict) -> pd.DataFrame:
    results = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})

        if "name" not in tags:  # only get elements with a name!
            continue

        lat, lon = _compute_centroid(el)
        osm_type = str(el.get("type", ""))
        osm_id = el.get("id")
        osm_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
        osm_geometry = _geometry_to_geojson(el)
        fueltype = tags.get("plant:source", tags.get("generator:source", "Unknown"))

        # Collect all known name variants (local, English, alternate) so matching
        # can try each of them — especially important for Balkan countries where
        # ENTSO-E may use a different language variant than the primary OSM name.
        name_variants = list(
            {
                v
                for k, v in tags.items()
                if k
                in (
                    "name",
                    "name:en",
                    "name:bs",
                    "name:hr",
                    "name:sr",
                    "alt_name",
                    "old_name",
                    "official_name",
                    "short_name",
                )
                and isinstance(v, str)
                and v.strip()
            }
        )

        for name in name_variants:
            results.append(
                {
                    "OSM_ID": osm_id,
                    "OSM_Type": osm_type,
                    "OSM_URL": osm_url,
                    "OSM_Geometry": osm_geometry,
                    "Name": name,
                    "Fueltype": fueltype,
                    "lat": lat,
                    "lon": lon,
                }
            )

    df = pd.DataFrame(results)
    if df.empty:
        return _empty_osm_df()
    return df


def query_osm_country_plants(
    country_code: str = "FR",
    cache_dir: Path | str | None = None,
) -> pd.DataFrame:
    """Queries Overpass API for power plants in a specific country.

    This takes long and is a work in progres... Which query is the most suitable one?
    Could also search for name - but often comes up empty...

    Args:
        country_code (str, optional): Country ISO code.
        cache_dir (Path | str | None, optional): Directory to read/write a cached
            Overpass JSON response. When provided, a successful response is saved
            as ``overpass_<COUNTRY>_plants.json`` and reused on subsequent calls.
            All Overpass endpoints are tried in order before falling back to a
            stale cache when all fail.

    Returns:
        pd.DataFrame: DataFrame of power plants in given country.
    """
    # overpass query to search for nodes, ways, relations that
    overpass_query = f"""
    [out:json][timeout:180];
    area["ISO3166-1"="{country_code}"]->.searchArea;
    (
      // Active Infrastructure
      nwr["power"="plant"](area.searchArea);

      // Historic / Decommissioned Plants
      nwr["abandoned:power"="plant"](area.searchArea);
      nwr["demolished:power"="plant"](area.searchArea);
      nwr["was:power"="plant"](area.searchArea);
      nwr["disused:power"="plant"](area.searchArea);
    );
    out body geom center;
    """

    cache_path = None
    if cache_dir is not None:
        cache_path = _cache_file(Path(cache_dir), country_code)
        if cache_path.exists():
            cached = _load_cached_overpass(cache_path)
            if isinstance(cached, dict):
                df_cached = _elements_to_df(cached)
                if not df_cached.empty:
                    logger.info(
                        f"Loaded {len(df_cached)} OSM rows from cache for "
                        f"country '{country_code}'."
                    )
                    return df_cached

    for endpoint in OVERPASS_URLS:
        try:
            response = requests.post(
                endpoint,
                data={"data": overpass_query},
                headers=HEADER,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            df = _elements_to_df(data)
            if cache_path is not None and not df.empty:
                _save_cached_overpass(cache_path, data)
            logger.info(
                f"Overpass endpoint '{endpoint}' returned {len(df)} rows "
                f"for '{country_code}'."
            )
            return df

        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.warning(
                f"Overpass endpoint '{endpoint}' failed for '{country_code}': {e}"
            )

    if cache_path is not None and cache_path.exists():
        cached = _load_cached_overpass(cache_path)
        if isinstance(cached, dict):
            df_cached = _elements_to_df(cached)
            if not df_cached.empty:
                logger.warning(
                    f"All Overpass endpoints failed for '{country_code}'. "
                    "Using stale cached OSM data."
                )
                return df_cached

    logger.error(
        f"All Overpass endpoints failed for country '{country_code}', "
        "and no usable cache was found."
    )
    return _empty_osm_df()
