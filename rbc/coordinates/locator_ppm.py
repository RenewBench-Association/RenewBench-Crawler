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
        self._entsoe_id_index = self._build_entsoe_id_index()
        logger.info("PPMLocator initialized")

    def _build_entsoe_id_index(self) -> dict[str, int]:
        """Pre-compute an ENTSO-E EIC code -> row-position index, once.

        ``match_by_entsoe_id`` used to call ``self.df_europe.explode(...)`` — an
        O(n) operation over the whole (pan-European) PPM dataframe — on *every*
        lookup. Building this index once at load time turns each lookup into an
        O(1) dict access instead, without changing which row is matched (first
        occurrence in row order is kept, same as before).
        """
        index: dict[str, int] = {}
        for pos, id_list in enumerate(self.df_europe["entsoe_id_list"]):
            for eic in id_list:
                index.setdefault(eic, pos)
        return index

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

    # Columns included in the full-row dicts returned by match_by_entsoe_id.
    # Must match the actual PPM CSV column names.
    _PPM_COLS: tuple[str, ...] = (
        "id",
        "Name",
        "Fueltype",
        "Technology",
        "Set",
        "Country",
        "Capacity",
        "Efficiency",
        "DateIn",
        "DateRetrofit",
        "DateOut",
        "lat",
        "lon",
        "Duration",
        "Volume_Mm3",
        "DamHeight_m",
        "StorageCapacity_MWh",
        "EIC",
        "projectID",
    )

    def match_by_entsoe_id(self, entsoe_id: str | None) -> dict | None:
        """Find a power plant by its ENTSOE EIC code and return the full row as a dict.

        Searches the pre-computed ``entsoe_id_list`` column (one EIC code per row after
        exploding the ``projectID`` dict-string) for an exact match via a pre-built
        EIC -> row-position index (see :meth:`_build_entsoe_id_index`).

        Args:
            entsoe_id (str | None): ENTSOE EIC code to search for (e.g.
                ``"11XNUON--------Q"``).

        Returns:
            dict with keys from :attr:`_PPM_COLS`, or ``None`` if the code is not
            found or the matched row has no coordinates.
        """
        if not entsoe_id or pd.isna(entsoe_id):
            return None

        target = str(entsoe_id).strip()
        pos = self._entsoe_id_index.get(target)
        if pos is None:
            return None

        row = self.df_europe.iloc[pos]
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None  # match found but no coordinates — not useful

        return {col: (row[col] if col in row.index else None) for col in self._PPM_COLS}
