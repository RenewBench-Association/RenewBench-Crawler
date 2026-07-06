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

from rbc.coordinates.locator_eic import (
    EICDirectoryLocator,
    _alpha_prefix,
)
from rbc.coordinates.locator_gem import GEMLocator
from rbc.coordinates.locator_osm_api import query_osm_country_plants
from rbc.coordinates.locator_osmpp import OSMPPLocator
from rbc.coordinates.locator_ppm import PPMLocator
from rbc.coordinates.map import build_map
from rbc.coordinates.mappings import (
    COUNTRY_ISO2_MAP,
    COUNTRY_PLANT_NAME_EXPANSIONS,
    GENERIC_UNIT_TOKENS,
    OPERATOR_METADATA,
    PLANT_NAME_EXPANSIONS,
)
from rbc.energy.entsoe.mappings import (
    ACTIVE_ZONES_METADATA,
    COLS_MAPPING,
    FUELTYPE_CODE_MAPPINGS,
    FUELTYPE_MAPPINGS,
)
from rbc.energy.utils import MissingDataError, load_df_from_file

# from rbc.coordinates.locator_osm_api import query_osm_country_plants --> in the works!


class CoordinateLocator:
    """Coordinate locator orchestrator."""

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        osm_update: bool = False,
        osm_live: bool = False,
        gem_dir: Path | None = None,
    ) -> None:
        """Initialize CoordinateLocator class.

        NOTE: Abbreviations in the class are as follows
        - energy generation (extracted from operator sources):          eg
        - energy-generating entities ("power plants" as in packages):   pp

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. Defaults to None.
            osm_update (bool): Re-fetch OSM data from Overpass and overwrite the local
                ``overpass_<CC>_plants.parquet`` file even if it already exists.
                Corresponds to the ``--update`` / ``-u`` CLI flag.
            osm_live (bool): Query Overpass live on every run, ignoring and not writing
                any local file.  Corresponds to the ``--live`` CLI flag.
            gem_dir (Path, optional): Directory containing manually downloaded Global
                Energy Monitor (GEM) tracker xlsx files
                (https://globalenergymonitor.org/download-data). When given, GEM is
                used as an additional coordinate source alongside powerplantmatching
                (PPM) in the ENTSOE enrichment pipeline. Defaults to None (GEM disabled).
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.osm_update = osm_update
        self.osm_live = osm_live
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
        self.eic_locator = EICDirectoryLocator(cache_dir=self.output_dir)  # europe only
        self.osmpploc = OSMPPLocator(output_dir=self.output_dir)  # Global
        self.gemloc = (
            GEMLocator(gem_dir=gem_dir, cache_dir=self.output_dir) if gem_dir else None
        )  # optional, requires manual download

        # Maps ENTSO-E unit name -> ordered alternative names for matching.
        # Order matters: original ENTSO-E name is always tried first, then EIC long
        # name, then EIC display name.
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

        # Country-specific plant-name-token expansions layered on top of the
        # global defaults (e.g. Estonian "elektrijaam" -> "soojuselektrijaam").
        country_code = self._country_to_iso2(self.country)
        self._plant_name_expansions: dict[str, str] = {
            **PLANT_NAME_EXPANSIONS,
            **COUNTRY_PLANT_NAME_EXPANSIONS.get(country_code or "", {}),
        }

        logger.info(
            f"CoordinateLocator initalized for: {self.operator} ({self.country})"
        )

    def find_coordinates_using_pp_databases(self) -> pd.DataFrame | None:
        """Find coordinates using power plants databases (ppm / osmpp).

        For ENTSOE data this delegates to the richer
        :meth:`find_and_enrich_entsoe_coordinates` pipeline which performs
        source-traceable enrichment through W_eicCodes, powerplantmatching and
        OpenInfraMap.  All other operators follow the legacy matching path.

        Returns:
            pd.DataFrame: Dataframe of power plants and any identified coordinates.
        """
        # ENTSOE: use the new enriched pipeline
        if self.code_col == OPERATOR_METADATA["entsoe"]["code_col"]:
            return self.find_and_enrich_entsoe_coordinates()

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
                # --- 2. OpenInfra / Overpass fallback for still unmatched rows
                df_new_additions = self._match_with_openinfra(df_new_additions)

                # update total identified matches
                self.df_matches = pd.concat(
                    [self.df_matches, df_new_additions], ignore_index=True
                )
                self.log_match_stats()

        return self.df_matches

    def find_and_enrich_entsoe_coordinates(self) -> pd.DataFrame:
        """Run the full ENTSOE source-traceable enrichment pipeline.

        All output columns are prefixed by their source so that the provenance of
        every value is immediately clear:

        - ``pp.*``            — from the raw energy production CSV files
        - ``wcode.*``         — from the ENTSO-E W_eicCodes directory
        - ``wcode.parent.*``  — parent production unit resolved from W_eicCodes
        - ``ppm.*``           — from the PyPSA powerplantmatching database
        - ``gem.*``           — from the Global Energy Monitor trackers (optional,
                                requires ``gem_dir`` to be set)
        - ``osm.*``           — from the OpenInfraMap / Overpass fallback
        - ``sibling.*``       — coordinates inherited from another already-matched
                                unit of the same physical plant (same EicParent)
        - ``lat``, ``lon``    — best available coordinates (ppm, then gem, then
                                osm, then sibling)
        - ``match_source``    — one of: ppm_direct · ppm_parent_direct ·
                                ppm_parent_entsoe_id · ppm_fuzzy_name · gem_direct ·
                                gem_parent_direct · gem_parent_entsoe_id ·
                                gem_fuzzy_name · osm · sibling_unit · unmatched

        Pipeline steps:
            1.  Collect & deduplicate unique generation units across all CSVs.
            2.  Add ``pp.fuel_type`` from :data:`FUELTYPE_CODE_MAPPINGS`.
            3.  Enrich with W_eicCodes.csv → ``wcode.*`` columns.
            4.  GEM/PPM direct match by unit EIC code or, if available, by the
                EicParent code already stored in ``wcode.EicParent`` (GEM tried
                first — unit ID then parent ID — PPM used as fallback).
            5.  Fuzzy parent-unit search within W_eicCodes → ``wcode.parent.*``.
            6.  GEM/PPM match via resolved parent EIC code.
            7.  PPM/GEM fuzzy name match guarded by a fuel-type check.
            8.  Fuel-type validation for all PPM/GEM-matched units.
            9.  OpenInfraMap / Overpass fallback for still-unmatched units.
            10. Sibling-unit fallback: units sharing the same EicParent (i.e. the
                same physical plant) as an already-matched unit inherit that
                unit's coordinates, e.g. an unnamed extra generator block of a
                plant whose other blocks were already matched.
            11. Finalise ``lat`` / ``lon`` and write ``enriched_units_<zone>.csv``.

        Returns:
            pd.DataFrame: Enriched dataframe, one row per unique generation unit.
        """
        zone_name = self.input_dir.name

        # ------------------------------------------------------------------ #
        # 1. Load and aggregate unique units across all CSVs                 #
        # ------------------------------------------------------------------ #
        all_dfs: list[pd.DataFrame] = []
        for input_path in sorted(self.input_dir.glob("*.csv")):
            all_dfs.append(load_df_from_file(input_path))

        if not all_dfs:
            logger.warning(f"No CSV files found in '{self.input_dir}'.")
            return pd.DataFrame()

        df_all = pd.concat(all_dfs, ignore_index=True)

        rel_cols = [
            c
            for c in [self.name_col, self.code_col, self.fuel_col]
            if c and c in df_all.columns
        ]
        df = (
            df_all[rel_cols]
            .drop_duplicates(subset=[self.code_col])
            .reset_index(drop=True)
        )

        logger.info(
            f"[{zone_name}] {len(df)} unique generation units found across {len(all_dfs)} CSV(s)."
        )

        # ------------------------------------------------------------------ #
        # 2. Rename production columns with pp. prefix + add pp.fuel_type    #
        # ------------------------------------------------------------------ #
        rename_map = {c: f"pp.{c}" for c in rel_cols}
        df = df.rename(columns=rename_map)

        pp_code_col = f"pp.{self.code_col}"
        pp_name_col = f"pp.{self.name_col}"
        pp_fuel_col = f"pp.{self.fuel_col}" if self.fuel_col else None

        df["pp.fuel_type"] = None
        if pp_fuel_col and pp_fuel_col in df.columns:
            df["pp.fuel_type"] = df[pp_fuel_col].map(
                lambda x: (
                    FUELTYPE_CODE_MAPPINGS.get(str(x).strip()) if pd.notna(x) else None
                )
            )

        # ------------------------------------------------------------------ #
        # 3. Enrich with W_eicCodes (wcode.*)                                #
        # ------------------------------------------------------------------ #
        wcode_fields = list(self.eic_locator._WCODE_FIELDS)
        for col in wcode_fields:
            df[f"wcode.{col}"] = None

        for idx, row in df.iterrows():
            eic = row.get(pp_code_col)
            if pd.isna(eic) or not str(eic).strip():
                continue
            full_row = self.eic_locator.lookup_full_row(str(eic).strip())
            for col in wcode_fields:
                df.at[idx, f"wcode.{col}"] = full_row.get(col)

        wcode_populated = df["wcode.EicLongName"].notna().sum()
        logger.info(
            f"[{zone_name}] W_eicCodes enrichment: {wcode_populated}/{len(df)} units found in EIC directory."
        )

        # ------------------------------------------------------------------ #
        # 4. GEM/PPM direct match by unit EIC code or wcode.EicParent        #
        # ------------------------------------------------------------------ #
        ppm_cols = list(self.ppmloc._PPM_COLS)
        for col in ppm_cols:
            df[f"ppm.{col}"] = None
        df["ppm.match_source"] = None

        gem_cols = list(GEMLocator._GEM_COLS)
        for col in gem_cols:
            df[f"gem.{col}"] = None
        df["gem.match_source"] = None

        def _still_unmatched(frame: pd.DataFrame) -> pd.Series:
            return frame["ppm.lat"].isna() & frame["gem.lat"].isna()

        for idx, row in df[_still_unmatched(df)].iterrows():
            eic = row.get(pp_code_col)
            parent_eic = row.get("wcode.EicParent")
            hit, source = None, None

            # 1. GEM: try the unit (generation) EIC directly
            if self.gemloc and pd.notna(eic) and str(eic).strip():
                hit = self.gemloc.match_by_entsoe_id(str(eic).strip())
                source = "gem_direct"

            # 2. GEM: try the parent (production) EIC from wcode.EicParent
            if (
                hit is None
                and self.gemloc
                and pd.notna(parent_eic)
                and str(parent_eic).strip()
            ):
                hit = self.gemloc.match_by_entsoe_id(str(parent_eic).strip())
                source = "gem_parent_direct"

            # 3. PPM fallback: unit EIC directly
            if hit is None and pd.notna(eic) and str(eic).strip():
                hit = self.ppmloc.match_by_entsoe_id(str(eic).strip())
                source = "ppm_direct"

            # 4. PPM fallback: parent EIC from wcode.EicParent
            if hit is None and pd.notna(parent_eic) and str(parent_eic).strip():
                hit = self.ppmloc.match_by_entsoe_id(str(parent_eic).strip())
                source = "ppm_parent_direct"

            if hit is not None:
                if source is not None and source.startswith("gem"):
                    for col in gem_cols:
                        df.at[idx, f"gem.{col}"] = hit.get(col)
                    df.at[idx, "gem.match_source"] = source
                else:
                    for col in ppm_cols:
                        df.at[idx, f"ppm.{col}"] = hit.get(col)
                    df.at[idx, "ppm.match_source"] = source

        ppm_direct_count = df["ppm.lat"].notna().sum()
        gem_direct_count = df["gem.lat"].notna().sum()
        logger.info(
            f"[{zone_name}] Direct/EicParent match: {gem_direct_count} via GEM, "
            f"{ppm_direct_count} via PPM (out of {len(df)})."
        )

        # ------------------------------------------------------------------ #
        # 5. Fuzzy parent-unit matching within W_eicCodes (wcode.parent.*)   #
        # ------------------------------------------------------------------ #
        parent_meta = [
            "EicCode",
            "EicDisplayName",
            "EicLongName",
            "EicResponsibleParty",
            "match_score",
            "match_confidence",
            "match_method",
        ]
        for col in parent_meta:
            df[f"wcode.parent.{col}"] = None

        for idx, row in df[_still_unmatched(df)].iterrows():
            parent = self.eic_locator.find_parent_production_unit(
                eic_parent=row.get("wcode.EicParent")
                if pd.notna(row.get("wcode.EicParent"))
                else None,
                display_name=row.get("wcode.EicDisplayName")
                if pd.notna(row.get("wcode.EicDisplayName"))
                else None,
                long_name=row.get("wcode.EicLongName")
                if pd.notna(row.get("wcode.EicLongName"))
                else None,
                responsible_party=row.get("wcode.EicResponsibleParty")
                if pd.notna(row.get("wcode.EicResponsibleParty"))
                else None,
            )
            if parent is not None:
                for col in parent_meta:
                    df.at[idx, f"wcode.parent.{col}"] = parent.get(col)

        parent_found = df["wcode.parent.EicCode"].notna().sum()
        logger.info(
            f"[{zone_name}] Fuzzy parent matching: {parent_found} parent production units resolved."
        )

        # ------------------------------------------------------------------ #
        # 6. GEM/PPM match via resolved parent EIC code                      #
        # ------------------------------------------------------------------ #
        # Only trust "high" confidence parent resolutions (direct EicParent
        # lookup, or a fuzzy match scoring >= 90) for this direct/unguarded EIC
        # code lookup. "medium" confidence guesses (e.g. a display-name-prefix
        # match built on a short, generic plant-type abbreviation) are too easy
        # to get wrong across countries and must go through fuzzy name + fuel
        # validation (step 7) instead, where a fuel-type mismatch can veto them.
        for idx, row in df[_still_unmatched(df)].iterrows():
            parent_eic = row.get("wcode.parent.EicCode")
            if pd.isna(parent_eic) or not str(parent_eic).strip():
                continue
            if row.get("wcode.parent.match_confidence") != "high":
                continue
            parent_eic_str = str(parent_eic).strip()

            hit = (
                self.gemloc.match_by_entsoe_id(parent_eic_str) if self.gemloc else None
            )
            if hit is not None:
                for col in gem_cols:
                    df.at[idx, f"gem.{col}"] = hit.get(col)
                df.at[idx, "gem.match_source"] = "gem_parent_entsoe_id"
            else:
                hit = self.ppmloc.match_by_entsoe_id(parent_eic_str)
                if hit is not None:
                    for col in ppm_cols:
                        df.at[idx, f"ppm.{col}"] = hit.get(col)
                    df.at[idx, "ppm.match_source"] = "ppm_parent_entsoe_id"

        ppm_after_parent = df["ppm.lat"].notna().sum()
        gem_after_parent = df["gem.lat"].notna().sum()
        logger.info(
            f"[{zone_name}] Match via parent EIC: "
            f"{gem_after_parent - gem_direct_count} additional via GEM, "
            f"{ppm_after_parent - ppm_direct_count} additional via PPM "
            f"({ppm_after_parent + gem_after_parent} total)."
        )

        # ------------------------------------------------------------------ #
        # 7. PPM/GEM fuzzy name match                                        #
        # ------------------------------------------------------------------ #
        for idx, row in df[_still_unmatched(df)].iterrows():
            # Priority order: wcode long name → parent long name → raw pp name
            candidates = [
                row.get("wcode.EicLongName"),
                row.get("wcode.parent.EicLongName"),
                row.get(pp_name_col),
            ]
            eg_fuel = row.get("pp.fuel_type")

            matched = False
            for candidate in candidates:
                if pd.isna(candidate) or not str(candidate).strip():
                    continue
                candidate_str = str(candidate).strip()

                # Also try the name with a trailing glued unit-suffix stripped
                # (e.g. "ENGURIUNIT_5" -> "enguri"), which the space-tokenized
                # _strip_numeric_name_tokens can't catch since there's no
                # separator between the plant name and the unit suffix.
                stripped_unit_suffix = self._strip_trailing_unit_suffix(candidate_str)
                name_variants = [candidate_str]
                if stripped_unit_suffix:
                    name_variants.append(stripped_unit_suffix)

                for name_variant in name_variants:
                    hit = self.ppmloc.fuzzy_match_by_name(
                        name_variant, country=self.country
                    )
                    if hit is not None and self._is_fueltype_compatible(
                        eg_fuel, hit.get("Fueltype")
                    ):
                        for col in ppm_cols:
                            df.at[idx, f"ppm.{col}"] = hit.get(col)
                        df.at[idx, "ppm.match_source"] = "ppm_fuzzy_name"
                        matched = True
                        break

                    if self.gemloc:
                        hit = self.gemloc.fuzzy_match_by_name(
                            name_variant, country=self.country, fuel_type=eg_fuel
                        )
                        if hit is not None and self._is_fueltype_compatible(
                            eg_fuel, hit.get("Fueltype")
                        ):
                            for col in gem_cols:
                                df.at[idx, f"gem.{col}"] = hit.get(col)
                            df.at[idx, "gem.match_source"] = "gem_fuzzy_name"
                            matched = True
                            break

                if matched:
                    break

        ppm_final = df["ppm.lat"].notna().sum()
        gem_final = df["gem.lat"].notna().sum()
        logger.info(
            f"[{zone_name}] Fuzzy name match: "
            f"{ppm_final - ppm_after_parent} additional via PPM, "
            f"{gem_final - gem_after_parent} additional via GEM "
            f"({ppm_final + gem_final} total)."
        )

        # ------------------------------------------------------------------ #
        # 8. Fuel-type validation for all PPM/GEM-matched units              #
        # ------------------------------------------------------------------ #
        df["fuel_type_match"] = None
        df["fuel_type_match_level"] = None
        matched_mask = df["ppm.lat"].notna() | df["gem.lat"].notna()
        for idx, row in df[matched_mask].iterrows():
            matched_fueltype = (
                row.get("ppm.Fueltype")
                if pd.notna(row.get("ppm.lat"))
                else row.get("gem.Fueltype")
            )
            level = self._classify_fueltype_match(
                row.get("pp.fuel_type"), matched_fueltype
            )
            df.at[idx, "fuel_type_match"] = level != "mismatch"
            df.at[idx, "fuel_type_match_level"] = level

        mismatches = (df["fuel_type_match_level"] == "mismatch").sum()
        if mismatches:
            logger.warning(
                f"[{zone_name}] Fuel-type mismatch on {mismatches} matched unit(s) — "
                f"verify these rows manually."
            )

        # ------------------------------------------------------------------ #
        # 9. OpenInfraMap / Overpass fallback                                #
        # ------------------------------------------------------------------ #
        osm_out_cols = ["lat", "lon", "id", "type", "url", "geometry"]
        for col in osm_out_cols:
            df[f"osm.{col}"] = None

        unmatched_mask = _still_unmatched(df)
        if unmatched_mask.any():
            logger.info(
                f"[{zone_name}] OpenInfra fallback for {unmatched_mask.sum()} unmatched units..."
            )
            country_code = self._country_to_iso2(self.country)
            if country_code:
                if self.df_openinfra.empty:
                    self.df_openinfra = query_osm_country_plants(
                        country_code,
                        cache_dir=self.input_dir,
                        force_update=self.osm_update,
                        live=self.osm_live,
                    )

                if not self.df_openinfra.empty:
                    # Populate _enriched_names from wcode data so OpenInfra matching
                    # benefits from official names instead of raw ENTSO-E unit codes.
                    for _, row in df[unmatched_mask].iterrows():
                        raw_name = str(row.get(pp_name_col, "") or "")
                        if not raw_name:
                            continue
                        alt_names: list[str] = []
                        for name_src in (
                            "wcode.EicLongName",
                            "wcode.EicDisplayName",
                            "wcode.parent.EicLongName",
                        ):
                            n = row.get(name_src)
                            if (
                                pd.notna(n)
                                and str(n).strip()
                                and str(n).strip() != raw_name
                            ):
                                alt_names.append(str(n).strip())
                        if alt_names:
                            self._enriched_names[raw_name] = alt_names

                    # Build a temporary DataFrame with the column names that
                    # _match_with_openinfra expects (self.name_col, self.fuel_col, lat, lon).
                    df_osm_input = df[unmatched_mask][[pp_name_col]].copy()
                    df_osm_input = df_osm_input.rename(
                        columns={pp_name_col: self.name_col}
                    )
                    if self.fuel_col:
                        df_osm_input[self.fuel_col] = df[unmatched_mask][
                            "pp.fuel_type"
                        ].values
                    df_osm_input["lat"] = None
                    df_osm_input["lon"] = None

                    df_osm_result = self._match_with_openinfra(df_osm_input)
                    osm_matched = df_osm_result[df_osm_result["lat"].notna()]

                    for _, osm_row in osm_matched.iterrows():
                        name_val = osm_row[self.name_col]
                        target_idx = df.index[df[pp_name_col] == name_val]
                        if len(target_idx) == 0:
                            continue
                        i = target_idx[0]
                        df.at[i, "osm.lat"] = osm_row.get("lat")
                        df.at[i, "osm.lon"] = osm_row.get("lon")
                        df.at[i, "osm.id"] = osm_row.get("osm_id")
                        df.at[i, "osm.type"] = osm_row.get("osm_type")
                        df.at[i, "osm.url"] = osm_row.get("osm_url")
                        df.at[i, "osm.geometry"] = osm_row.get("osm_geometry")

            osm_matched_count = df["osm.lat"].notna().sum()
            logger.info(
                f"[{zone_name}] OpenInfra fallback: {osm_matched_count} additional units matched."
            )

        # ------------------------------------------------------------------ #
        # 10. Sibling-unit fallback: reuse a co-located unit's coordinates   #
        # ------------------------------------------------------------------ #
        # Some units have no usable name of their own (e.g. an extra generator
        # block added later) but share the same physical plant — identified via
        # the EicParent code — with another unit that was already matched by any
        # of the previous steps. Rather than re-guessing a name for OSM/PPM/GEM
        # matching, simply inherit that sibling's coordinates.
        df["sibling.lat"] = None
        df["sibling.lon"] = None
        df["sibling.match_source"] = None

        interim_lat = (
            df["ppm.lat"].combine_first(df["gem.lat"]).combine_first(df["osm.lat"])
        )
        interim_lon = (
            df["ppm.lon"].combine_first(df["gem.lon"]).combine_first(df["osm.lon"])
        )

        def _clean_str_series(series: pd.Series) -> pd.Series:
            return series.map(
                lambda v: str(v).strip() if pd.notna(v) and str(v).strip() else None
            )

        # 1. Prefer the officially declared parent EIC (wcode.EicParent).
        eic_parent = _clean_str_series(df["wcode.EicParent"])

        # 2. Fall back to the fuzzy-resolved parent EIC (wcode.parent.EicCode) —
        # but ONLY when it actually differs from the unit's own EIC code. When
        # the EIC directory has no distinct "Production Unit" entry for a plant,
        # find_parent_production_unit() falls back to matching a unit against
        # itself (self-reference), which must not be treated as a shared key.
        own_eic = _clean_str_series(df[pp_code_col]) if pp_code_col in df else None
        parent_eic_resolved = _clean_str_series(df["wcode.parent.EicCode"])
        distinct_parent_eic = pd.Series(
            [
                p if p is not None and (own_eic is None or p != o) else None
                for p, o in zip(
                    parent_eic_resolved,
                    own_eic if own_eic is not None else [None] * len(df),
                )
            ],
            index=df.index,
        )

        # 3. Group by the plant "base name" derived from the official EIC long
        # name with its trailing unit-suffix token stripped (e.g. "Balti G09" /
        # "Balti G10" / "Balti G11" -> "balti"). This reliably identifies units
        # of the same physical plant even when no distinct parent EIC entry
        # exists at all (e.g. Balti/Eesti in Estonia), and copes with
        # inconsistent EicDisplayName formatting (e.g. "BEJ_G09" vs "BEJG10").
        def _plant_base_key(long_name: str | None) -> str | None:
            normalized = self._normalize_name(long_name)
            if not normalized:
                return None
            tokens = normalized.split()
            if len(tokens) > 1 and re.fullmatch(r"[a-z]{1,4}\d+", tokens[-1]):
                tokens = tokens[:-1]
            base = " ".join(tokens).strip()
            return base or None

        long_name_key = df["wcode.EicLongName"].map(_plant_base_key)
        long_name_key = long_name_key.map(lambda k: f"long_name:{k}" if k else None)

        # 4. Last resort: group by the shared alphabetic prefix of the official
        # EIC display name (e.g. "BEJ_G09"/"BEJ_G11" -> "BEJ").
        display_prefix = df["wcode.EicDisplayName"].map(
            lambda v: _alpha_prefix(v) if pd.notna(v) else ""
        )
        display_prefix = display_prefix.map(
            lambda p: f"display_prefix:{p}" if len(p) >= 3 else None
        )

        plant_group_key = (
            eic_parent.combine_first(distinct_parent_eic)
            .combine_first(long_name_key)
            .combine_first(display_prefix)
        )

        has_group_key = plant_group_key.notna()
        already_matched = interim_lat.notna()

        sibling_lookup = (
            pd.DataFrame(
                {
                    "_key": plant_group_key[already_matched & has_group_key],
                    "_lat": interim_lat[already_matched & has_group_key],
                    "_lon": interim_lon[already_matched & has_group_key],
                    "_name": df.loc[already_matched & has_group_key, pp_name_col],
                }
            )
            .dropna(subset=["_key"])
            .drop_duplicates(subset=["_key"])
            .set_index("_key")
        )

        needs_sibling = ~already_matched & has_group_key
        for idx in df.index[needs_sibling]:
            key = plant_group_key.at[idx]
            if key in sibling_lookup.index:
                sib = sibling_lookup.loc[key]
                df.at[idx, "sibling.lat"] = sib["_lat"]
                df.at[idx, "sibling.lon"] = sib["_lon"]
                df.at[idx, "sibling.match_source"] = f"sibling_of:{sib['_name']}"

        sibling_matched_count = df["sibling.lat"].notna().sum()
        logger.info(
            f"[{zone_name}] Sibling-unit fallback: {sibling_matched_count} additional "
            f"units matched via a co-located sibling unit."
        )

        # ------------------------------------------------------------------ #
        # 11. Finalise lat / lon, match_source, and write output CSV         #
        # ------------------------------------------------------------------ #
        df["lat"] = interim_lat.combine_first(df["sibling.lat"])
        df["lon"] = interim_lon.combine_first(df["sibling.lon"])

        osm_derived_source = df.apply(
            lambda r: (
                "osm"
                if pd.notna(r.get("osm.lat"))
                else "sibling_unit"
                if pd.notna(r.get("sibling.lat"))
                else "unmatched"
            ),
            axis=1,
        )
        df["match_source"] = (
            df["ppm.match_source"]
            .combine_first(df["gem.match_source"])
            .combine_first(osm_derived_source)
        )

        total_matched = df["lat"].notna().sum()
        logger.info(
            f"[{zone_name}] Enrichment complete: {total_matched}/{len(df)} units with coordinates. "
            f"Sources: {df['match_source'].value_counts().to_dict()}"
        )

        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.output_dir / f"enriched_units_{zone_name}.csv"
            df.to_csv(out_path, index=False)
            logger.info(f"[{zone_name}] Enriched units written to '{out_path}'.")

        return df

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
                self.df_openinfra = query_osm_country_plants(
                    country_code,
                    cache_dir=self.input_dir,
                    force_update=self.osm_update,
                    live=self.osm_live,
                )

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
                    self._normalize_name(n), self._plant_name_expansions
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
                v for v in self._plant_name_expansions.values() if len(v.split()) == 1
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
                    source_tag = "eic_long_name" if idx == 0 else "eic_display_name"
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
                        raw_norm, self._plant_name_expansions
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
    def _is_fueltype_compatible(eg_type: str | None, pp_type: str | None) -> bool:
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
    def _classify_fueltype_match(eg_type: str | None, pp_type: str | None) -> str:
        """Classify the fuel-type agreement between an energy-generation record and PPM.

        Args:
            eg_type: Canonical fuel type from the energy production data (e.g. ``"wind"``).
            pp_type: Fuel type string from powerplantmatching (e.g. ``"Wind"``).

        Returns:
            ``"exact"``      — both normalize to the same label.
            ``"compatible"`` — one contains the other, or one side is missing.
            ``"mismatch"``   — clearly different fuel types.
        """
        eg = CoordinateLocator._normalize_fueltype_label(eg_type)
        pp = CoordinateLocator._normalize_fueltype_label(pp_type)
        if not eg or not pp:
            return "compatible"
        if eg == pp:
            return "exact"
        if eg in pp or pp in eg:
            return "compatible"
        return "mismatch"

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

    @classmethod
    def _strip_trailing_unit_suffix(cls, value: str | None) -> str:
        """Strip a trailing unit-suffix glued directly onto the plant name.

        Some ENTSO-E naming conventions concatenate the unit suffix directly onto
        the plant name with no separating space/underscore (e.g.
        ``"ENGURIUNIT_5"`` -> ``"enguri"``), which the space-tokenized
        :meth:`_strip_numeric_name_tokens` cannot catch since "enguriunit" and "5"
        would otherwise remain a single glued token.

        Returns:
            str: The name with the trailing unit-suffix removed, or ``""`` if the
                name doesn't end in a recognized unit-suffix (no fallback needed).
        """
        normalized = cls._normalize_name(value)
        if not normalized:
            return ""

        unit_words = "|".join(token for token in GENERIC_UNIT_TOKENS if len(token) > 1)
        stripped = re.sub(rf"(?:{unit_words})\s*\d*$", "", normalized).strip()
        return stripped if stripped and stripped != normalized else ""

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


def _collect_zone_dirs(
    input_paths: Path | str | list[Path | str],
) -> list[Path]:
    """Resolve one or more input paths into a flat, sorted list of zone directories.

    Three input shapes are accepted:

    - **Single zone folder** — a directory that directly contains the CSV data
      files (no subdirectories).  Treated as one zone.
    - **Container folder** — a directory whose immediate children are zone
      directories.  All subdirectories are collected as individual zones.
    - **List** — any mix of the two shapes above.  Each element is resolved
      independently and the results are concatenated.

    Args:
        input_paths: A single ``Path`` / ``str``, or a list thereof.

    Returns:
        list[Path]: Deduplicated, sorted list of resolved zone directories.
    """
    if isinstance(input_paths, (str, Path)):
        candidates = [Path(input_paths)]
    else:
        candidates = [Path(p) for p in input_paths]

    zone_dirs: list[Path] = []
    for path in candidates:
        if not path.is_dir():
            logger.warning(f"'{path}' is not a directory — skipping.")
            continue
        subdirs = sorted(p for p in path.iterdir() if p.is_dir())
        if subdirs:
            # path is a container → collect its immediate subdirectories
            zone_dirs.extend(subdirs)
        else:
            # path is a leaf zone directory
            zone_dirs.append(path)

    # deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in zone_dirs:
        resolved = d.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(d)
    return unique


if "__main__" == __name__:
    import argparse

    parser = argparse.ArgumentParser(
        description="Find coordinates for power plants and render an interactive map."
    )
    parser.add_argument(
        "--update",
        "-u",
        action="store_true",
        help=(
            "Re-fetch OSM power plant data from Overpass and overwrite the local "
            "overpass_<CC>_plants.parquet file, even if it already exists."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Query the Overpass API live on every run. "
            "The local OSM file is neither read nor written."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("../testdata/coordinates/"),
        help="Directory where enriched_units_<zone>.csv files are written.",
    )
    parser.add_argument(
        "--gem-dir",
        type=Path,
        default=Path("../testdata/coordinates/gem-data"),
        help=(
            "Directory containing manually downloaded Global Energy Monitor (GEM) "
            "tracker xlsx files (https://globalenergymonitor.org/download-data). "
            "When given, GEM is used as an additional coordinate source alongside "
            "powerplantmatching in the ENTSOE enrichment pipeline. Pass an empty "
            "string or a non-existent path to disable GEM matching."
        ),
    )
    args = parser.parse_args()
    gem_dir = args.gem_dir if args.gem_dir and args.gem_dir.is_dir() else None
    if args.gem_dir and gem_dir is None:
        logger.warning(
            f"--gem-dir '{args.gem_dir}' is not a directory — GEM matching disabled."
        )

    # --- configure input here: pick ONE of the three forms ---
    #
    # 1) Container folder — every subdirectory becomes one zone:
    # input_paths: Path | str | list[Path | str] = Path("../testdata/energy/entsoe/1h/")
    #
    # 2) Single zone folder:
    # input_paths = Path("../testdata/energy/entsoe/1h/10Y1001A1001A39I/")

    #
    # 3) Explicit list of zone folders (mix of single zones and containers allowed):
    input_paths: Path | str | list[Path | str] = [
        Path("../testdata/energy/entsoe/1h/10Y1001A1001A39I/"),
        Path("../testdata/energy/entsoe/1h/10Y1001A1001A990/"),
        Path("../testdata/energy/entsoe/1h/10Y1001A1001B012/"),
        Path("../testdata/energy/entsoe/1h/10Y1001C--00100H/"),
        Path("../testdata/energy/entsoe/1h/10YAL-KESH-----5/"),
        Path("../testdata/energy/entsoe/1h/10YAT-APG------L/"),
        Path("../testdata/energy/entsoe/1h/10YBA-JPCC-----D/"),
        Path("../testdata/energy/entsoe/1h/10YBE----------2/"),
        Path("../testdata/energy/entsoe/1h/10YCA-BULGARIA-R/"),
        Path("../testdata/energy/entsoe/1h/10YCH-SWISSGRIDZ/"),
        Path("../testdata/energy/entsoe/1h/10YCS-CG-TSO---S/"),
        Path("../testdata/energy/entsoe/1h/10YCS-SERBIATSOV/"),
        Path("../testdata/energy/entsoe/1h/10YDE-ENBW-----N/"),
        Path("../testdata/energy/entsoe/1h/10YDE-EON------1/"),
        Path("../testdata/energy/entsoe/1h/10YDE-RWENET---I/"),
        Path("../testdata/energy/entsoe/1h/10YDE-VE-------2/"),
        Path("../testdata/energy/entsoe/1h/10YFI-1--------U/"),
        Path("../testdata/energy/entsoe/1h/10YGR-HTSO-----Y/"),
        Path("../testdata/energy/entsoe/1h/10YLV-1001A00074/"),
        Path("../testdata/energy/entsoe/1h/10YMK-MEPSO----8/"),
        Path("../testdata/energy/entsoe/1h/10YNL----------L/"),
        Path("../testdata/energy/entsoe/1h/10YPT-REN------W/"),
        Path("../testdata/energy/entsoe/1h/10YSE-1--------K/"),
        Path("../testdata/energy/entsoe/1h/10YSK-SEPS-----K/"),
    ]

    zone_dirs = _collect_zone_dirs(input_paths)
    dataframes: list[pd.DataFrame] = []
    labels: list[str] = []

    for zone_dir in zone_dirs:
        folder_name = zone_dir.name
        label = folder_name[3:5]  # e.g. "10YLV-1001A00074" → "LV"
        try:
            cl = CoordinateLocator(
                input_dir=zone_dir,
                output_dir=args.output,
                osm_update=args.update,
                osm_live=args.live,
                gem_dir=gem_dir,
            )
            df = cl.find_coordinates_using_pp_databases()
            if df is not None and not df.empty:
                dataframes.append(df)
                labels.append(label)
                logger.info(
                    f"[{label}] {folder_name}: "
                    f"{df['lat'].notna().sum()}/{len(df)} matched."
                )
        except Exception as e:
            logger.warning(f"[{label}] {folder_name}: skipped — {e}")

    if dataframes:
        # build_map works best with a name column; for ENTSOE the name col is prefixed
        map_dfs = []
        for df_map in dataframes:
            # Provide a flat 'Name' column for the map if not already present
            name_col_long = OPERATOR_METADATA["entsoe"]["entity_col"]
            if f"pp.{name_col_long}" in df_map.columns and "Name" not in df_map.columns:
                df_map = df_map.copy()
                df_map["Name"] = df_map[f"pp.{name_col_long}"]
            map_dfs.append(df_map)
        build_map(map_dfs, labels=labels)
    else:
        logger.warning("No results found for the given input paths.")
