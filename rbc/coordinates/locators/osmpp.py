"""Coordinate finding for energy entities using the osm-powerplants package.

Source: OSM data
"""

import pandas as pd
from loguru import logger

OSMPP_URL = (
    "https://raw.githubusercontent.com/open-energy-transition/osm-powerplants/main/"
)
OSMPP_CSV_URL = OSMPP_URL + "osm_global.csv.gz"
OSMPP_REJECTED_CSV_URL = OSMPP_URL + "osm_global_rejected_plants.csv.gz"


class OSMPPLocator:
    """Coordinate locator using osm-powerplants package."""

    OSMPP_COLS: tuple[str, ...] = (
        "projectID",
        "Country",
        "lat",
        "lon",
        "type",
        "Fueltype",
        "Technology",
        "Capacity",
        "Name",
        "Set",
        "capacity_source",
        "DateIn",
        "id",
        "created_at",
        "config_hash",
        "config_version",
        "processing_parameters",
        "generator_count",
    )

    def __init__(self) -> None:
        """Initializes OSMPPLocator."""
        # All energy entities in the world that "make the cut" according to osm-pp.
        self.df = pd.read_csv(OSMPP_CSV_URL)
        # Energy entities that are filtered out by osm-pp due to missing data
        self.df_rejected = pd.read_csv(OSMPP_REJECTED_CSV_URL)
        logger.info("OSMPPLocator initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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
        return self.df[self.df["Country"] == country]
