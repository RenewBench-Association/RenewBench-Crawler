"""ENTSOE-E DATA PROCESSOR."""

from pathlib import Path

import pandas as pd

from rbc.energy.entsoe.mappings import PSRTYPE_MAPPINGS
from rbc.energy.utils import load_df_from_file, write_df_to_csv

COLS_MAPPING = {
    "timestamp": "timestamp",
    "time_series.mkt_psrtype.power_system_resources.name": "Unit_Name",
    "time_series.mkt_psrtype.power_system_resources.m_rid.value": "Unit_Code",
    "time_series.mkt_psrtype.psr_type": "PSR_Type",
    "time_series.mkt_psrtype.power_system_resources.nominal_p": "Capacity",
    "time_series.period.point.quantity": "Generation_MW",
    "time_series.period.point.secondary_quantity": "Consumption_MW",
    "time_series.quantity_measure_unit_name": "Measurement_Unit",
    "time_series.period.resolution": "Temporal_Resolution",
}


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
        for csv_path in self.input_path.rglob("*.csv"):
            self.process(input_file_path=csv_path)

    def process(self, input_file_path: Path) -> None:
        """Process previously downloaded, raw ENTSO-e energy generation data.

        Processing includes the following steps:
        1. rename column headers

        This allows the raw df to be transformed:
        From:   ['timestamp', 'time_series.mkt_psrtype.power_system_resources.name',
                 'time_series.mkt_psrtype.power_system_resources.m_rid.value',
                 'time_series.mkt_psrtype.psr_type',
                 'time_series.mkt_psrtype.power_system_resources.nominal_p',
                 'time_series.period.point.quantity',
                 'time_series.period.point.secondary_quantity',
                 'time_series.quantity_measure_unit_name',
                 'time_series.period.resolution']
        → to:   tbd

        Args:
            input_file_path (Path): Path to the ONS raw data csv file.
        """
        # load raw electricity generation data
        df: pd.DataFrame = load_df_from_file(input_file_path)

        # rename column headers
        df = df.rename(columns=COLS_MAPPING)

        # convert PSR type codes into actual fuel types
        df["Fuel_Type"] = df["PSR_Type"].map(PSRTYPE_MAPPINGS)

        # save to output_path folder
        bz = input_file_path.parent
        output_path = Path(self.output_path, bz)
        output_path.mkdir(parents=True, exist_ok=True)
        output_file_path = Path(output_path, f"{Path(input_file_path).stem}.csv")
        write_df_to_csv(df, output_file_path)
