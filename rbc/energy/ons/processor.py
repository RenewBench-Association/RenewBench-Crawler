"""ONS DATA PROCESSOR."""

from pathlib import Path

import pandas as pd

from rbc.energy.utils import load_df_from_file, write_df_to_csv

COLS_TRANSLATION = {
    "din_instante": "datetime",
    "id_subsistema": "subsystem_id",
    "nom_subsistema": "subsystem_name",
    "id_estado": "state_id",
    "nom_estado": "state_name",
    "cod_modalidadeoperacao": "operation_mode",
    "nom_tipousina": "plant_type",
    "nom_tipocombustivel": "fuel_type",
    "nom_usina": "plant_name",
    "id_ons": "ons_id",
    "ceg": "generation_project_code",
    "val_geracao": "generation_MWmed",
}
TYPE_TRANSLATION = {
    "HIDROELÉTRICA": "Hydro",
    "TÉRMICA": "Thermal",
    "EOLIELÉTRICA": "Wind",
    "FOTOVOLTAICA": "Solar",
    "NUCLEAR": "Nuclear",
    "Hidráulica": "Hydro",
    "Gás": "Gas",
    "Óleo Diesel": "Diesel Oil",
    "Biomassa": "Biomass",
    "Óleo Combustível": "Fuel Oil",
    "Eólica": "Wind",
    "Carvão": "Coal",
    "Resíduos Industriais": "Industrial Waste",
    "Fotovoltaica": "Photovoltaic",
    "Nuclear": "Nuclear",
}


class OnsProcessor:
    """ONS data processor.

    Attributes:
        input_path (Path): Path to the input directory which contains raw csv files.
        output_path (dict): Path to the output directory.
    """

    def __init__(self, input_path: Path, output_path: Path):
        """Initialize the ONS raw data processor.

        Args:
            input_path (Path): Path to the folder containing ONS raw data file.
            output_path (Path): Path to the destination folder for processed data files.
        """
        self.input_path = input_path
        self.output_path = output_path

    def process(self, input_file_path: Path) -> None:
        """Process previously downloaded, raw ONS energy generation data.

        Processing includes the following steps:
        1. adapt datetime format
        2. translate relevant Portuguese to English

        This allows the raw df to be transformed:
        From:   ['din_instante', 'id_subsistema', 'nom_subsistema', 'id_estado', 'nom_estado',
                 'cod_modalidadeoperacao', 'nom_tipousina', 'nom_tipocombustivel',
                 'nom_usina', 'id_ons', 'ceg', 'val_geracao']
        → to:   tbd

        Args:
            input_file_path (Path): Path to the ONS raw data csv file.
        """
        # load raw electricity generation data
        df: pd.DataFrame = load_df_from_file(input_file_path)

        # translate Portuguese column headers into English
        df = df.rename(columns=COLS_TRANSLATION)

        # adapt datetime format
        df["datetime"] = pd.to_datetime(df["datetime"])
        # set timezone (command accounts for DST before 2019
        df["datetime"] = df["datetime"].dt.tz_localize("America/Sao_Paulo")
        df["datetime"] = df["datetime"].dt.tz_convert("UTC")  # convert to timezone

        # translate Portuguese values (fuel types) into English
        for col in ["plant_type", "fuel_type"]:
            df[col] = df[col].map(TYPE_TRANSLATION)

        # save to output_path folder
        output_file_path = Path(self.output_path, f"{Path(input_file_path).stem}.csv")
        write_df_to_csv(df, output_file_path)
