"""Coordinate finding for energy entities using the osm-powerplants package.

Source: OSM data
"""

from pathlib import Path

import pandas as pd
from loguru import logger
from osm_powerplants import get_cache_dir, get_config, process_units

OSM_CONFIG = get_config()
OSM_CACHE_DIR = str(get_cache_dir(OSM_CONFIG))

OSMPP_URL = (
    "https://raw.githubusercontent.com/open-energy-transition/osm-powerplants/main/"
)
OSMPP_CSV_URL = OSMPP_URL + "osm_global.csv.gz"
OSMPP_REJECTED_CSV_URL = OSMPP_URL + "osm_global_rejected_plants.csv.gz"


class OSMPPLocator:
    """Coordinate locator using osm-powerplants package."""

    def __init__(self, output_dir: Path | None = None):
        """Initializes OSMPPLocator.

        Args:
            output_dir (Path, optional): Output dir for storing results from API querying.
                Defaults to None.
        """
        self.output_dir = output_dir
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

        # All energy entities in Europe that "make the cut" according to osm-pp
        self.df_global = pd.read_csv(OSMPP_CSV_URL)
        # Energy entities that are filtered out by osm-pp due to missing data
        self.df_global_rejected = pd.read_csv(OSMPP_REJECTED_CSV_URL)
        logger.info("OSMPPLocator initialized")

    def get_pp_df_from_static_csv(self, country: str) -> pd.DataFrame:
        """Gets power plant df of all OSM energy entities in a given country from static csv.

        The static CSV is updated on a regular basis (ca. monthly). Does not contain
        decommissioned plants, but earliest publish is 2025 so not a lot of historical
        versions that could be used instead of the current one.

        Args:
            country (str): Country name (i.e. "France")

        Returns:
            pd.DataFrame: DataFrame containing all OSM energy entities in the country.
                Has the columns:
                ['projectID', 'Country', 'lat', 'lon', 'type', 'Fueltype', 'Technology',
                 'Capacity', 'Name', 'Set', 'capacity_source', 'DateIn', 'id',
                 'created_at', 'config_hash', 'config_version', 'processing_parameters',
                 'generator_count']
        """
        return self.df_global[self.df_global["Country"] == country]

    def request_pp_df(self, country: str) -> pd.DataFrame | None:
        """Requests (and saves) power plant df of all OSM energy entities in a given country.

        Nice idea but the request for country data works once and then hangs itself up at the
        next request (esp. larger countries!). The alternative is using the global csv they
        automatically refresh (start: 2025). However, their parsing of OSM looks for
        "plant=power" which doesn't apply to decommissioned / outdated plants.

        Args:
            country (str): Country name or iso code.

        Returns:
            pd.DataFrame | None: DataFrame of all OSM energy entities in the country or
                None, if an error occurred during parsing (which happens a lot!).
        """
        if self.output_dir is None:
            logger.warning(
                "No output_dir was provided when the class instance was initialized! CSVs "
                "will not be saved, only data returned via the df."
            )

        try:
            df = process_units(
                countries=[country],
                config=OSM_CONFIG,
                cache_dir=OSM_CACHE_DIR,
                output_path=Path(self.output_dir, "entities.csv")
                if self.output_dir
                else None,
                rejected_output_path=Path(self.output_dir, "rejected_entities.csv")
                if self.output_dir
                else None,
            )

        except ValueError as e:
            logger.error(f"Invalid country string '{country}' provided: {e}")
            return None

        except OSError as e:
            logger.error(f"Could not save OSM coordinate file(s) to output path: {e}")
            return None

        if df.empty:
            logger.error(f"No OSM energy entitites found in country '{country}'")
            return None

        return df
