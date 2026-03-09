"""IESO DATA PROCESSOR."""

import difflib
import re
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

from rbc.energy.utils import load_df_from_file, write_df_to_csv

URL_GENERATORS = "https://www.ieso.ca/localcontent/ontarioenergymap/js/map.js"


class IesoProcessor:
    """IESO data processor.

    Attributes:
        input_path (Path): Path to the input directory which contains raw csv files.
        output_path (dict): Path to the output directory.
        df_map_info (pd.DataFrame): Dataframe containing generator info from IESO Energy Map.
    """

    def __init__(self, input_path: Path, output_path: Path):
        """Initialize the IESO raw data processor.

        Args:
            input_path (Path): Path to the folder containing IESO raw data file.
            output_path (Path): Path to the destination folder for processed data files.
        """
        self.input_path = input_path
        self.output_path = output_path

        # get generator information from IESO Energy Map
        self.df_map_info = self.extract_generator_types_and_locs()

    @staticmethod
    def extract_generator_types_and_locs() -> pd.DataFrame:
        """Extract generator info (fuel type and location coordinates) from IESO Energy Map.

        Extracts information from all markers in the IESO Energy Map / associated
        javascript (js) file. For all currently active generators in Ontario, this gets:
        ['Generator', 'Latitude', 'Longitude', 'Fuel Type', 'Note' (optional)]

        Returns:
            pd.DataFrame: Generator info from IESO Energy Map.

        Raises:
            ValueError: If the js structure has changed and search for patterns comes up short.
        """
        js = requests.get(URL_GENERATORS).text

        # extract the genMarkersRef array (info block for generator markers on the map)
        pattern = r"var\s+genMarkersRef\s*=\s*\[(.*?)\];"
        match = re.search(pattern, js, re.DOTALL)

        if not match:
            raise ValueError(
                "Could not find a 'genMarkersRef' section in the js. The IESO Energy Map "
                "structure seems to have changed! Please adapt the regex pattern search."
            )

        array_text = match.group(1)

        # extract map points:   ['name', google.maps.LatLng(lat, lon), 'tech', (optional) 'note']
        entry_pattern = r"\['(.*?)',\s*new google\.maps\.LatLng\((.*?),\s*(.*?)\),\s*'(.*?)'(?:,\s*'(.*?)')?\]"
        entries = re.findall(entry_pattern, array_text)

        if not entries:
            raise ValueError(
                "Could not find the defined entry pattern in the js. The IESO Energy Map "
                "structure seems to have changed! Please adapt the regex pattern search."
            )

        map_generators = []
        for name, lat, lon, tech, note in entries:
            map_generators.append(
                {
                    "Generator": name,
                    "Latitude": float(lat),
                    "Longitude": float(lon),
                    "Fuel Type": tech.upper(),  # make uppercase to match EG data
                    "Note": note if note else None,
                }
            )

        return pd.DataFrame(map_generators)

    def process(self, input_file_path: Path) -> None:
        """Process previously downloaded, raw IESO energy generation data.

        Processing includes the following steps:
        1. match generator names from the EG df to those existing in the IESO Energy Map.
        2. insert generator location (lat / lon columns)
        3. (re)define 'Fuel Type' values where non-existent
        4. (re)define 'Measurement' values where inconsistent.
        This allows the raw df to be transformed:
        From:   ['Delivery Date', 'Generator', 'Fuel Type', 'Measurement', 'Hour 1', ..., 'Hour 24']
        → to:   ['Delivery Date', 'Generator', 'Fuel Type', 'Measurement', 'Hour 1', ..., 'Hour 24',
                 'Latitude', 'Longitude']

        Args:
            input_file_path (Path): Path to the IESO raw data csv file.
        """
        # load raw electricity generation data
        df_eg_raw: pd.DataFrame = load_df_from_file(input_file_path)

        # 1. get matches
        df_eg_gens = df_eg_raw["Generator"].unique()

        match_dict = {}
        for gen in df_eg_gens:
            match_name = self.best_generator_match(generator=gen)
            if match_name:
                match_dict[gen] = match_name
            else:
                logger.warning(f"No match in IESO Energy Map for generator: {gen}")

        # define a filtered main df with only generators that have a match
        df_eg = df_eg_raw[df_eg_raw["Generator"].isin(match_dict.keys())].copy()

        # 2. insert map coordinates (lat/lon) into main df
        df_eg["Matched_Gen"] = df_eg["Generator"].map(match_dict)  # temp column
        # for lookup

        map_lookup = self.df_map_info.set_index("Generator")
        df_eg["Latitude"] = df_eg["Matched_Gen"].map(map_lookup["Latitude"])
        df_eg["Longitude"] = df_eg["Matched_Gen"].map(map_lookup["Longitude"])

        # 3. check / insert fuel type
        df_eg["Fuel Type"] = df_eg["Fuel Type"].astype(object)
        mapped_fuel = df_eg["Matched_Gen"].map(map_lookup["Fuel Type"])

        # --- pre-2019: 'Fuel Type' non-existent (simply stored as "None")
        no_fuel_type = df_eg["Fuel Type"].isna() | (df_eg["Fuel Type"] == "None")
        df_eg.loc[no_fuel_type, "Fuel Type"] = mapped_fuel[no_fuel_type]

        # --- post-2019: 'Fuel Type' already exists -> check if values conflict with map!
        has_fuel_type = ~no_fuel_type
        conflicts = df_eg[has_fuel_type & (df_eg["Fuel Type"] != mapped_fuel)]

        if not conflicts.empty:
            for _, row in (
                conflicts[["Generator", "Fuel Type", "Matched_Gen"]]
                .drop_duplicates()
                .iterrows()
            ):
                eg_fuel = row["Fuel Type"]
                map_fuel = map_lookup.loc[row["Matched_Gen"], "Fuel Type"]
                logger.warning(
                    f"For generator {row['Generator']}, fuel type from EG data {eg_fuel} "
                    f"does not match map fuel type {map_fuel}! Sticking to EG data type."
                )

        df_eg.drop(columns=["Matched_Gen"], inplace=True)

        # 4. redefine capacity for consistency (old: all=capability, new: wind=avail cap)
        df_eg["Measurement"] = df_eg["Measurement"].replace(
            ["Available Capacity", "Capability"], "Capacity"
        )

        # save to output_path folder
        output_file_path = Path(self.output_path, f"{Path(input_file_path).stem}.csv")
        write_df_to_csv(df_eg, output_file_path)

    def best_generator_match(self, generator: str) -> str | None:
        """Find the best matching generator facility for a given generator name.

        Args:
            generator (str): EG generator name

        Returns:
            str | None: best matching generator if one was found, otherwise None.
        """
        map_names = {
            homogenize_str(n): n for n in self.df_map_info["Generator"].tolist()
        }
        gen = homogenize_str(generator)

        # partial substring filter: must overlap strongly
        candidates = [k for k in list(map_names.keys()) if gen[:4] in k or k[:4] in gen]
        if not candidates:
            return None

        # pick best difflib match within the found candidates
        best = difflib.get_close_matches(gen, candidates, n=1, cutoff=0.6)
        if not best:
            return None

        return map_names[best[0]]  # return original generator name in IESO Energy Map


def homogenize_str(s: str) -> str:
    """Homogenize string by removing spaces and punctuation and making it uppercase.

    Args:
        s (str): String to homogenize

    Returns:
        str: Homogenized string
    """
    return re.sub(r"[^A-Z0-9]", "", s.upper())
