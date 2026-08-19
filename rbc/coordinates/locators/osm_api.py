"""Coordinate finding for EGEs using the OSM Overpass Turbo API directly.

Source: API (https://overpass-turbo.eu/)
Data foundation: OpenStreetMap (https://www.openstreetmap.org)
"""

import json
import re
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

from rbc.coordinates.mappings import COUNTRY_OSM_RELATION_ID_MAP

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",  # sometimes given 406 Client Error
    "https://lz4.overpass-api.de/api/interpreter",  # sometimes given 406 Client Error
]
OVERPASS_SERVER_TIMEOUT = 300
OVERPASS_CLIENT_TIMEOUT = OVERPASS_SERVER_TIMEOUT + 60
HEADER = {
    "User-Agent": (
        "RenewBench-Crawler/1.0 "
        "(+https://github.com/RenewBench-Association/RenewBench-Crawler)"
    ),
    "Accept": "application/json",
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
    "Status",
    "Capacity",
]


def query_osm_country_plants(
    country_code: str,
    cache_dir: Path | str | None = None,
    force_update: bool = False,
    live: bool = False,
) -> pd.DataFrame:
    """Queries Overpass API for power plants in a specific country.

    Strategy: Search for area by its ISO 3166-1 alpha-2 tag first and retry using the OSM
    relation ID only if alpha-code search returned nothing (this does not raise an error).
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
    country_code = country_code.upper()
    cache_path: Path | None = None
    parquet_path: Path | None = None

    if not live and cache_dir is not None:
        parquet_path = Path(cache_dir, f"overpass_{country_code}_plants.parquet")
        cache_path = Path(cache_dir, f"overpass_{country_code}_plants.json")

        if not force_update:
            if (
                parquet_path.is_file()
            ):  # Fast: local parquet (processed df, loads in ms)
                df_parquet = _load_parquet(parquet_path)
                if df_parquet is not None and len(df_parquet) > 0:
                    return df_parquet

            if cache_path.is_file():  # Fallback: raw JSON cache (re-parse on load)
                cached = _load_cached_overpass(cache_path)
                if isinstance(cached, dict):
                    df_cached = _elements_to_df(cached)
                    if len(df_cached) > 0:
                        logger.info(
                            f"Loaded {len(df_cached)} OSM rows from JSON cache for "
                            f"country '{country_code}'."
                        )
                        return df_cached

    # --- Attempt 1: ISO alpha-2 tag lookup ----------------------------------------
    area_clause = _code_area(iso_alpha_code=country_code)
    data = post_overpass(query=_build_query(area_clause), label=country_code)

    # --- Attempt 2: osm country relation ID fallback ------------------------------
    if data is not None and not data.get("elements"):
        rel_id = COUNTRY_OSM_RELATION_ID_MAP.get(country_code)
        if rel_id is not None:
            logger.warning(
                f"ISO3166-1 lookup returned 0 elements for '{country_code}'; "
                f"retrying via OSM relation {rel_id}."
            )
            area_clause = _id_area(relation_id=rel_id)
            data = post_overpass(query=_build_query(area_clause), label=country_code)
        else:
            logger.error(
                f"ISO3166-1 lookup returned 0 elements for '{country_code}' and "
                "no relation ID is registered. Add one to COUNTRY_OSM_RELATION_ID_MAP!"
            )

    if data is not None:
        df = _elements_to_df(data)

        if len(df) > 0 and not live:
            if parquet_path is not None:
                _save_parquet(parquet_path, df)
            if cache_path is not None:
                _save_cached_overpass(cache_path, data)

        logger.info(f"Built {len(df)} OSM rows for '{country_code}'.")
        return df

    # --- Stale cache as last resort -------------------------------------------
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
# Post query
# ---------------------------------------------------------------------------
def post_overpass(query: str, label: str) -> dict | None:
    """Post a query to the OSM Overpass Turbo API endpoints in order, return on first success.

    Args:
        query (str): Overpass QL query.
        label (str): Label for identification used in log messages (e.g. the country code).

    Returns:
        dict | None: Parsed Overpass response, or None if every endpoint failed.
    """
    for endpoint in OVERPASS_URLS:
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=HEADER,
                timeout=OVERPASS_CLIENT_TIMEOUT,
            )

            # if query syntax error (400): will fail for all URLs, so quit immediately
            if response.status_code == 400:
                logger.error(
                    f"Overpass rejected the query for '{label}' (HTTP 400). "
                    f"Body: {response.text[:500]}"
                )
                return None

            response.raise_for_status()
            data = response.json()

            n_elements = len(data.get("elements", []))
            logger.info(
                f"Overpass endpoint '{endpoint}' returned {n_elements} elements "
                f"for '{label}'."
            )
            return data

        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Overpass endpoint '{endpoint}' failed for '{label}': {e}")

    return None


# ---------------------------------------------------------------------------
# Build query
# ---------------------------------------------------------------------------
_INACTIVE_STAGES = (
    "abandoned",
    "disused",
    "demolished",
    "razed",
    "removed",
    "ruins",
    "was",
    "construction",
    "proposed",
    "planned",
)


def _build_query(area_clause: str) -> str:
    """Build the Overpass query for EGEs within a given area.

    Args:
        area_clause (str): A complete Overpass statement including `.searchArea`,
            e.g. `area["ISO3166-1"="DE"]->.searchArea;` or `area(3600051477)->.searchArea;`.

    Returns:
        str: Overpass QL query string.
    """
    inactive_queries = """"""
    for k in _INACTIVE_STAGES:
        inactive_queries += f"""  nwr["{k}:power"="plant"](area.searchArea);\n"""

    return f"""
    [out:json][timeout:{OVERPASS_SERVER_TIMEOUT}];
    {area_clause}
    (
      // Active EGEs
      nwr["power" = "plant"](area.searchArea);

      // Historic / decommissioned / planned EGEs
    {inactive_queries}
    );
    out body geom center;
    """


def _code_area(iso_alpha_code: str) -> str:
    """OSM area clause defining a country by its ISO 3166-1 alpha-2 code.

    Args:
        iso_alpha_code (str): ISO 3166-1 alpha-2 code (uppercase).

    Returns:
        str: Overpass statement binding `.searchArea`.
    """
    return (
        f'(area["ISO3166-1"="{iso_alpha_code}"]["admin_level"="2"];'
        f'area["ISO3166-1:alpha2"="{iso_alpha_code}"]["admin_level"="2"];)'
        f"->.searchArea;"
    )


def _id_area(relation_id: int) -> str:
    """OSM area clause defining a boundary (country) directly by OSM relation ID.

    Args:
        relation_id (int): OSM relation ID of the boundary.

    Returns:
        str: Overpass statement binding `.searchArea`.
    """
    return f"area({3600000000 + relation_id})->.searchArea;"


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------
_FUEL_KEY = "source"
_CAPA_KEY = "output:electricity"
_NAME_KEYS = (
    "name",
    "alt_name",
    "old_name",
    "official_name",
    "short_name",
    "int_name",
    "loc_name",
    "reg_name",
    "nat_name",
)
# find language-dep names (i.e. "name", "name:en", "name:zh-Hant", but not "name:etymology")
_LANGUAGE_SUFFIX = re.compile(r"^[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?$")


def _elements_to_df(data: dict) -> pd.DataFrame:
    """Extract relevant elements (EGEs) from OSM data and transform into DataFrame.

    Args:
        data (dict): OSM data received from API call.

    Returns:
        df (pd.DataFrame): DataFrame containing structured OSM data.
    """
    results = []
    for el in data.get("elements", []):
        raw_tags = el.get("tags", {})
        if not raw_tags:
            continue

        status, name_variants, tags = _parse_tag_information(raw_tags)

        if not name_variants:  # only continue if element (EGE) has a name!
            continue

        (lat, lon), geometry = _parse_spatial_data(el)
        osm_id = el.get("id")
        osm_type = str(el.get("type", ""))  # node, way or relation
        osm_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
        fuel = tags.get(
            f"plant:{_FUEL_KEY}", tags.get(f"generator:{_FUEL_KEY}", "unknown")
        )
        capa = tags.get(
            f"plant:{_CAPA_KEY}", tags.get(f"generator:{_CAPA_KEY}", "unknown")
        )

        base_data = {
            "Fueltype": fuel,
            "lat": lat,
            "lon": lon,
            "OSM_ID": osm_id,
            "OSM_Type": osm_type,
            "OSM_URL": osm_url,
            "OSM_Geometry": geometry,
            "Status": status,
            "Capacity": capa,
        }
        for name in name_variants:
            results.append({"Name": name, **base_data})

    df = pd.DataFrame(results)
    if len(df) == 0:
        return pd.DataFrame(columns=OUT_COLUMNS)  # empty df

    return df[OUT_COLUMNS]  # ensure correct ordering


def _parse_tag_information(tags: dict) -> tuple[str, list[str], dict]:
    """Parse raw OSM tags of an EGE extract all relevant information in one go.

    Args:
        tags (dict): Raw OSM tags of one EGE received from API call.

    Returns:
        tuple:
            - status (str): EGE status (e.g. active, decommissioned (=inactive), unknown)
            - name_variants (list): All name variants for an EGE
            - clean_tags (dict): Clean tags (prefixes for inactive EGEs like "was:" stripped)
    """
    status = "unknown"
    name_variants = set()
    clean_tags = {}

    if tags.get("power") in {"plant", "generator"}:
        status = "active"

    for key, value in tags.items():
        prefix, sep, rest = key.partition(":")
        is_inactive = prefix in _INACTIVE_STAGES and sep

        # 1. Clean the key (strip prefixes if it's an inactive EGE)
        clean_key = rest if is_inactive else key

        # 2. Redefine the status if the EGE wasn't strictly "active"
        if (
            status == "unknown"
            and is_inactive
            and clean_key == "power"
            and value in {"plant", "generator"}
        ):
            status = prefix

        # 3. Collect all known name variants
        if _is_name_key(clean_key) and isinstance(value, str) and value.strip():
            name_variants.add(value.strip())

        # 4. Populate clean_tags (active keys win e.g.: "power:source" > "was:power:source")
        if not is_inactive or clean_key not in clean_tags:
            clean_tags[clean_key] = value

    return status, sorted(name_variants), clean_tags


def _is_name_key(key: str) -> bool:
    """Check whether a tag key holds a name / name variant (e.g. "old_name", "name:hv-Hall).

    Args:
        key (str): Tag key.

    Returns:
        bool: True if the key is a name or a language-suffixed name variant.
    """
    if key in _NAME_KEYS:
        return True

    name, sep, suffix = key.partition(":")
    return name in _NAME_KEYS and bool(sep) and bool(_LANGUAGE_SUFFIX.match(suffix))


def _parse_spatial_data(
    el: dict,
) -> tuple[tuple[float | None, float | None], dict | None]:
    """Extract centroid and GeoJSON geometry from an OSM element in one go.

    Args:
        el (dict): The OSM data element.

    Returns:
        tuple:
            - tuple(lat (float), lon (float)): Tuple of floats, or (None, None) if not found.
            - geojson (dict): Dictionary representing the GeoJSON geometry, or None.
    """
    osm_type = str(el.get("type", "")).lower()

    # 1. Handle "ways" / "relations" data elements → list of points in 'geometry'
    geometry = el.get("geometry")
    if isinstance(geometry, list) and geometry:
        coords = []
        lat_sum, lon_sum = 0.0, 0.0

        for p in geometry:
            if isinstance(p, dict):
                lat, lon = p.get("lat"), p.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    coords.append([float(lon), float(lat)])
                    lat_sum += float(lat)
                    lon_sum += float(lon)

        if coords:
            num_points = len(coords)
            centroid = (lat_sum / num_points, lon_sum / num_points)

            if osm_type in {"way", "relation"} and num_points >= 3:
                if coords[0] != coords[-1]:  # if polygon is open, close it
                    coords.append(coords[0])
                return centroid, {"type": "Polygon", "coordinates": [coords]}

            return centroid, {"type": "LineString", "coordinates": coords}

    # 2. Handle "nodes" / "out center" API queries → single point in 'center' or 'lat'/'lon'
    center = el.get("center", {}) if isinstance(el.get("center"), dict) else {}
    lat = center.get("lat", el.get("lat"))
    lon = center.get("lon", el.get("lon"))

    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        lat, lon = float(lat), float(lon)
        return (lat, lon), {"type": "Point", "coordinates": [lon, lat]}

    # 3. Handle missing spatial data
    return (None, None), None


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
