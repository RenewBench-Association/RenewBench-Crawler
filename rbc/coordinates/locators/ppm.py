"""Coordinate finding for EGEs using the powerplantmatching package.

Source: GitHub package (https://github.com/PyPSA/powerplantmatching/)
Data foundation: https://github.com/PyPSA/powerplantmatching/blob/master/powerplantmatching/package_data/config.yaml#L61
(for details s. scripts/coordinates/README.md)
"""

import ast
from functools import cached_property

import pandas as pd
from loguru import logger

from rbc.coordinates.match_schema import PPDB_ADAPTER, MatchCandidate
from rbc.coordinates.utils.country import normalize_locator_countries
from rbc.coordinates.utils.values import strip_str
from rbc.energy.utils import load_df_from_file

PPM_CSV_URL = "https://raw.githubusercontent.com/PyPSA/powerplantmatching/refs/heads/master/powerplants.csv"


class PPMLocator:
    """Coordinate locator using powerplantsmatching package.

    Attributes:
        df (pd.DataFrame): Dataframe of normalized PPM data from the GitHub's CSV.
            Has the columns:
            [
                'id', 'Name', 'Fueltype', 'Technology', 'Set', 'Country', 'Capacity',
                'Efficiency', 'DateIn', 'DateRetrofit', 'DateOut', 'lat', 'lon',
                'Duration', 'Volume_Mm3', 'DamHeight_m', 'StorageCapacity_MWh',
                'EIC', 'projectID'
            ]
    """

    def __init__(self):
        """Initializes PPMLocator."""
        # All energy entities in Europe that "make the cut" according to ppm
        self.df: pd.DataFrame = load_df_from_file(PPM_CSV_URL)
        self.df = normalize_locator_countries(self.df)  # normalize the country values

        logger.info(f"PPMLocator initialized: {len(self.df)} entries")

    # ------------------------------------------------------------------
    # Cached properties (calculated once and re-used)
    # ------------------------------------------------------------------
    @cached_property
    def _entsoe_id_index(self) -> dict[str, int]:
        """Pre-compute an ENTSO-E EIC code lookup (row-position index) once.

        Avoids full df scan which ``match_by_entsoe_id`` would otherwise need on every call.

        Returns:
            dict[str, int]: EIC code lookup dict.
        """
        index: dict[str, int] = {}

        for pos, project_id in enumerate(self.df["projectID"]):
            for eic in self._extract_entsoe_code_list(project_id):
                index.setdefault(eic, pos)

        return index

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_entsoe_code_list(project_id_str: str) -> list[str]:
        """Extracts the 'ENTSOE' key-value pairs from the 'projectID' column string.

        The 'projectID' column contains dict-like objects stored as strings with
        all manner of IDs, including ENTSO-e IDs (for some). These are extracted to create a
        separate df column for pp matching. As sometimes more than one entsoe ID is
        associated with a pp, the matches are returned as lists.

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
                return [str(item).strip() for item in entsoe_set]  # get value(s)!

        except (ValueError, SyntaxError):  # handle any malformed strings
            return []

        return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_country_df(self, country: str) -> pd.DataFrame:
        """Gets a df of all EGEs in a given country, sliced from the CSV-based PPM df.

        The static CSV is updated on a regular basis (ca. monthly). Combination of all
        kinds of different sources for Europe, including but not limited to the OSMPP data.

        Args:
            country (str): Country name.

        Returns:
            pd.DataFrame: DataFrame containing all OSM energy entities of one country.
        """
        return self.df[(self.df["Country"] == country)]

    def match_by_entsoe_id(self, entsoe_id: str | None) -> MatchCandidate | None:
        """Find an EGE by its ENTSOE EIC code and return the row as a MatchCandidate.

        Extracts ENTSO-E codes from PPM's parsed "projectID" column (see
        ``_extract_entsoe_code_list``) via a pre-built EIC -> row-position index
        (see ``_entsoe_id_index``).

        Args:
            entsoe_id (str | None): ENTSOE EIC code to search for (e.g. "11XNUON--------Q").

        Returns:
            MatchCandidate | None: Matched row as a MatchCandidate if one was found,
                has coordinates and a name, else None.
        """
        target = strip_str(entsoe_id)
        if target is None:
            return None

        pos = self._entsoe_id_index.get(target)
        if pos is None:
            return None

        row = self.df.iloc[pos]
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None  # match found but no coordinates — not useful

        return MatchCandidate.from_row(row, adapter=PPDB_ADAPTER)
