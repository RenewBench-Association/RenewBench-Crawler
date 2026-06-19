"""Coordinate finding for energy entities using the powerplantmatching package.

Source: OSM data, ???
"""

import ast

import pandas as pd
from loguru import logger

# import powerplantmatching as ppm

PPM_CSV_URL = "https://raw.githubusercontent.com/PyPSA/powerplantmatching/refs/heads/master/powerplants.csv"


class PPMLocator:
    """Coordinate locator using powerplantsmatching package."""

    def __init__(self):
        """Initializes PPMLocator."""
        # All power plants in Europe that "make the cut" according to ppm
        self.df_europe = pd.read_csv(PPM_CSV_URL)
        self.df_europe["entsoe_id_list"] = self.df_europe["projectID"].apply(
            self._extract_entsoe_code_list
        )
        logger.info("PPMLocator initialized")

    def get_pp_df_from_static_csv(self, country: str) -> pd.DataFrame:
        """Gets power plant df of all energy entities in a given country from static csv.

        The static CSV is updated on a regular basis (ca. monthly). Combination of all
        kinds of different sources for Europe, including but not limited to the
        osm-powerplant package.

        Args:
            country (str): Country name.

        Returns:
            pd.DataFrame: DataFrame containing all OSM energy entities in the country.
                Had the columns:
                ['id', 'Name', 'Fueltype', 'Technology', 'Set', 'Country', 'Capacity',
                 'Efficiency', 'DateIn', 'DateRetrofit', 'DateOut', 'lat', 'lon',
                 'Duration', 'Volume_Mm3', 'DamHeight_m', 'StorageCapacity_MWh', 'EIC',
                 'projectID', 'entsoe_id']
        """
        return self.df_europe[(self.df_europe["Country"] == country)]

    def _extract_entsoe_code_list(self, project_id_str: str) -> list:
        """Extracts the 'ENTSOE' key-value pairs from the 'projectID' column string.

        The 'projectID' column contains dict-like objects stored as strings with
        all manner of IDs, including ENTSO-e IDs (for some). These are extracted to create a
        separate df column for pp matching. As there are sometimes more than one entsoe ID
        associated with a pp, they are returned as lists

        Args:
            project_id_str (str): Project ID string from the ppm df. For example:
                "{'MASTR': {'MASTR-SEE915985628661'}, 'GEM': {'G100000601739'},
                  'JRC': {'JRC-H208'}, 'EESI': {'EESI-64743'}, 'ENTSOE': {'11WD2ERZH0002682'},
                  'GHR': {'GHR-GHR03186'}, 'OPSD': {'BNA0558'}, 'GEO': {'GEO-44352'}}"

        Returns:
            list: List of entsoe ID(s) or an empty list, if no entsoe ID(s) is/are available.
        """
        if not isinstance(project_id_str, str):
            return []

        try:
            data_dict = ast.literal_eval(project_id_str)  # convert to actual dict
            entsoe_set = data_dict.get("ENTSOE", None)

            if entsoe_set:
                return [
                    str(item).strip() for item in entsoe_set
                ]  # get value(s) from key!

        except (ValueError, SyntaxError):  # handle any malformed strings
            return []

        return []
