import pandas as pd
import requests
from loguru import logger

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADER = {
    "User-Agent": "RenewBench Association +("
    "+https://github.com/RenewBench-Association/RenewBench-Crawler)"
}


def query_osm_country_plants(country_code: str = "FR") -> pd.DataFrame:
    """Queries Overpass API for power plants in a specific country.

    This takes long and is a work in progres... Which query is the most suitable one?
    Could also search for name - but often comes up empty...

    Args:
        country_code (str, optional): Country ISO code.

    Returns:
        pd.DataFrame: DataFrame of power plants in given country.
    """
    # overpass query to search for nodes, ways, relations that
    overpass_query = f"""
    [out:json];
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
    out center;
    """

    try:
        response = requests.post(
            OVERPASS_URL, data={"data": overpass_query}, headers=HEADER
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as e:
        logger.error(
            f"Overpass API error: {response.status_code} - {response.reason}: {e}"
        )
        return None

    results = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})

        if "name" not in tags:  # only get elements with a name!
            continue

        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")

        results.append(
            {
                "OSM_ID": el["id"],
                "Name": tags.get("name"),
                "Plant_Source": tags.get(
                    "plant:source", tags.get("generator:source", "Unknown")
                ),
                "Capacity_MW": tags.get(
                    "plant:output:electricity",
                    tags.get("generator:output:electricity", "Unknown"),
                ),
                "Latitude": lat,
                "Longitude": lon,
                "Tags_Dump": str(tags),  # Keep all tags for debugging edge cases
            }
        )

    df = pd.DataFrame(results)
    return df
