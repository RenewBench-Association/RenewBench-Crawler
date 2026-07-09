"""Coordinate location orchestration.

Orchestrates coordinate finding for power-generation units via a declarative,
per-operator pipeline (see :attr:`CoordinateLocator.PIPELINES`): ENTSO-E uses
its own EIC-code-driven pipeline, every other operator uses the "standard"
pipeline (load & dedupe -> fuzzy match against GEM/OSM -> fuel-type
validation -> sibling-unit fallback -> finalize) unless a future operator
defines its own.
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd
from loguru import logger

from rbc.coordinates.locator_eic import (
    EICDirectoryLocator,
    _alpha_prefix,
)
from rbc.coordinates.locator_gem import GEMLocator
from rbc.coordinates.locator_osm_api import query_osm_country_plants
from rbc.coordinates.locator_ppm import PPMLocator
from rbc.coordinates.map import build_map
from rbc.coordinates.mappings import COUNTRY_ISO2_MAP, OPERATOR_METADATA
from rbc.coordinates.matcher import NameMatrixMatcher
from rbc.coordinates.tokenizer import base_name_key
from rbc.energy.entsoe.mappings import (
    ACTIVE_ZONES_METADATA,
    FUELTYPE_CODE_MAPPINGS,
    FUELTYPE_MAPPINGS,
)
from rbc.energy.utils import MissingDataError, load_df_from_file


class CoordinateLocator:
    """Coordinate locator orchestrator."""

    # Ordered step-method-name lists, one per named pipeline. Looked up via
    # OPERATOR_METADATA[operator].get("pipeline", "standard") in
    # run_pipeline(). Only entsoe deviates from "standard" today; a future
    # operator with genuinely bespoke needs gets its own entry here rather
    # than a new hardcoded orchestration method.
    PIPELINES: dict[str, list[str]] = {
        "entsoe": [
            "_step_load_and_dedupe",
            "_step_map_fuel_type",
            "_step_entsoe_eic_lookup",
            "_step_entsoe_match_by_id",
            "_step_entsoe_resolve_parent_unit",
            "_step_entsoe_match_by_parent_id",
            "_step_fuzzy_match",
            "_step_validate_fueltype",
            "_step_sibling_fallback_eic",
            "_step_finalize",
        ],
        "standard": [
            "_step_load_and_dedupe",
            "_step_map_fuel_type",
            "_step_fuzzy_match",
            "_step_validate_fueltype",
            "_step_sibling_fallback_name",
            "_step_finalize",
        ],
    }

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        osm_update: bool = False,
        osm_live: bool = False,
        gem_dir: Path | None = None,
        ppmloc: PPMLocator | None = None,
        eic_locator: EICDirectoryLocator | None = None,
        gemloc: GEMLocator | None = None,
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
                (PPM, entsoe pipeline only) in the fuzzy name-matching step. Defaults
                to None (GEM disabled). Ignored when *gemloc* is given directly.
            ppmloc (PPMLocator, optional): Pre-built PPM locator to reuse (e.g. across
                multiple zones in a single run) instead of constructing a new one,
                which re-downloads the pan-European PPM CSV. Defaults to None (a new
                instance is created).
            eic_locator (EICDirectoryLocator, optional): Pre-built EIC directory
                locator to reuse. Defaults to None, in which case a new instance is
                only constructed if the resolved pipeline is "entsoe" -- the entsoe
                pipeline is the only one that uses EIC codes, so other operators
                don't pay for the W_eicCodes.csv fetch at all. An explicitly-passed
                instance is always honored regardless of pipeline.
            gemloc (GEMLocator, optional): Pre-built GEM locator to reuse. Defaults to
                None, in which case a new instance is created from *gem_dir* (or GEM
                stays disabled if *gem_dir* is also None).
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.osm_update = osm_update
        self.osm_live = osm_live
        if not self.input_dir.is_dir():
            raise ValueError(f"Input directory '{input_dir}' is not a directory!")

        self.df_openinfra = pd.DataFrame()
        # Locators are expensive to construct (network/CSV/parquet reads), so
        # callers processing multiple zones in one run should build them once and
        # pass them in here to be shared, rather than paying that cost per zone.
        self.ppmloc = ppmloc if ppmloc is not None else PPMLocator()  # Europe only
        if gemloc is not None:
            self.gemloc: GEMLocator | None = gemloc
        else:
            self.gemloc = (
                GEMLocator(gem_dir=gem_dir, cache_dir=self.output_dir)
                if gem_dir
                else None
            )  # optional, requires manual download

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

        except IndexError:
            raise ValueError(f"No country match found for '{self.input_dir}'!")

        except KeyError as e:
            raise ValueError(
                f"No country match found in Europe for '{self.input_dir}': {e}"
            )

        except MissingDataError as e:
            raise e

        self._pipeline_name = OPERATOR_METADATA[self.operator].get(
            "pipeline", "standard"
        )
        if eic_locator is not None:
            self.eic_locator: EICDirectoryLocator | None = eic_locator
        elif self._pipeline_name == "entsoe":
            self.eic_locator = EICDirectoryLocator(cache_dir=self.output_dir)
        else:
            self.eic_locator = None

        logger.info(
            f"CoordinateLocator initalized for: {self.operator} ({self.country})"
        )

    def run_pipeline(self) -> pd.DataFrame:
        """Run this operator's configured pipeline end-to-end.

        Looks up ``OPERATOR_METADATA[self.operator]["pipeline"]`` (defaults to
        ``"standard"``) and executes the corresponding ordered step list from
        :attr:`PIPELINES`, threading one DataFrame through each step in turn.

        Returns:
            pd.DataFrame: Enriched dataframe, one row per unique generation unit.
        """
        if self._pipeline_name not in self.PIPELINES:
            raise ValueError(
                f"Unknown pipeline '{self._pipeline_name}' for operator "
                f"'{self.operator}'."
            )
        df = pd.DataFrame()
        for step_name in self.PIPELINES[self._pipeline_name]:
            df = getattr(self, step_name)(df)
            if step_name == "_step_load_and_dedupe" and len(df) == 0:
                # Preserves the original monolithic method's exact
                # short-circuit behavior when input_dir has no CSVs, rather
                # than letting an empty df flow harmlessly through every
                # remaining step (which pandas would tolerate, but with
                # extra cosmetic log lines that don't exist today).
                break
        return df

    # ------------------------------------------------------------------ #
    # Small string-formatting properties shared across steps             #
    # ------------------------------------------------------------------ #
    @property
    def _zone_name(self) -> str:
        return self.input_dir.name

    @property
    def _pp_name_col(self) -> str:
        return f"pp.{self.name_col}"

    @property
    def _pp_code_col(self) -> str | None:
        return f"pp.{self.code_col}" if self.code_col else None

    def _still_unmatched(self, df: pd.DataFrame) -> pd.Series:
        return df["ppm.lat"].isna() & df["gem.lat"].isna()

    # ------------------------------------------------------------------ #
    # Shared steps (both pipelines)                                      #
    # ------------------------------------------------------------------ #
    def _step_load_and_dedupe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load raw CSVs, dedupe to one row per unique generation unit.

        Dedupes on code_col when the operator has one (ENTSO-E, eia); falls
        back to name_col otherwise (all other operators, which have no
        unique per-row code today).
        """
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
        dedupe_subset = [self.code_col] if self.code_col else [self.name_col]
        df_unique = (
            df_all[rel_cols]
            .drop_duplicates(subset=dedupe_subset)
            .reset_index(drop=True)
        )

        logger.info(
            f"[{self._zone_name}] {len(df_unique)} unique generation units found "
            f"across {len(all_dfs)} CSV(s)."
        )
        return df_unique

    def _step_map_fuel_type(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename production columns with the pp. prefix, add pp.fuel_type."""
        rename_map = {c: f"pp.{c}" for c in df.columns}
        df = df.rename(columns=rename_map)

        pp_fuel_col = f"pp.{self.fuel_col}" if self.fuel_col else None
        df["pp.fuel_type"] = None
        if pp_fuel_col and pp_fuel_col in df.columns:
            df["pp.fuel_type"] = df[pp_fuel_col].map(
                lambda x: (
                    FUELTYPE_CODE_MAPPINGS.get(str(x).strip()) if pd.notna(x) else None
                )
            )
        return df

    def _ensure_osm_loaded(self, country_code: str | None) -> None:
        if country_code and len(self.df_openinfra) == 0:
            self.df_openinfra = query_osm_country_plants(
                country_code,
                cache_dir=self.input_dir,
                force_update=self.osm_update,
                live=self.osm_live,
            )

    def _ensure_exact_match_columns(self, df: pd.DataFrame) -> None:
        """Ensure ppm.*/gem.* lat/lon/match_source columns exist (in place).

        The entsoe pipeline's exact-ID steps normally create these first;
        the standard pipeline has no exact-ID stage at all, so anything
        that reads these columns (_still_unmatched, _add_eic_alt_names,
        _fuzzy_match_core, _interim_coords, ...) would otherwise KeyError
        the first time it runs. No-op once the columns already exist.
        """
        for col in (
            "ppm.lat",
            "ppm.lon",
            "ppm.match_source",
            "gem.lat",
            "gem.lon",
            "gem.match_source",
        ):
            if col not in df.columns:
                df[col] = None

    def _fuzzy_match_core(
        self,
        df: pd.DataFrame,
        matcher: NameMatrixMatcher,
        name_candidates_fn,
    ) -> pd.DataFrame:
        """Shared per-row fuzzy-match loop, used by both pipelines.

        Args:
            df: Working dataframe. Caller must have already called
                _ensure_exact_match_columns(df).
            matcher: A NameMatrixMatcher already wired to whichever
                locators this pipeline uses.
            name_candidates_fn: Callable(row) -> ordered list of name
                strings to try against the matcher, most-authoritative first.
        """
        self._ensure_exact_match_columns(df)  # defensive; no-op if already done
        matcher.build_matrix()

        for idx, row in df[self._still_unmatched(df)].iterrows():
            eg_fuel = row.get("pp.fuel_type")

            for name_candidate in name_candidates_fn(row):
                if pd.isna(name_candidate) or not str(name_candidate).strip():
                    continue

                result = matcher.match(
                    target_name=str(name_candidate).strip(),
                    fuel_type=eg_fuel,
                    threshold=75,  # Lower threshold to catch more matches with enhanced fuzzy matching
                )

                if result.matched and result.candidate:
                    candidate = result.candidate

                    if candidate.source == "ppm":
                        df.at[idx, "ppm.lat"] = candidate.lat
                        df.at[idx, "ppm.lon"] = candidate.lon
                        df.at[idx, "ppm.Name"] = candidate.name
                        df.at[idx, "ppm.Fueltype"] = candidate.fueltype
                        df.at[idx, "ppm.Country"] = candidate.country
                        df.at[idx, "ppm.match_source"] = "ppm_fuzzy_matrix"

                    elif candidate.source == "gem" and self.gemloc:
                        df.at[idx, "gem.lat"] = candidate.lat
                        df.at[idx, "gem.lon"] = candidate.lon
                        df.at[idx, "gem.plant_name"] = candidate.name
                        df.at[idx, "gem.Fueltype"] = candidate.fueltype
                        df.at[idx, "gem.Country"] = candidate.country
                        df.at[idx, "gem.match_source"] = "gem_fuzzy_matrix"

                    elif candidate.source == "osm":
                        df.at[idx, "osm.lat"] = candidate.lat
                        df.at[idx, "osm.lon"] = candidate.lon
                        df.at[idx, "osm.id"] = candidate.source_id
                        df.at[idx, "osm.type"] = None
                        df.at[idx, "osm.url"] = None
                        df.at[idx, "osm.geometry"] = None
                        df.at[idx, "osm.Fueltype"] = candidate.fueltype

                    break

        # Initialize OSM columns if they don't exist
        for col in ["lat", "lon", "id", "type", "url", "geometry"]:
            if f"osm.{col}" not in df.columns:
                df[f"osm.{col}"] = None

        ppm_final = df["ppm.lat"].notna().sum()
        gem_final = df["gem.lat"].notna().sum()
        osm_final = df["osm.lat"].notna().sum()
        logger.info(
            f"[{self._zone_name}] NameMatrixMatcher: "
            f"{ppm_final} via PPM total, {gem_final} via GEM total, "
            f"{osm_final} via OSM."
        )
        return df

    def _step_validate_fueltype(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fuel-type validation for all matched units (from any source)."""
        df["fuel_type_match"] = None
        df["fuel_type_match_level"] = None
        matched_mask = (
            df["ppm.lat"].notna() | df["gem.lat"].notna() | df["osm.lat"].notna()
        )
        for idx, row in df[matched_mask].iterrows():
            matched_fueltype = None
            if pd.notna(row.get("ppm.lat")):
                matched_fueltype = row.get("ppm.Fueltype")
            elif pd.notna(row.get("gem.lat")):
                matched_fueltype = row.get("gem.Fueltype")
            elif pd.notna(row.get("osm.lat")):
                matched_fueltype = row.get("osm.Fueltype")

            level = self._classify_fueltype_match(
                row.get("pp.fuel_type"), matched_fueltype
            )
            df.at[idx, "fuel_type_match"] = level != "mismatch"
            df.at[idx, "fuel_type_match_level"] = level

        mismatches = (df["fuel_type_match_level"] == "mismatch").sum()
        if mismatches:
            logger.warning(
                f"[{self._zone_name}] Fuel-type mismatch on {mismatches} matched "
                f"unit(s) — verify these rows manually."
            )
        return df

    def _interim_coords(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Best-so-far lat/lon from exact-ID + fuzzy matches, before sibling fallback."""
        lat = df["ppm.lat"].combine_first(df["gem.lat"]).combine_first(df["osm.lat"])
        lon = df["ppm.lon"].combine_first(df["gem.lon"]).combine_first(df["osm.lon"])
        return lat, lon

    @staticmethod
    def _clean_str_series(series: pd.Series) -> pd.Series:
        return series.map(
            lambda v: str(v).strip() if pd.notna(v) and str(v).strip() else None
        )

    def _sibling_fallback_core(
        self, df: pd.DataFrame, plant_group_key: pd.Series
    ) -> pd.DataFrame:
        """Shared sibling-unit fallback machinery, given an already-derived group key.

        Some units have no usable name of their own (e.g. an extra generator
        block added later) but share the same physical plant as another unit
        that was already matched by any of the previous steps. Rather than
        re-guessing a name for OSM/PPM/GEM matching, simply inherit
        that sibling's coordinates.
        """
        df["sibling.lat"] = None
        df["sibling.lon"] = None
        df["sibling.match_source"] = None

        interim_lat, interim_lon = self._interim_coords(df)

        has_group_key = plant_group_key.notna()
        already_matched = interim_lat.notna()

        sibling_lookup = (
            pd.DataFrame(
                {
                    "_key": plant_group_key[already_matched & has_group_key],
                    "_lat": interim_lat[already_matched & has_group_key],
                    "_lon": interim_lon[already_matched & has_group_key],
                    "_name": df.loc[already_matched & has_group_key, self._pp_name_col],
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
            f"[{self._zone_name}] Sibling-unit fallback: {sibling_matched_count} "
            f"additional units matched via a co-located sibling unit."
        )
        return df

    def _step_finalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Finalise lat/lon, match_source, and write the output CSV."""
        interim_lat, interim_lon = self._interim_coords(df)
        df["lat"] = interim_lat.combine_first(df["sibling.lat"])
        df["lon"] = interim_lon.combine_first(df["sibling.lon"])

        def _derived_source_row(r: pd.Series) -> str:
            if pd.notna(r.get("osm.lat")):
                return "osm"
            if pd.notna(r.get("sibling.lat")):
                return "sibling_unit"
            return "unmatched"

        derived_source = df.apply(_derived_source_row, axis=1)
        df["match_source"] = (
            df["ppm.match_source"]
            .combine_first(df["gem.match_source"])
            .combine_first(derived_source)
        )

        total_matched = df["lat"].notna().sum()
        logger.info(
            f"[{self._zone_name}] Enrichment complete: {total_matched}/{len(df)} units "
            f"with coordinates. Sources: {df['match_source'].value_counts().to_dict()}"
        )

        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.output_dir / f"enriched_units_{self._zone_name}.csv"
            df.to_csv(out_path, index=False)
            logger.info(f"[{self._zone_name}] Enriched units written to '{out_path}'.")

        return df

    # ------------------------------------------------------------------ #
    # ENTSO-E-only steps                                                  #
    # ------------------------------------------------------------------ #
    def _step_entsoe_eic_lookup(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enrich with W_eicCodes.csv -> wcode.* columns."""
        assert self.eic_locator is not None
        wcode_fields = list(self.eic_locator._WCODE_FIELDS)
        for col in wcode_fields:
            df[f"wcode.{col}"] = None

        for idx, row in df.iterrows():
            eic = row.get(self._pp_code_col)
            if pd.isna(eic) or not str(eic).strip():
                continue
            full_row = self.eic_locator.lookup_full_row(str(eic).strip())
            for col in wcode_fields:
                df.at[idx, f"wcode.{col}"] = full_row.get(col)

        wcode_populated = df["wcode.EicLongName"].notna().sum()
        logger.info(
            f"[{self._zone_name}] W_eicCodes enrichment: {wcode_populated}/{len(df)} "
            f"units found in EIC directory."
        )
        return df

    def _step_entsoe_match_by_id(self, df: pd.DataFrame) -> pd.DataFrame:
        """GEM/PPM direct match by unit EIC code or wcode.EicParent."""
        ppm_cols = list(self.ppmloc._PPM_COLS)
        for col in ppm_cols:
            df[f"ppm.{col}"] = None
        df["ppm.match_source"] = None

        gem_cols = list(GEMLocator._GEM_COLS)
        for col in gem_cols:
            df[f"gem.{col}"] = None
        df["gem.match_source"] = None

        for idx, row in df[self._still_unmatched(df)].iterrows():
            eic = row.get(self._pp_code_col)
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
            f"[{self._zone_name}] Direct/EicParent match: {gem_direct_count} via GEM, "
            f"{ppm_direct_count} via PPM (out of {len(df)})."
        )
        return df

    def _step_entsoe_resolve_parent_unit(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fuzzy parent-unit matching within W_eicCodes -> wcode.parent.* columns."""
        assert self.eic_locator is not None
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

        for idx, row in df[self._still_unmatched(df)].iterrows():
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
            f"[{self._zone_name}] Fuzzy parent matching: {parent_found} parent "
            f"production units resolved."
        )
        return df

    def _step_entsoe_match_by_parent_id(self, df: pd.DataFrame) -> pd.DataFrame:
        """GEM/PPM match via resolved parent EIC code.

        Only trust "high" confidence parent resolutions (direct EicParent
        lookup, or a fuzzy match scoring >= 90) for this direct/unguarded EIC
        code lookup. "medium" confidence guesses (e.g. a display-name-prefix
        match built on a short, generic plant-type abbreviation) are too easy
        to get wrong across countries and must go through fuzzy name + fuel
        validation instead, where a fuel-type mismatch can veto them.
        """
        gem_cols = list(GEMLocator._GEM_COLS)
        ppm_cols = list(self.ppmloc._PPM_COLS)
        for idx, row in df[self._still_unmatched(df)].iterrows():
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
            f"[{self._zone_name}] Match via parent EIC: {gem_after_parent} via GEM "
            f"total, {ppm_after_parent} via PPM total "
            f"({ppm_after_parent + gem_after_parent} total)."
        )
        return df

    def _add_eic_alt_names(self, df: pd.DataFrame, matcher: NameMatrixMatcher) -> None:
        for _, row in df[self._still_unmatched(df)].iterrows():
            raw_name = str(row.get(self._pp_name_col, "") or "")
            if not raw_name:
                continue
            alt_names: list[str] = []
            for name_src in (
                "wcode.EicLongName",
                "wcode.EicDisplayName",
                "wcode.parent.EicLongName",
            ):
                n = row.get(name_src)
                if pd.notna(n) and str(n).strip() and str(n).strip() != raw_name:
                    alt_names.append(str(n).strip())
            if alt_names:
                matcher.add_alternative_names(raw_name, alt_names)

    def _step_fuzzy_match(self, df: pd.DataFrame) -> pd.DataFrame:
        """NameMatrixMatcher: unified fuzzy name matching, shared by both pipelines.

        PPM (powerplantmatching) is Europe-only data, so it's only wired in
        for the entsoe pipeline. GEM and the live OSM Overpass source are
        used by both. The EIC-derived alternative names / wcode.* candidate
        columns are entsoe-only (populated by the earlier _step_entsoe_*
        steps) -- for the standard pipeline they simply don't exist, and
        row.get() on a missing column returns None safely, so this same
        logic falls straight through to the raw pp.<name_col> candidate
        without any special-casing needed here.
        """
        self._ensure_exact_match_columns(df)
        country_code = self._country_to_iso2(self.country)
        self._ensure_osm_loaded(country_code)

        matcher = NameMatrixMatcher(
            country=self.country,
            country_code=country_code,
            ppm_locator=self.ppmloc if self._pipeline_name == "entsoe" else None,
            gem_locator=self.gemloc,
            osm_df=self.df_openinfra if len(self.df_openinfra) > 0 else None,
        )
        self._add_eic_alt_names(df, matcher)

        return self._fuzzy_match_core(
            df,
            matcher,
            lambda row: [
                row.get("wcode.EicLongName"),
                row.get("wcode.parent.EicLongName"),
                row.get(self._pp_name_col),
            ],
        )

    def _derive_plant_group_key_eic(self, df: pd.DataFrame) -> pd.Series:
        """4-tier EIC-based sibling-unit grouping key (entsoe only)."""
        eic_parent = self._clean_str_series(df["wcode.EicParent"])

        # Fall back to the fuzzy-resolved parent EIC (wcode.parent.EicCode) —
        # but ONLY when it actually differs from the unit's own EIC code. When
        # the EIC directory has no distinct "Production Unit" entry for a
        # plant, find_parent_production_unit() falls back to matching a unit
        # against itself (self-reference), which must not be treated as a
        # shared key.
        pp_code_col = self._pp_code_col
        own_eic = (
            self._clean_str_series(df[pp_code_col])
            if pp_code_col and pp_code_col in df
            else None
        )
        parent_eic_resolved = self._clean_str_series(df["wcode.parent.EicCode"])
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

        # Group by the plant "base name" derived from the official EIC long
        # name with its trailing unit-suffix token stripped (e.g. "Balti G09"
        # / "Balti G10" / "Balti G11" -> "balti"). This reliably identifies
        # units of the same physical plant even when no distinct parent EIC
        # entry exists at all (e.g. Balti/Eesti in Estonia), and copes with
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

        # Last resort: group by the shared alphabetic prefix of the official
        # EIC display name (e.g. "BEJ_G09"/"BEJ_G11" -> "BEJ").
        display_prefix = df["wcode.EicDisplayName"].map(
            lambda v: _alpha_prefix(v) if pd.notna(v) else ""
        )
        display_prefix = display_prefix.map(
            lambda p: f"display_prefix:{p}" if len(p) >= 3 else None
        )

        return (
            eic_parent.combine_first(distinct_parent_eic)
            .combine_first(long_name_key)
            .combine_first(display_prefix)
        )

    def _step_sibling_fallback_eic(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._sibling_fallback_core(df, self._derive_plant_group_key_eic(df))

    # ------------------------------------------------------------------ #
    # Standard-pipeline-only steps                                       #
    # ------------------------------------------------------------------ #
    def _derive_plant_group_key_name(self, df: pd.DataFrame) -> pd.Series:
        """Name-based sibling-unit grouping key for operators with no EIC data.

        Reduces each unit's name to its discriminative tokens via
        rbc.coordinates.tokenizer.base_name_key, so e.g. "Plant X Unit 1" and
        "Plant X Unit 2" group together. Known, accepted limitation (same
        class of risk as the EIC-based display_prefix tier): two genuinely
        different plants that reduce to the same base name will incorrectly
        group -- there is no unique per-plant ID to fall back on for sources
        without EIC/wcode data.
        """
        country_code = self._country_to_iso2(self.country)

        def _key(name: object) -> str | None:
            if pd.isna(name) or not str(name).strip():
                return None
            base = base_name_key(str(name).strip(), country_code)
            return f"name_base:{base}" if base else None

        return df[self._pp_name_col].map(_key)

    def _step_sibling_fallback_name(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._sibling_fallback_core(df, self._derive_plant_group_key_name(df))

    # ------------------------------------------------------------------ #
    # Static/class helper methods                                        #
    # ------------------------------------------------------------------ #
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

    @staticmethod
    def _country_to_iso2(country: str | None) -> str | None:
        """Map country name aliases used in datasets to ISO-2 country code."""
        if not country:
            return None
        return COUNTRY_ISO2_MAP.get(str(country).strip().lower(), None)


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
    input_paths: Path | str | list[Path | str] = Path("../testdata/energy/entsoe/1h/")
    #
    # 2) Single zone folder:
    # input_paths = Path("../testdata/energy/entsoe/1h/10YCH-SWISSGRIDZ/")

    #
    # 3) Explicit list of zone folders (mix of single zones and containers allowed):
    # input_paths: Path | str | list[Path | str] = [
    # Path("../testdata/energy/entsoe/1h/10Y1001A1001A39I/"),
    # Path("../testdata/energy/entsoe/1h/10Y1001A1001A990/"),
    # Path("../testdata/energy/entsoe/1h/10Y1001A1001B012/"),
    # Path("../testdata/energy/entsoe/1h/10Y1001C--00100H/"),
    # Path("../testdata/energy/entsoe/1h/10YAL-KESH-----5/"),
    # Path("../testdata/energy/entsoe/1h/10YAT-APG------L/"),
    # Path("../testdata/energy/entsoe/1h/10YBA-JPCC-----D/"),
    # Path("../testdata/energy/entsoe/1h/10YBE----------2/"),
    # Path("../testdata/energy/entsoe/1h/10YCA-BULGARIA-R/"),
    # Path("../testdata/energy/entsoe/1h/10YCH-SWISSGRIDZ/"),
    # Path("../testdata/energy/entsoe/1h/10YCS-CG-TSO---S/"),
    # Path("../testdata/energy/entsoe/1h/10YCS-SERBIATSOV/"),
    # Path("../testdata/energy/entsoe/1h/10YDE-ENBW-----N/"),
    # Path("../testdata/energy/entsoe/1h/10YDE-EON------1/"),
    # Path("../testdata/energy/entsoe/1h/10YDE-RWENET---I/"),
    # Path("../testdata/energy/entsoe/1h/10YDE-VE-------2/"),
    # Path("../testdata/energy/entsoe/1h/10YFI-1--------U/"),
    # Path("../testdata/energy/entsoe/1h/10YGR-HTSO-----Y/"),
    # Path("../testdata/energy/entsoe/1h/10YLV-1001A00074/"),
    # Path("../testdata/energy/entsoe/1h/10YMK-MEPSO----8/"),
    # Path("../testdata/energy/entsoe/1h/10YNL----------L/"),
    # Path("../testdata/energy/entsoe/1h/10YPT-REN------W/"),
    # Path("../testdata/energy/entsoe/1h/10YSE-1--------K/"),
    # Path("../testdata/energy/entsoe/1h/10YSK-SEPS-----K/"),
    # ]

    zone_dirs = _collect_zone_dirs(input_paths)
    dataframes: list[pd.DataFrame] = []
    labels: list[str] = []

    # Build the (expensive: network/CSV/parquet-backed) reference-data locators
    # ONCE and share them across all zones below. Previously a fresh set was
    # constructed per zone_dir, meaning the pan-European PPM CSV was re-downloaded
    # and the GEM/EIC directories were re-parsed once per zone — very wasteful for
    # multi-zone runs (e.g. several German TSO zones all sharing the same data).
    shared_ppmloc = PPMLocator()
    shared_eic_locator = EICDirectoryLocator(cache_dir=args.output)
    shared_gemloc = (
        GEMLocator(gem_dir=gem_dir, cache_dir=args.output) if gem_dir else None
    )

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
                ppmloc=shared_ppmloc,
                eic_locator=shared_eic_locator,
                gemloc=shared_gemloc,
            )
            df = cl.run_pipeline()
            # Use explicit check to avoid pandas NA boolean ambiguity
            if df is not None and len(df) > 0:
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
