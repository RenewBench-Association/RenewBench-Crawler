"""AEMO DATA PROCESSOR."""

from pathlib import Path

import pandas as pd

from rbc.energy.aemo.downloader import EXPECTED_COLS
from rbc.energy.utils import load_df_from_file, write_df_to_csv


class AemoProcessor:
    """AEMO data processor.

    Attributes:
        input_path (Path): Path to the input directory which contains raw csv files.
        output_path (dict): Path to the output directory.
        agg_map (dict): Dictionary of df columns and their respective aggregation function.
    """

    def __init__(self, input_path: Path, output_path: Path):
        """Initialize the AEMO raw data processor.

        Args:
            input_path (Path): Path to the folder containing AEMO raw data file.
            output_path (Path): Path to the destination folder for processed data files.
        """
        self.input_path = input_path
        self.output_path = output_path

        # define aggregation map for later facility data extraction
        self.agg_map = {
            **{
                c: ("min" if "date" in c or "seen" in c else lambda x: list(x.unique()))
                for c in EXPECTED_COLS
                if c.startswith("unit_")
            },
            **{c: "first" for c in EXPECTED_COLS if not c.startswith("unit_")},
            **{"value": "sum"},
        }

    def process(self, input_file_path: Path) -> None:
        """Process previously downloaded, raw AEMO energy generation data.

        Processing includes the following steps:
        1. generate facility data rows from units

        This allows the raw df to be transformed:
        From:   EXPECTED_COLS
        → to:   []

        Args:
            input_file_path (Path): Path to the AEMO raw data csv file.
        """
        # load raw electricity generation data
        df_u: pd.DataFrame = load_df_from_file(input_file_path)

        df_f = df_u.groupby(["timestamp", "code"]).agg(self.agg_map).reset_index()
        df_fu = pd.concat([df_u, df_f], ignore_index=True)
        df_fu = df_fu.sort_values(by=["timestamp", "code"])

        # save to output_path folder
        output_file_path = Path(self.output_path, f"{Path(input_file_path).stem}.csv")
        write_df_to_csv(df_fu, output_file_path)
