import re
from pathlib import Path

import pandas as pd
from loguru import logger

from rbc.coordinates.locator_eic import EICDirectoryLocator, _alpha_prefix
from rbc.coordinates.locator_gem import GEMLocator
from rbc.coordinates.locator_ppm import PPMLocator
from rbc.coordinates.pipelines._base import BasePipeline
from rbc.coordinates.tokenizer import normalize_name


class EntsoePipeline(BasePipeline):
    """Entsoe location/coordinate finding pipeline."""

    STEPS: list[str] = [
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
    ]

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        gemloc: GEMLocator | None = None,
        ppmloc: PPMLocator | None = None,
        eicloc: EICDirectoryLocator | None = None,
        osm_update: bool = False,
        osm_live: bool = False,
    ) -> None:
        """Initializes the child class for the Entsoe pipeline.

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. Defaults to None.
            gemloc (GEMLocator, optional): Pre-built GEM locator to reuse. Defaults to
                None, in which case GEM is disabled.
            ppmloc (PPMLocator, optional): Pre-built PPM locator to reuse the pan-European
                PPM CSV or global OSMPP CSV. Defaults to None, in which case a new locator
                is built.
            eicloc (EICDirectoryLocator, optional): Pre-built EIC directory
                locator to reuse. Defaults to None, in which case a new instance is
                only constructed if the resolved pipeline is "entsoe" -- the entsoe
                pipeline is the only one that uses EIC codes, so other operators
                don't pay for the W_eicCodes.csv fetch at all. An explicitly-passed
                instance is always honored regardless of pipeline.
            osm_update (bool): Re-fetch OSM data from Overpass and overwrite the local
                ``overpass_..._plants.parquet`` file even if it already exists.
                Corresponds to the ``--update`` / ``-u`` CLI flag.
            osm_live (bool): Query Overpass live on every run, ignoring and not writing
                any local file.  Corresponds to the ``--live`` CLI flag.
        """
        super().__init__(
            input_dir=input_dir,
            output_dir=output_dir,
            gemloc=gemloc,
            ppmloc=ppmloc,
            osm_update=osm_update,
            osm_live=osm_live,
        )

        self.eicloc: EICDirectoryLocator | None = (
            eicloc
            if eicloc is not None
            else (EICDirectoryLocator(cache_dir=self.output_dir))
        )
        if self.ppmloc is None:
            self.ppmloc = PPMLocator()

    # ------------------------------------------------------------------
    # PIPELINE STEPS (for EntsoePipeline only)
    # ------------------------------------------------------------------
    def _step_entsoe_eic_lookup(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enrich data using the 'W_eicCodes.csv' (specifically the wcode.* columns).

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with enriched data).
        """
        assert self.eicloc is not None
        wcode_fields = list(self.eicloc._WCODE_FIELDS)
        for col in wcode_fields:
            df[f"wcode.{col}"] = None

        for idx, row in df.iterrows():
            eic = row.get(self.sysop_code_col)
            if pd.isna(eic) or not str(eic).strip():
                continue
            full_row = self.eicloc.lookup_full_row(str(eic).strip())
            for col in wcode_fields:
                df.at[idx, f"wcode.{col}"] = full_row.get(col)

        wcode_populated = df["wcode.EicLongName"].notna().sum()
        logger.info(
            f"[{self.input_dir.name}] W_eicCodes enrichment: {wcode_populated}/{len(df)} "
            f"units found in EIC directory."
        )
        return df

    def _step_entsoe_match_by_id(self, df: pd.DataFrame) -> pd.DataFrame:
        """Find matches by directly comparing EGE EIC codes / wcode.EicParent to GEM / PPM.

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated dataframe (now with direct EIC code matches).
        """
        assert self.ppmloc is not None

        ppm_cols = list(self.ppmloc._PPM_COLS)
        for col in ppm_cols:
            df[f"ppm.{col}"] = None
        df["ppm.match_source"] = None

        gem_cols = list(GEMLocator._GEM_COLS)
        for col in gem_cols:
            df[f"gem.{col}"] = None
        df["gem.match_source"] = None

        for idx, row in df[self._still_unmatched(df)].iterrows():
            eic = row.get(self.sysop_code_col)
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
            f"[{self.input_dir.name}] Direct/EicParent match: {gem_direct_count} via GEM, "
            f"{ppm_direct_count} via PPM (out of {len(df)})."
        )
        return df

    def _step_entsoe_resolve_parent_unit(self, df: pd.DataFrame) -> pd.DataFrame:
        """Find parent-units through fuzzy matching within W_eicCodes ('wcode.parent.*' cols).

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated dataframe (now with parent units identified).
        """
        assert self.eicloc is not None
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
            parent = self.eicloc.find_parent_production_unit(
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
            f"[{self.input_dir.name}] Fuzzy parent matching: {parent_found} parent "
            f"production units resolved."
        )
        return df

    def _step_entsoe_match_by_parent_id(self, df: pd.DataFrame) -> pd.DataFrame:
        """Find matches by comparing EGE's resolved parent EIC code with GEM / PPM.

        Only trust "high" confidence parent resolutions (direct EicParent lookup or a fuzzy
        match scoring >= 90) for this direct EIC code lookup. "medium" confidence guesses
        (e.g. a display-name-prefix match built on a short, generic plant-type abbreviation)
        are too easy to get wrong across countries and must go through fuzzy name + fuel
        validation instead, where a fuel-type mismatch can veto them.

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated dataframe (now with parent EIC code matches).
        """
        assert self.ppmloc is not None

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
            f"[{self.input_dir.name}] Match via parent EIC: {gem_after_parent} via GEM "
            f"total, {ppm_after_parent} via PPM total "
            f"({ppm_after_parent + gem_after_parent} total)."
        )
        return df

    def _step_sibling_fallback_eic(self, df: pd.DataFrame) -> pd.DataFrame:
        """FALLBACK STEP --- Use EIC code matching of siblings as fallback option.

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with sibling EIC matches).
        """
        return self._sibling_fallback_core(df, self._derive_plant_group_key_eic(df))

    def _derive_plant_group_key_eic(self, df: pd.DataFrame) -> pd.Series:
        """Find 4-tier EIC-based sibling-unit grouping key.

        Fall back to the fuzzy-resolved parent EIC (wcode.parent.EicCode) ONLY when it differs
        from the unit's own EIC code. When the EIC directory has no associated distinct
        "Production Unit" entry find_parent_production_unit() falls back to matching a unit
        against itself (self-reference), which must not be treated as a shared key.
        As a last resort, group by the shared alphabetic prefix of the official EIC display
        name (e.g. "BEJ_G09"/"BEJ_G11" -> "BEJ").

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            pd.Series: Combined series of fallback options.
        """
        eic_parent = self._clean_str_series(df["wcode.EicParent"])

        # OPTION 1: use fuzzy-resolved parent EIC code
        sysop_code_col = self.sysop_code_col
        own_eic = (
            self._clean_str_series(df[sysop_code_col])
            if sysop_code_col and sysop_code_col in df
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

        # OPTION 2: use EGE's own extractable long name key
        def _plant_base_key(long_name: str | None) -> str | None:
            """Derive the base key from the official EIC long name with suffix stripped.

            Example: "Balti G09" / "Balti G10" / "Balti G11" -> "balti"

            Args:
                long_name (str | None): The official EIC long name.

            Returns:
                str | None: The base key if it can be found, otherwise None.
            """
            normalized = normalize_name(long_name)
            if not normalized:
                return None

            tokens = normalized.split()
            if len(tokens) > 1 and re.fullmatch(r"[a-z]{1,4}\d+", tokens[-1]):
                tokens = tokens[:-1]
            base = " ".join(tokens).strip()
            return base or None

        long_name_key = df["wcode.EicLongName"].map(_plant_base_key)
        long_name_key = long_name_key.map(lambda k: f"long_name:{k}" if k else None)

        # OPTION 3: group by the shared alphabetic prefix of the official EIC display name
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
