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


def query_osm_country_plants(
    country_code: str,
    cache_dir: Path | str | None = None,
    force_update: bool = False,
    live: bool = False,
) -> pd.DataFrame:
    """Queries Overpass API for power plants in a specific country.

    By default, the result is cached as ``overpass_<CC>_plants.parquet`` inside
    ``cache_dir`` and loaded from there on subsequent calls.

    Args:
        country_code (str): ISO 3166-1 alpha-2 country code.
        cache_dir (Path | str | None, optional): Directory for the local OSM power
            plant files.  When provided a `.parquet` file is written on the first
            successful fetch and read back on all subsequent calls.
        force_update (bool): Ignore any existing local file and re-fetch from
            Overpass, then overwrite it.  Corresponds to `--update`.
        live (bool): Query Overpass directly without reading or writing any local
            file.  Corresponds to `--live`.

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

    country_code = country_code.upper()
    cache_path: Path | None = None
    parquet_path: Path | None = None

    if not live and cache_dir is not None:
        parquet_path = Path(cache_dir, f"overpass_{country_code}_plants.parquet")
        cache_path = Path(cache_dir, f"overpass_{country_code}_plants.json")

        if not force_update:
            # Fast: local parquet (processed DataFrame, loads in milliseconds)
            if parquet_path.is_file():
                df_parquet = _load_parquet(parquet_path)
                if df_parquet is not None and len(df_parquet) > 0:
                    return df_parquet

            # Fallback: raw JSON cache (re-parse on load)
            if cache_path.is_file():
                cached = _load_cached_overpass(cache_path)
                if isinstance(cached, dict):
                    df_cached = _elements_to_df(cached)
                    if len(df_cached) > 0:
                        logger.info(
                            f"Loaded {len(df_cached)} OSM rows from JSON cache for "
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

            if len(df) > 0 and not live:
                if parquet_path is not None:
                    _save_parquet(parquet_path, df)
                if cache_path is not None:
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

    if not live and cache_path is not None and cache_path.exists():
        cached = _load_cached_overpass(cache_path)
        if isinstance(cached, dict):
            df_cached = _elements_to_df(cached)
            if len(df_cached) > 0:
                logger.warning(
                    f"All Overpass endpoints failed for '{country_code}'. "
                    "Using stale cached OSM data."
                )
                return df_cached

    logger.error(
        f"All Overpass endpoints failed for country '{country_code}', "
        "and no usable cache was found."
    )
    return pd.DataFrame(columns=OUT_COLUMNS)  # empty df


# ---------------------------------------------------------------------------
# OSM data extraction helpers
# ---------------------------------------------------------------------------
def _elements_to_df(data: dict) -> pd.DataFrame:
    """Extract relevant elements from OSM data and transform into DataFrame.

    Args:
        data (dict): OSM data received from API call.

    Returns:
        df (pd.DataFrame): DataFrame containing structured OSM data.
    """
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

        # Collect all known name variants (local, English, alternate) so matching can try all
        # -> especially important for countries with different language variants.
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
    if len(df) == 0:
        return pd.DataFrame(columns=OUT_COLUMNS)  # empty df

    return df


def _compute_centroid(el: dict) -> tuple[float | None, float | None]:
    """Compute centroid from available OSM geometry/center/point fields.

    Args:
        el (dict): OSM data element.

    Returns:
        lat, lon (tuple[float | None, float | None]): Latitude and longitude of centroid.
    """
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
    """Convert OSM element geometry to a GeoJSON-like dictionary when possible.

    Args:
        el (dict): OSM data element.

    Returns:
        dict | None: Extracted GeoJSON-like dictionary, if extractable.
    """
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


# ---------------------------------------------------------------------------
# I/O (read/write) helpers
# ---------------------------------------------------------------------------
def _load_parquet(parquet_path: Path) -> pd.DataFrame | None:
    """Load parquet data from a file.

    Args:
        parquet_path (Path): Parquet file path.

    Returns:
        pd.DataFrame | None: Parquet data loaded as a DataFrame, if extractable.
    """
    try:
        df = pd.read_parquet(parquet_path)
        logger.info(
            f"Loaded {len(df)} OSM rows from local parquet for "
            f"'{parquet_path.stem.split('_')[1]}'."
        )
        return df
    except Exception as e:
        logger.warning(f"Could not read parquet '{parquet_path}': {e}")
        return None


def _save_parquet(parquet_path: Path, df: pd.DataFrame) -> None:
    """Save DataFrame data to a parquet file.

    Args:
        parquet_path (Path): Parquet file path to save DataFrame to.
        df (pd.DataFrame): DataFrame data to save.
    """
    try:
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(parquet_path, index=False)
        logger.info(f"OSM plant data saved → {parquet_path} ({len(df)} rows)")
    except Exception as e:
        logger.warning(f"Could not write parquet '{parquet_path}': {e}")


def _load_cached_overpass(cache_path: Path) -> dict | None:
    """Load cached Overpass data from a file.

    Args:
        cache_path (Path): Overpass cache JSON path.

    Returns:
        dict | None: Loaded cached Overpass data loaded as a dict, if extractable.
    """
    try:
        with cache_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read Overpass cache '{cache_path}': {e}")
        return None


def _save_cached_overpass(cache_path: Path, data: dict) -> None:
    """Save cached Overpass data to a JSON file.

    Args:
        cache_path (Path): Overpass cache JSON path to save data to.
        data (dict): Overpass data to be stored.
    """
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        logger.warning(f"Could not write Overpass cache '{cache_path}': {e}")
