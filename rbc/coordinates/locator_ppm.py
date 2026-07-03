"""Coordinate finding for energy entities using the powerplantmatching package.

Source: OSM data, ???
"""

import ast

import pandas as pd
from loguru import logger
from rapidfuzz import fuzz, process

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

    # Columns included in the full-row dicts returned by match_by_entsoe_id /
    # fuzzy_match_by_name.  Must match the actual PPM CSV column names.
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
        exploding the ``projectID`` dict-string) for an exact match.

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
        df_exploded = self.df_europe.explode("entsoe_id_list")
        hits = df_exploded[df_exploded["entsoe_id_list"] == target]
        if hits.empty:
            return None

        row = hits.iloc[0]
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None  # match found but no coordinates — not useful

        return {col: (row[col] if col in row.index else None) for col in self._PPM_COLS}

    def fuzzy_match_by_name(
        self,
        name: str | None,
        threshold: int = 85,
    ) -> dict | None:
        """Fuzzy-match a plant name against the powerplantmatching database.

        Uses ``fuzz.WRatio`` for robust cross-language matching.  Only rows that
        already have coordinates are considered.

        Args:
            name (str | None): Plant name to search for.
            threshold (int): Minimum WRatio score (0–100) to accept a match.
                Defaults to 85.

        Returns:
            dict with keys from :attr:`_PPM_COLS` plus ``"ppm_match_score"``,
            or ``None`` if no match above *threshold* was found.
        """
        if not name or pd.isna(name):
            return None

        df_with_coords = self.df_europe.dropna(subset=["lat", "lon"])
        if df_with_coords.empty:
            return None

        pp_names: list[str] = df_with_coords["Name"].dropna().tolist()
        pp_names_lower = [n.lower() for n in pp_names]

        hit = process.extractOne(str(name).lower(), pp_names_lower, scorer=fuzz.WRatio)
        if not hit or float(hit[1]) < threshold:
            return None

        matched_lower = str(hit[0])
        score = float(hit[1])

        # Recover the original (non-lowercased) name for the DataFrame lookup
        try:
            original_name = pp_names[pp_names_lower.index(matched_lower)]
        except ValueError:
            return None

        rows = df_with_coords[df_with_coords["Name"] == original_name]
        if rows.empty:
            return None

        row = rows.iloc[0]
        result = {
            col: (row[col] if col in row.index else None) for col in self._PPM_COLS
        }
        result["ppm_match_score"] = score
        return result
