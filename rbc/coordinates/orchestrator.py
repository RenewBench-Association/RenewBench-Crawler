"""Coordinate location orchestration.

This is used for orchestrating location finding. Currently not very successful....
"""

import pprint
from pathlib import Path

import pandas as pd
from loguru import logger
from rapidfuzz import fuzz, process

from rbc.coordinates.locator_osmpp import OSMPPLocator
from rbc.coordinates.locator_ppm import PPMLocator
from rbc.coordinates.mappings import OPERATOR_METADATA
from rbc.energy.entsoe.mappings import (
    ACTIVE_ZONES_METADATA,
    COLS_MAPPING,
    FUELTYPE_MAPPINGS,
)
from rbc.energy.utils import MissingDataError, load_df_from_file

# from rbc.coordinates.locator_osm_api import query_osm_country_plants --> in the works!


class CoordinateLocator:
    """Coordinate locator orchestrator."""

    def __init__(self, input_dir: Path, output_dir: Path | None = None) -> None:
        """Initialize CoordinateLocator class.

        NOTE: Abbreviations in the class are as follows
        - energy generation (extracted from operator sources):          eg
        - energy-generating entities ("power plants" as in packages):   pp

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. Defaults to None.
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        if not self.input_dir.is_dir():
            raise ValueError(f"Input directory '{input_dir}' is not a directory!")

        self.df_matches = pd.DataFrame()  # to be populated with pp names, lat, lon
        self.match_stats = {  # keep track of how many matches were found
            name: 0
            for name in dir(self)
            if name.startswith("_match_with") and callable(getattr(self, name))
        }

        # get public pp information
        self.df_pp = pd.DataFrame()
        self.ppmloc = PPMLocator()  # Europe only
        self.osmpploc = OSMPPLocator(output_dir=self.output_dir)  # Global

        try:
            self.operator = [p for p in self.input_dir.parts if p in OPERATOR_METADATA][
                0
            ]
            self.country = OPERATOR_METADATA[self.operator]["country"]
            self.name_col = OPERATOR_METADATA[self.operator]["entity_col"]
            self.code_col = OPERATOR_METADATA[self.operator].get("code_col", None)
            self.fuel_col = OPERATOR_METADATA[self.operator].get("fuel_col", None)
            if self.name_col == "":
                raise MissingDataError(
                    f"No 'entity_col' name defined in OPERATOR_METADATA for "
                    f"'{[self.operator]}':\n{OPERATOR_METADATA[self.operator]}"
                )

            if self.country == "Europe":
                bz = self.input_dir.stem
                self.country = str(
                    ACTIVE_ZONES_METADATA[bz]["alias"]
                )  # incorrect for DE!
                self.df_pp = self.ppmloc.get_pp_df_from_static_csv(self.country)
            else:
                self.df_pp = self.osmpploc.get_pp_df_from_static_csv(self.country)

        except IndexError:
            raise ValueError(f"No country match found for '{self.input_dir}'!")

        except KeyError as e:
            raise ValueError(
                f"No country match found in Europe for '{self.input_dir}': {e}"
            )

        except MissingDataError as e:
            raise e

        # this works regardless of ppm or osmpp due to same column names
        self.pp_names = self.df_pp["Name"].unique().tolist()
        self.pp_types = self.df_pp["Fueltype"].unique().tolist()

        logger.info(
            f"CoordinateLocator initalized for: {self.operator} ({self.country})"
        )

    def find_coordinates_using_pp_databases(self) -> pd.DataFrame | None:
        """Find coordinates using power plants databases (ppm / osmpp).

        Returns:
            pd.DataFrame: Dataframe of power plants and any identified coordinates.
        """
        # define relevant columns for matching df
        # rel_cols = [self.name_col, self.code_col] if self.code_col else [self.name_col]
        rel_cols = [self.name_col]
        if self.code_col:
            rel_cols.append(self.code_col)
        if self.fuel_col:
            rel_cols.append(self.fuel_col)

        # FAILSAFE: if the pp database df is empty, exit immediately!
        if self.df_pp.empty:
            logger.warning(
                f"No reference powerplant dataframe available for '{self.country}'! "
                f"Returning structured empty dataframe."
            )
            return pd.DataFrame(columns=rel_cols + ["lat", "lon"])

        for input_path in self.input_dir.glob("*.csv"):  # this won't work for JSONs...
            df_eg = load_df_from_file(input_path)

            # ---- in case it's from entsoe, do some redefinitions (to be removed later!)
            if self.code_col == OPERATOR_METADATA["entsoe"]["code_col"]:
                df_eg = self._renaming_stuff_in_entsoe_df(df_eg)

            # 1. get current eg file's unique pps - df with only "rel_cols"
            df_unique = df_eg[rel_cols].drop_duplicates(subset=[self.name_col])

            # 2. find new additions
            if self.df_matches.empty:  # first run: everything is new
                df_new_additions = df_unique.copy()

            else:  # next runs: only pps NOT already in df are new
                is_new_plant = ~df_unique[self.name_col].isin(
                    self.df_matches[self.name_col]
                )
                df_new_additions = df_unique[is_new_plant].copy()

            # 3. process ONLY the new additions
            if not df_new_additions.empty:
                df_new_additions["lat"] = None
                df_new_additions["lon"] = None

                # 4. run matching logic(s)
                # --- 1. EIC code matching
                if self.code_col == OPERATOR_METADATA["entsoe"]["code_col"]:
                    df_new_additions = self._match_with_eic_code(df_new_additions)
                # --- 2. Name (& fuel type) matching
                df_new_additions = self._match_with_name(df_new_additions)

                # update total identified matches
                self.df_matches = pd.concat(
                    [self.df_matches, df_new_additions], ignore_index=True
                )
                self.log_match_stats()

        return self.df_matches

    def _match_with_eic_code(self, df_eg_unique: pd.DataFrame) -> pd.DataFrame:
        """Find coordinates for powerplants via the EIC (ENTSO-e) code.

        NOTE: This sounds really cool and would be awesome if it had a good success rate.
        Unfortunately it seems like EIC codes are rarely entered into OSM or the likes -
        f.e. of France's 141 units in 2020, 0 matches are found via EIC code.....

        Args:
            df_eg_unique (pd.DataFrame): Dataframe of unique pps from energy generation
                with cols: [rel_cols, lat, lon]

        Returns:
            pd.DataFrame: Original input dataframe including any newly matched coordinates
                with cols: [rel_cols, lat, lon]
        """
        try:
            # --- focus ONLY on rows that haven't been matched yet
            df_unmatched = df_eg_unique[df_eg_unique["lat"].isna()].copy()
            if df_unmatched.empty:
                logger.info("All plants already matched. Skipping code matching.")
                return df_eg_unique

            # --- reduce pp database to 3 column lookup based on EIC code
            df_pp_lookup = self.df_pp[["entsoe_id_list", "lat", "lon"]].explode(
                "entsoe_id_list"
            )

            # --- match EIC codes with inner merge (select ONLY successfully matched rows)
            df_new_matches = pd.merge(
                df_unmatched.drop(columns=["lat", "lon"]),  # drop to avoid double cols!
                df_pp_lookup,
                left_on=self.code_col,
                right_on="entsoe_id_list",
                how="inner",
            ).set_index(self.name_col)[
                ["lat", "lon"]
            ]  # define index for later alignment

            # --- patch the new coordinates in and define new matches ONLY where prev None
            df_output = df_unmatched.set_index(self.name_col)
            df_output = df_output.combine_first(df_new_matches).reset_index()

            # --- log stats
            num_old_matches = df_eg_unique["lat"].notna().sum()
            num_all_matches = df_output["lat"].notna().sum()
            num_new_matches = int(num_all_matches - num_old_matches)
            self.match_stats["_match_with_eic_code"] = num_new_matches
            logger.info(
                f"Successfully matched {num_new_matches} NEW pp (out of {len(df_eg_unique)} "
                f"total) via ENTSOE code matching!"
            )
            return df_output

        except KeyError:
            logger.warning("Error in attempt to find matches via ENTSOE code!")
            return df_eg_unique

    # def _unimplemented__match_with_eic_code_similarity(self, eic: str):
    #     """Potential option: Find similar EIC (ENTOSE) codes - probably not smart..."""
    #
    #     for index, row in self.df_pp.iterrows():
    #         pp_eic = row["entsoe_id_list"][0]
    #
    #         similarity = SequenceMatcher(None, eic, pp_eic).ratio()
    #         logger.info(
    #             f"For plant with EIC {eic}, found plant in ppm csv with similarity "
    #             f"{similarity}:\n{row}"
    #         )

    def _match_with_name(self, df_eg_unique: pd.DataFrame) -> pd.DataFrame:
        """Find coordinates for powerplants via fuzzy name matching.

        Compare pp names from eg data to ones in the pp database. If match is
        found, validated fuel type to see if they are similar (to not accidentally match a
        pp that has a similar name but is actually producing entirely different).

        NOTE: I would expect this to do better... Probably necessary to tweak fuzzy matching!
        F.e. for Poland 11 out of 131 plants are matched...

        Args:
            df_eg_unique (pd.DataFrame): Dataframe of unique pps from energy generation
                with cols: [rel_cols, lat, lon]

        Returns:
            pd.DataFrame: Original input dataframe including any newly matched coordinates
                with cols: [rel_cols, lat, lon]
        """
        try:
            # --- focus ONLY on rows that haven't been matched yet
            df_unmatched = df_eg_unique[df_eg_unique["lat"].isna()].copy()
            if df_unmatched.empty:
                logger.info("All plants already matched. Skipping name matching.")
                return df_eg_unique

            # --- batch fuzzy match the names
            df_unmatched["matched_pp_name"] = df_unmatched[self.name_col].apply(
                lambda x: self._find_best_string_match(x, self.pp_names)
            )
            df_unmatched = df_unmatched.dropna(subset=["matched_pp_name"])

            # --- pull fuel types and coordinates from self.df_pp using the matched names
            df_pp_lookup = self.df_pp[["Name", "Fueltype", "lat", "lon"]].rename(
                columns={"Fueltype": "pp_fueltype"}
            )
            df_pp_lookup = df_pp_lookup.drop_duplicates(subset=["Name"])  # 1-to-1 match

            # --- merge fuzzy mapping to get target data coordinates and fuel types
            df_candidates = pd.merge(
                df_unmatched.drop(columns=["lat", "lon"]),  # drop to avoid double cols!
                df_pp_lookup,
                left_on="matched_pp_name",
                right_on="Name",
                how="inner",
            )

            # !!! FUEL TYPE GUARDRAIL !!!
            # --- filter out rows where a name matched but fuel type is completely mismatched
            if self.fuel_col:
                is_valid_fuel = df_candidates.apply(
                    lambda row: self._is_fueltype_compatible(
                        row[self.fuel_col], row["pp_fueltype"]
                    ),
                    axis=1,
                )
                df_candidates = df_candidates[is_valid_fuel]

            # convert back to an indexable lookup table for combine_first
            df_new_matches = df_candidates.set_index(self.name_col)[["lat", "lon"]]

            # --- patch the validated coordinates into the main dataframe
            df_output = df_eg_unique.set_index(self.name_col)
            df_output = df_output.combine_first(df_new_matches).reset_index()

            # --- log stats
            num_old_matches = df_eg_unique["lat"].notna().sum()
            num_all_matches = df_output["lat"].notna().sum()
            num_new_matches = int(num_all_matches - num_old_matches)
            self.match_stats["_match_with_name"] = num_new_matches
            logger.info(
                f"Successfully matched {num_new_matches} NEW pp (out of {len(df_eg_unique)} "
                f"total) via fuzzy name + fuel type matching!"
            )
            return df_output

        except Exception as e:
            logger.warning(
                f"Error in attempt to find matches via Name + Fuel validation: {e}"
            )
            return df_eg_unique

    # def _outdated__match_with_name(self, name: str, type: str = None):
    #     """Match with name row by row implementation which takes a lot more time!!!
    #
    #     This should work with the ppm or osmpp df, since the relevant column names are
    #     identical ("Name" and "Fueltype" in both).
    #     """
    #     pp_name = self.find_best_match(name, self.pp_names)
    #     if pp_name is None:
    #         logger.warning(f"No match for power plant '{name}' found in ppm csv!")
    #         return None
    #
    #     df_output = self.df_pp.loc[self.df_pp["Name"].str.contains(pp_name, case=False)]
    #     if df_output.empty:
    #         logger.warning(f"Power plant '{name}' not found in ppm csv!")
    #         return None
    #
    #     if type:
    #         pp_type = self.find_best_match(type, self.pp_types)
    #         if pp_name is None:
    #             logger.warning(f"No match for power plant type '{type}' found in ppm csv!")
    #             return df_output
    #
    #         else:
    #             df_output = df_output.loc[df_output["Fueltype"].str.contains(pp_type, case=False)]
    #             if df_output.empty:
    #                 logger.warning(
    #                     f"Power plant '{name}' of type '{type}' not found in ppm csv! "
    #                     f"Only plants with similar names found:\n{df_output}"
    #                 )
    #                 return None
    #
    #     return df_output

    # ----------------
    # Helper methods
    # ----------------
    @staticmethod
    def _find_best_string_match(
        target: str, choices: list[str], threshold: int = 80
    ) -> str | None:
        """Find the best fuzzy match for a string within a list of choices.

        Args:
            target (str): Target string to find match for.
            choices (list[str]): List of choices against which will be matched.
            threshold (int): Fuzzy match threshold. Defaults to 80 (= 80 %).
        """
        if not target or pd.isna(target):
            return None

        target = str(target).lower()
        match = process.extractOne(target, choices, scorer=fuzz.WRatio)
        # match returns: (matched_string, score, index)

        if match and match[1] > threshold:
            return match[0]
        return None

    @staticmethod
    def _is_fueltype_compatible(eg_type: str, pp_type: str) -> bool:
        """Validate if the eg fuel type matches the pp database fuel type.

        Handles basic string cleaning and empty values gracefully.

        Args:
            eg_type (str): fuel type of plant in energy generation df.
            pp_type (str): fuel type of plant in powerplant database.
        """
        if pd.isna(eg_type) or pd.isna(pp_type):
            return True  # if one dataset lacks a type, we pass it but remain cautious

        # normalized substring check (e.g., 'wind onshore' contains 'wind')
        eg_clean = str(eg_type).lower().strip()
        pp_clean = str(pp_type).lower().strip()
        return eg_clean in pp_clean or pp_clean in eg_clean

    @staticmethod
    def _renaming_stuff_in_entsoe_df(df_eg: pd.DataFrame) -> pd.DataFrame:
        """Renaming stuff in the entsoe dataframe where necessary.

        NOTE: THIS IS JUST INTERIM! WILL BE MOVED TO PROCESSOR SCRIPT!

        Args:
            df_eg (pd.DataFrame): dataframe containing ENTSOE eg data.

        Returns:
            df_eg (pd.DataFrame): update dataframe containing ENTSOE eg data.
        """
        # rename column headers (if necessary)
        df_eg = df_eg.rename(columns=COLS_MAPPING)

        # rename PSR fuel types codes or full definition to simple fueltype names
        target_col = None
        possible_col_names = ["PSR_Type", "time_series.mkt_psrtype.psr_type"]

        for col in possible_col_names:
            if col in df_eg.columns:
                target_col = col
                break

        # apply value mappings if the column exists (match code OR full definition)
        if target_col:
            df_eg[target_col] = df_eg[target_col].replace(FUELTYPE_MAPPINGS)

        return df_eg

    # ----------------
    # Documentation methods
    # ----------------
    def log_match_stats(self):
        """Log match stats."""
        matches = self.df_matches["lat"].notna().sum()
        logger.info(
            f"---STATUS---\n"
            f"Coordinates found for {matches} / {len(self.df_matches)} pp: "
            f"\n{pprint.pformat(self.match_stats, indent=4)}"
        )


if "__main__" == __name__:
    input_dir = Path("/path/to/dir/containing/csvs/")  # THIS NEEDS TO BE A REAL PATH!!!

    cl = CoordinateLocator(input_dir=input_dir)
    df_coords = cl.find_coordinates_using_pp_databases()
