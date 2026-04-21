"""ADME DATA PROCESSOR."""

from pathlib import Path

import pandas as pd

from rbc.energy.adme.downloader import TIME_COL
from rbc.energy.utils import load_df_from_file, write_df_to_csv

COLS_TRANSLATION = {
    "Fecha": "Datetime",
    "Hidráulico": "Hydro",
    "Biomasa": "Biomass",
    "Térmico": "Thermal",
    "Eólico": "Wind",
    "Solar": "Solar",
}


class AdmeProcessor:
    """ADME data processor.

    Attributes:
        input_path (Path): Path to the input directory which contains raw csv files.
        output_path (dict): Path to the output directory.
    """

    def __init__(self, input_path: Path, output_path: Path):
        """Initialize the ADME raw data processor.

        Args:
            input_path (Path): Path to the folder containing ADME raw data file.
            output_path (Path): Path to the destination folder for processed data files.
        """
        self.input_path = input_path
        self.output_path = output_path

    def process(self, input_file_path: Path) -> None:
        """Process previously downloaded, raw ADME energy generation data.

        Processing includes the following steps:
        1. adapt datetime format

        This allows the raw df to be transformed:
        From:   ['Datetime', 'Hidráulico', 'Biomasa', 'Térmico', 'Eólico', 'Solar']
        → to:   ['datetime', 'unit_name', 'fuel_type', 'value']

        Args:
            input_file_path (Path): Path to the ADME raw data csv file.
        """
        # load raw electricity generation data
        df: pd.DataFrame = load_df_from_file(input_file_path)

        # redefine timestamp column
        df.columns = pd.MultiIndex.from_tuples(
            [("Fecha", "/") if c == TIME_COL else c for c in df.columns]
        )

        # adapt datetime format
        df[("Fecha", "/")] = pd.to_datetime(df[("Fecha", "/")], dayfirst=True)

        # shift from EOI to BOI convention
        df["standard_time"] = pd.to_datetime(df[("Fecha", "/")]) - pd.to_timedelta(
            1, unit="h"
        )

        # translate relevant Spanish into English
        df.columns = pd.MultiIndex.from_tuples(
            [(COLS_TRANSLATION.get(c[0], c[0]), c[1]) for c in df.columns]
        )

        # save to output_path folder
        output_file_path = Path(self.output_path, f"{Path(input_file_path).stem}.csv")
        write_df_to_csv(df, output_file_path)

    @staticmethod
    def _redefine_time_column(df: pd.DataFrame) -> pd.DataFrame:
        """Redefine the timestamp ("Fecha") double column header, aligning naming throughout.

        Args:
            df (pd.DataFrame): Dataframe with "Fecha" double column to be renamed.

        Returns:
            pd.DataFrame: adapted Dataframe.
        """
        df.columns = pd.MultiIndex.from_tuples(
            [
                ("Fecha", "/") if (c[0] == "Fecha" or c == ("/", "Fecha")) else c
                for c in df.columns
            ]
        )
        return df
