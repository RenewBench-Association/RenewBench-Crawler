"""ENTSOE-E DATA PROCESSOR."""

from pathlib import Path

import pandas as pd

from rbc.energy.entsoe.mappings import PSRTYPE_MAPPINGS
from rbc.energy.utils import load_df_from_file


class EntsoeProcessor:
    """Entsoe-E raw data processor."""

    def __init__(self, input_path: Path, output_path: Path) -> None:
        """Initialize the Entso-e raw data processor.

        Args:
            input_path (Path): Path to the folder containing Entso-e raw data file.
            output_path (Path): Path to the destination folder for processed data files.
        """
        self.input_path = input_path
        self.output_path = output_path

        # load dfs from csv and process
        for csv_path in self.input_path.glob("*.csv"):
            df = load_df_from_file(csv_path)
            self.general_processing(df)

    @staticmethod
    def general_processing(df: pd.DataFrame):
        """Perform general processing."""
        df["PSR_Type"] = df["PSR_Type"].map(PSRTYPE_MAPPINGS)
