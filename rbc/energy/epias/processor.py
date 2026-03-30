"""EPIAS DATA PROCESSOR."""

import pandas as pd


class EPIASProcessor:
    """EPIAS raw data processor."""

    def __init__(self):
        """EPIAS processor init (empty for now)."""
        pass

    @staticmethod
    def _split_plant_name(df_gen: pd.DataFrame) -> pd.DataFrame:
        r"""Split the plant name into plant name, EIC code and ID.

        Split the plant name (powerPlantName) into plant name, EIC code and ID
        using the pattern:
        1. (?P<shortName>.*?) match everything at the start
        2. -(?P<eic>40W[A-Z0-9]{13})- match 16-char EIC flanked by dashes
        3. (?P<id>\d{1,4})$ match the 1-4 digit ID at the very end

        Examples:
        -   powerPlantName:     SARAL-3 HES-40W000000014543G-2542
            shortName, EIC, ID: SARAL-3 HES, 40W000000014543G, 2542
        -   powerPlantName:     ACIBADEM BURSA-663
            shortName, EIC, ID: ACIBADEM BURSA, NaN, 663

        Args:
            df_gen (pd.DataFrame): Dataframe of energy generation data

        Returns:
            df: updated df_gen dataframe
        """
        extracted_columns = df_gen["powerPlantName"].str.extract(
            r"(?P<shortName>.*?)-(?P<eic>40W[A-Z0-9]{13})-(?P<id>\d{1,4})$"
        )
        df_gen[["shortName", "eic", "id"]] = extracted_columns

        # where pattern didn't match (i.e. no EIC number), split once from ID
        missing = df_gen["eic"].isna()
        if missing.any():
            name, id_code = df_gen.loc[missing, "powerPlantName"].str.rsplit(
                "-", n=1, expand=True
            )
            df_gen.loc[missing, "shortName"] = name
            df_gen.loc[missing, "id"] = id_code

        # raise error if any shortNames have not been defined
        if df_gen["shortName"].isna().any():
            raise ValueError(
                "Error in splitting plant names! Some shortnames are not defined."
            )

        return df_gen
