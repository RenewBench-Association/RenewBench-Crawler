"""Coordinate finding for EGEs using the osm-powerplants package.

Source: GitHub package (https://github.com/open-energy-transition/osm-powerplants)
Data foundation: OSM data
"""

import pandas as pd
from loguru import logger

from rbc.coordinates.utils.country import normalize_locator_countries
from rbc.energy.utils import load_df_from_file

OSMPP_URL = (
    "https://raw.githubusercontent.com/open-energy-transition/osm-powerplants/main/"
)
OSMPP_CSV_URL = OSMPP_URL + "osm_global.csv.gz"
OSMPP_REJECTED_CSV_URL = OSMPP_URL + "osm_global_rejected_plants.csv.gz"


class OSMPPLocator:
    """Coordinate locator using osm-powerplants package.

    Attributes:
        df (pd.DataFrame): Dataframe of normalized OSMPP data from GitHub's global CSV.
            Has the columns:
            [
                'projectID', 'Country', 'lat', 'lon', 'type', 'Fueltype', 'Technology',
                'Capacity', 'Name', 'Set', 'capacity_source', 'DateIn', 'id', 'created_at',
                'config_hash', 'config_version', 'processing_parameters', 'generator_count'
            ]
    """

    def __init__(self) -> None:
        """Initializes OSMPPLocator."""
        # All energy entities in the world that "make the cut" according to osm-pp.
        self.df: pd.DataFrame = load_df_from_file(OSMPP_CSV_URL)
        self.df = normalize_locator_countries(self.df)  # normalize the country values

        # # Energy entities that are filtered out by osm-pp due to missing data
        # self.df_rejected: pd.DataFrame = load_df_from_file(OSMPP_REJECTED_CSV_URL)
        # self.df_rejected = normalize_locator_countries(self.df_rejected)
        logger.info(f"OSMPPLocator initialized: {len(self.df)} entries")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_country_df(self, country: str) -> pd.DataFrame:
        """Gets a df of all EGEs in a given country, sliced from the CSV-based OSMPP df.

        The static CSV is updated on a regular basis (ca. monthly). Does not contain
        decommissioned plants, but earliest publish is 2025 so not a lot of historical
        versions that could be used instead of the current one anyway.

        Args:
            country (str): Country name (i.e. "France")

        Returns:
            pd.DataFrame: DataFrame containing all OSM energy entities in the country.
        """
        return self.df[self.df["Country"] == country]
