"""Coordinate location orchestration.

This is used for orchestrating location finding. Currently not very successful....
"""

import pprint
import re
import unicodedata
from pathlib import Path

import pandas as pd
from loguru import logger
from rapidfuzz import fuzz, process

from rbc.coordinates.locator_eic import EICDirectoryLocator, lookup_eic_in_wikidata
from rbc.coordinates.locator_osm_api import query_osm_country_plants
from rbc.coordinates.locator_osmpp import OSMPPLocator
from rbc.coordinates.locator_ppm import PPMLocator
from rbc.coordinates.mappings import (
    COUNTRY_ISO2_MAP,
    GENERIC_UNIT_TOKENS,
    OPERATOR_METADATA,
    PLANT_NAME_EXPANSIONS,
)
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
        self.df_openinfra = pd.DataFrame()
        self.ppmloc = PPMLocator()  # Europe only
        self.osmpploc = OSMPPLocator(output_dir=self.output_dir)  # Global
        self.eic_locator = EICDirectoryLocator(cache_dir=self.output_dir)
        # Maps ENTSO-E unit name -> ordered alternative names for matching.
        # Order matters: original ENTSO-E name is always tried first, then EIC long
        # name, then EIC display name, then a WikiData label as final fallback.
        self._enriched_names: dict[str, list[str]] = {}

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
                assert self.country is not None
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
            return pd.DataFrame(
                columns=rel_cols
                + ["lat", "lon", "osm_id", "osm_type", "osm_url", "osm_geometry"]
            )

        for input_path in self.input_dir.glob("*.csv"):  # this won't work for JSONs...
            df_eg = load_df_from_file(input_path)

            # ---- in case it's from entsoe, do some redefinitions (to be removed later!)

            # TODO: This does not make any sense, I comment it out for now, but if you rename it here, the df_unique below will not have the correct column names anymore, so the code will break.
            # if self.code_col == OPERATOR_METADATA["entsoe"]["code_col"]:
            #    df_eg = self._renaming_stuff_in_entsoe_df(df_eg)

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
                df_new_additions["osm_id"] = None
                df_new_additions["osm_type"] = None
                df_new_additions["osm_url"] = None
                df_new_additions["osm_geometry"] = None

                # 4. run matching logic(s)
                # --- 1. EIC code matching (against ppm CSV entsoe_id_list)
                if self.code_col == OPERATOR_METADATA["entsoe"]["code_col"]:
                    df_new_additions = self._match_with_eic_code(df_new_additions)
                # --- 1.5. WikiData EIC lookup (direct coords) + EIC directory name enrichment
                if self.code_col:
                    df_new_additions = self._match_with_eic_wikidata(df_new_additions)
                # --- 2. Name (& fuel type) matching
                df_new_additions = self._match_with_name(df_new_additions)
                # --- 3. OpenInfra / Overpass fallback for still unmatched rows
                df_new_additions = self._match_with_openinfra(df_new_additions)

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

            # --- batch fuzzy match with ordered candidate names per row:
            # 1) original ENTSO-E unit name
            # 2) EIC long name
            # 3) EIC display name
            # 4) WikiData label (if available)
            def _pick_best_pp_match(row: pd.Series) -> pd.Series:
                source_name = str(row[self.name_col])
                alt_names = self._enriched_names.get(source_name, [])

                best_match = None
                best_score = -1.0
                best_source = "raw"

                ordered_candidates: list[tuple[str | None, str]] = [
                    (source_name, "raw")
                ]
                for idx, alt_name in enumerate(alt_names):
                    source_tag = (
                        "eic_long_name"
                        if idx == 0
                        else "eic_display_name"
                        if idx == 1
                        else "wikidata_name"
                    )
                    ordered_candidates.append((alt_name, source_tag))

                expanded_candidates: list[tuple[str | None, str]] = []
                for candidate_name, source_tag in ordered_candidates:
                    expanded_candidates.append((candidate_name, source_tag))
                    stripped_name = self._strip_numeric_name_tokens(candidate_name)
                    stripped_tag = f"{source_tag}_no_numbers"
                    if stripped_name and stripped_name != candidate_name:
                        expanded_candidates.append((stripped_name, stripped_tag))

                for candidate_name, source_tag in expanded_candidates:
                    if not candidate_name or pd.isna(candidate_name):
                        continue
                    match = process.extractOne(
                        str(candidate_name).lower(),
                        self.pp_names,
                        scorer=fuzz.WRatio,
                    )
                    if match and float(match[1]) > best_score:
                        best_match = str(match[0])
                        best_score = float(match[1])
                        best_source = source_tag

                if best_match and best_score > 80:
                    return pd.Series(
                        {
                            "matched_pp_name": best_match,
                            "matched_score": best_score,
                            "matched_name_source": best_source,
                        }
                    )

                return pd.Series(
                    {
                        "matched_pp_name": None,
                        "matched_score": None,
                        "matched_name_source": None,
                    }
                )

            df_unmatched[
                ["matched_pp_name", "matched_score", "matched_name_source"]
            ] = df_unmatched.apply(_pick_best_pp_match, axis=1)
            df_unmatched = df_unmatched.dropna(subset=["matched_pp_name"])

            if not df_unmatched.empty:
                num_enriched_used = int(
                    (df_unmatched["matched_name_source"] != "raw").sum()
                )
                if num_enriched_used > 0:
                    logger.info(
                        f"Name matching used alternative enriched names for {num_enriched_used} "
                        "plants."
                    )

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

    def _match_with_eic_wikidata(self, df_eg_unique: pd.DataFrame) -> pd.DataFrame:
        """Find coordinates or enrich names via EIC code lookup against WikiData and the ENTSO-E EIC directory.

        Two sub-strategies run for each still-unmatched plant that has an EIC code:

        1. ENTSO-E EIC directory (no API key, fast, offline-capable):
           Looks up the official registered display name for the unit's EIC code.
           The enriched name is stored so that the subsequent OpenInfra fuzzy-matching
           step can use it instead of the often-generic ENTSO-E unit name.

        2. WikiData (P3179 = EIC code, P625 = coordinates):
           If coordinates are found in WikiData they are written directly to lat/lon,
           skipping the name-matching steps entirely.  If only a label is returned it
           is stored as an enriched name for OpenInfra matching.

        Args:
            df_eg_unique (pd.DataFrame): Dataframe of unique pps from energy generation
                with cols: [rel_cols, lat, lon, osm_*]

        Returns:
            pd.DataFrame: Input dataframe with any newly found coordinates filled in.
        """
        try:
            df_unmatched = df_eg_unique[df_eg_unique["lat"].isna()].copy()
            df_with_code = df_unmatched[df_unmatched[self.code_col].notna()]
            if df_with_code.empty:
                return df_eg_unique

            logger.info(
                f"EIC lookup: querying WikiData + EIC directory for "
                f"{len(df_with_code)} unmatched plants with EIC codes..."
            )

            new_coords: dict[str, dict] = {}  # plant_name → {lat, lon, osm_url}

            for _, row in df_with_code.iterrows():
                eic = str(row[self.code_col]).strip()
                plant_name = str(row[self.name_col])

                # --- Strategy 1: EIC directory -> ordered name enrichment
                official_names = self.eic_locator.lookup_names(eic)
                if official_names:
                    ordered_names = [
                        name for name in official_names if name != plant_name
                    ]
                    if ordered_names:
                        self._enriched_names[plant_name] = ordered_names
                        logger.debug(
                            f"  EIC directory: '{plant_name}' -> official names {ordered_names}"
                        )

                # --- Strategy 2: WikiData → direct coordinates (or label enrichment)
                wd = lookup_eic_in_wikidata(eic)
                if wd is None:
                    continue

                if wd.get("name"):
                    existing_names = self._enriched_names.get(plant_name, [])
                    wd_name = str(wd["name"])
                    if wd_name != plant_name and wd_name not in existing_names:
                        self._enriched_names[plant_name] = existing_names + [wd_name]
                        logger.debug(
                            f"  WikiData: '{plant_name}' -> label '{wd['name']}'"
                        )

                if wd.get("lat") is not None and wd.get("lon") is not None:
                    new_coords[plant_name] = {
                        "lat": wd["lat"],
                        "lon": wd["lon"],
                        "osm_url": wd.get("wikidata_url"),  # WikiData URL stored here
                    }
                    logger.info(
                        f"  WikiData: direct coordinates for '{plant_name}' "
                        f"({wd['lat']:.4f}, {wd['lon']:.4f})"
                    )

            num_enriched = len(self._enriched_names)
            if not new_coords:
                self.match_stats["_match_with_eic_wikidata"] = 0
                logger.info(
                    f"EIC lookup: 0 direct coordinate matches. "
                    f"{num_enriched} unit names enriched for downstream matching."
                )
                return df_eg_unique

            df_new_matches = pd.DataFrame(
                [{self.name_col: name, **coords} for name, coords in new_coords.items()]
            ).set_index(self.name_col)

            df_output = df_eg_unique.set_index(self.name_col)
            df_output = df_output.combine_first(df_new_matches).reset_index()

            num_new = int(
                df_output["lat"].notna().sum() - df_eg_unique["lat"].notna().sum()
            )
            self.match_stats["_match_with_eic_wikidata"] = num_new
            logger.info(
                f"EIC lookup: {num_new} direct coordinate matches via WikiData. "
                f"{num_enriched} unit names enriched for downstream matching."
            )
            return df_output

        except Exception as e:
            logger.warning(f"Error in EIC WikiData/directory matching: {e}")
            return df_eg_unique

    def _match_with_openinfra(self, df_eg_unique: pd.DataFrame) -> pd.DataFrame:
        """Find coordinates for powerplants via OpenInfra/Overpass OSM records.

        This method is used as a fallback after ppm/osmpp matching for rows that are
        still unmatched.

        Args:
            df_eg_unique (pd.DataFrame): Dataframe of unique pps from energy generation
                with cols: [rel_cols, lat, lon]

        Returns:
            pd.DataFrame: Original input dataframe including any newly matched coordinates.
        """
        try:
            # --- focus ONLY on rows that haven't been matched yet
            df_unmatched = df_eg_unique[df_eg_unique["lat"].isna()].copy()
            if df_unmatched.empty:
                logger.info("All plants already matched. Skipping OpenInfra matching.")
                return df_eg_unique

            country_code = self._country_to_iso2(self.country)
            if country_code is None:
                logger.warning(
                    f"No ISO-2 mapping available for country '{self.country}'. "
                    f"Skipping OpenInfra matching."
                )
                return df_eg_unique

            if self.df_openinfra.empty:
                self.df_openinfra = query_osm_country_plants(country_code)

            if self.df_openinfra.empty:
                logger.warning(
                    f"OpenInfra/Overpass did not return data for '{self.country}'. "
                    f"Skipping OpenInfra matching."
                )
                return df_eg_unique

            df_lookup = self.df_openinfra[
                [
                    "Name",
                    "Fueltype",
                    "lat",
                    "lon",
                    "OSM_ID",
                    "OSM_Type",
                    "OSM_URL",
                    "OSM_Geometry",
                ]
            ].copy()
            df_lookup = df_lookup.dropna(subset=["Name", "lat", "lon"])
            if df_lookup.empty:
                logger.warning(
                    "OpenInfra dataframe has no usable Name/lat/lon rows. "
                    "Skipping OpenInfra matching."
                )
                return df_eg_unique

            # normalize + expand plant-type tokens for more robust Balkan matching
            df_lookup["name_norm"] = df_lookup["Name"].apply(
                lambda n: self._expand_plant_name_tokens(
                    self._normalize_name(n), PLANT_NAME_EXPANSIONS
                )
            )
            df_lookup = df_lookup[df_lookup["name_norm"] != ""]
            # Drop purely generic entries (e.g. bare "Hidroelektrana" → "hydroelectric")
            # that carry no location information. They score 100 via token_set_ratio
            # against every same-type plant, swamping the correct specific matches.
            # IMPORTANT: only drop single-token entries whose content is a known generic
            # expansion output (e.g. "hydroelectric", "thermal"). Real proper plant names
            # that happen to be a single word (e.g. "Sloecentrale" → "sloecentrale") must
            # NOT be dropped.
            _generic_single_tokens = frozenset(
                v for v in PLANT_NAME_EXPANSIONS.values() if len(v.split()) == 1
            )
            df_lookup = df_lookup[
                ~(
                    (df_lookup["name_norm"].str.split().str.len() == 1)
                    & df_lookup["name_norm"].isin(_generic_single_tokens)
                )
            ]
            df_lookup = df_lookup.drop_duplicates(subset=["name_norm"])  # deterministic
            if df_lookup.empty:
                return df_eg_unique

            choices = df_lookup["name_norm"].tolist()
            lookup_by_norm = df_lookup.set_index("name_norm")

            new_rows: list[dict[str, str | float | None]] = []
            for _, row in df_unmatched.iterrows():
                plant_name = str(row[self.name_col])
                alt_names = self._enriched_names.get(plant_name, [])
                ordered_candidates: list[tuple[str, str]] = [(plant_name, "raw")]
                for idx, alt_name in enumerate(alt_names):
                    source_tag = (
                        "eic_long_name"
                        if idx == 0
                        else "eic_display_name"
                        if idx == 1
                        else "wikidata_name"
                    )
                    ordered_candidates.append((alt_name, source_tag))

                expanded_candidates: list[tuple[str, str]] = []
                for candidate_name, source_tag in ordered_candidates:
                    expanded_candidates.append((candidate_name, source_tag))
                    stripped_name = self._strip_numeric_name_tokens(candidate_name)
                    stripped_tag = f"{source_tag}_no_numbers"
                    if stripped_name and stripped_name != candidate_name:
                        expanded_candidates.append((stripped_name, stripped_tag))

                best_candidate_name = None
                best_candidate_source = "raw"
                best_target_norm = None
                best_top_candidates: list[tuple[str, float, int]] = []
                best_score = -1.0

                for candidate_name, candidate_source in expanded_candidates:
                    raw_norm = self._normalize_name(candidate_name)
                    target_norm = self._expand_plant_name_tokens(
                        raw_norm, PLANT_NAME_EXPANSIONS
                    )
                    if not target_norm:
                        continue

                    top_candidates = process.extract(
                        target_norm,
                        choices,
                        scorer=fuzz.token_set_ratio,
                        limit=3,
                    )
                    top_score = float(top_candidates[0][1]) if top_candidates else -1.0
                    if top_score > best_score:
                        best_score = top_score
                        best_candidate_name = candidate_name
                        best_candidate_source = candidate_source
                        best_target_norm = target_norm
                        best_top_candidates = top_candidates

                if not best_target_norm:
                    continue

                enrich_label = (
                    f" [{best_candidate_source}: '{best_candidate_name}']"
                    if best_candidate_source != "raw"
                    else ""
                )
                logger.debug(
                    f"  OpenInfra top-3 for '{plant_name}'{enrich_label} "
                    f"(norm: '{best_target_norm}'):"
                )
                for cand_norm, cand_score, _ in best_top_candidates:
                    cand_display = df_lookup.loc[
                        df_lookup["name_norm"] == cand_norm, "Name"
                    ]
                    cand_name = (
                        cand_display.iloc[0] if not cand_display.empty else cand_norm
                    )
                    logger.debug(f"    [{cand_score:.0f}] '{cand_name}'")

                match = best_top_candidates[0] if best_top_candidates else None
                if not match:
                    continue

                matched_norm = str(match[0])
                score = float(match[1])
                # Keep threshold moderate because names can vary a lot across datasets.
                if score < 75:
                    logger.debug(
                        f"  -> REJECTED '{row[self.name_col]}': best score {score:.0f} < 75"
                    )
                    continue

                candidate = lookup_by_norm.loc[matched_norm]
                candidate_fuel = candidate.get("Fueltype", None)

                if (
                    self.fuel_col
                    and score < 90
                    and not self._is_fueltype_compatible(
                        row.get(self.fuel_col, None), candidate_fuel
                    )
                ):
                    logger.debug(
                        f"  -> REJECTED '{row[self.name_col]}' by fuel guardrail: "
                        f"eg='{row.get(self.fuel_col, None)}', osm='{candidate_fuel}'"
                    )
                    continue

                new_rows.append(
                    {
                        str(self.name_col): row[self.name_col],
                        "lat": candidate["lat"],
                        "lon": candidate["lon"],
                        "osm_id": candidate.get("OSM_ID", None),
                        "osm_type": candidate.get("OSM_Type", None),
                        "osm_url": candidate.get("OSM_URL", None),
                        "osm_geometry": candidate.get("OSM_Geometry", None),
                    }
                )

            if not new_rows:
                self.match_stats["_match_with_openinfra"] = 0
                logger.info(
                    f"No additional OpenInfra matches found for '{self.country}'."
                )
                return df_eg_unique

            df_new_matches = pd.DataFrame(new_rows).drop_duplicates(
                subset=[self.name_col]
            )
            df_new_matches = df_new_matches.set_index(self.name_col)[
                ["lat", "lon", "osm_id", "osm_type", "osm_url", "osm_geometry"]
            ]

            for col in ["osm_id", "osm_type", "osm_url", "osm_geometry"]:
                if col not in df_eg_unique.columns:
                    df_eg_unique[col] = None
            df_output = df_eg_unique.set_index(self.name_col)
            df_output = df_output.combine_first(df_new_matches).reset_index()

            num_old_matches = df_eg_unique["lat"].notna().sum()
            num_all_matches = df_output["lat"].notna().sum()
            num_new_matches = int(num_all_matches - num_old_matches)
            self.match_stats["_match_with_openinfra"] = num_new_matches
            logger.info(
                f"Successfully matched {num_new_matches} NEW pp (out of {len(df_eg_unique)} "
                f"total) via OpenInfra/Overpass fallback matching!"
            )
            return df_output

        except Exception as e:
            logger.warning(
                f"Error in attempt to find matches via OpenInfra fallback: {e}"
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

        # Normalize ENTSO-E code/definition values to canonical labels before compare.
        eg_clean = CoordinateLocator._normalize_fueltype_label(eg_type)
        pp_clean = CoordinateLocator._normalize_fueltype_label(pp_type)
        return eg_clean in pp_clean or pp_clean in eg_clean

    @staticmethod
    def _normalize_fueltype_label(value: str | None) -> str:
        """Normalize fuel type strings/codes to comparable lowercase labels."""
        if value is None or pd.isna(value):
            return ""
        raw = str(value).strip()
        mapped = FUELTYPE_MAPPINGS.get(raw, raw)
        return str(mapped).lower().strip()

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

    @staticmethod
    def _expand_plant_name_tokens(normalized: str, expansions: dict[str, str]) -> str:
        """Expand known plant-type abbreviations and local names to canonical English.

        Applied token-by-token so that e.g. 'he capljina g1' becomes
        'hydroelectric capljina g1', matching 'hidroelektrana capljina' which
        also expands to 'hydroelectric capljina'.

        Args:
            normalized (str): Already-normalized (lowercase, diacritic-free) name.
            expansions (dict[str, str]): Mapping of known tokens to canonical terms.

        Returns:
            str: Name with known tokens replaced by canonical English equivalents.
        """
        if not normalized:
            return normalized
        tokens = normalized.split()
        return " ".join(expansions.get(tok, tok) for tok in tokens)

    @staticmethod
    def _normalize_name(value: str | None) -> str:
        """Normalize power plant names for robust cross-source matching."""
        if value is None or pd.isna(value):
            return ""

        text = str(value).lower().strip()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @classmethod
    def _strip_numeric_name_tokens(cls, value: str | None) -> str:
        """Return a simplified normalized name for station-level fallback matching.

        This is a last-resort fallback for cases where ENTSO-E names include unit
        numbers and generic unit markers (e.g. "Unit 20", "Sloecentrale unit 20")
        but OSM only stores the station-level feature without a per-unit suffix
        (e.g. just "Sloecentrale").
        """
        normalized = cls._normalize_name(value)
        if not normalized:
            return ""

        tokens = [
            token
            for token in normalized.split()
            if not token.isdigit() and token not in GENERIC_UNIT_TOKENS
        ]
        return " ".join(tokens).strip()

    @staticmethod
    def _country_to_iso2(country: str | None) -> str | None:
        """Map country name aliases used in datasets to ISO-2 country code."""
        if not country:
            return None
        return COUNTRY_ISO2_MAP.get(str(country).strip().lower(), None)

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
    input_dir = Path(
        "../testdata/energy/entsoe/1h/10YPT-REN------W/"
    )  # THIS NEEDS TO BE A REAL PATH!!!

    cl = CoordinateLocator(input_dir=input_dir)
    df_coords = cl.find_coordinates_using_pp_databases()

    print(df_coords)
