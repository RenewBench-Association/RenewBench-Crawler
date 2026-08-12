"""ENTSOE location/coordinate finding pipeline."""

import re
from pathlib import Path

import pandas as pd
from loguru import logger

import rbc.coordinates.locators.eic_registry as eic
from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.matcher import NameMatrixMatcher
from rbc.coordinates.pipelines._base import BasePipeline
from rbc.coordinates.utils.tokenizer import normalize_name

# Constants for WCODE-related column headers
WCODE_PREFIX = "wcode"
WCODE_PARENT_PREFIX = f"{WCODE_PREFIX}.parent"

WCODE_PARENT = f"{WCODE_PREFIX}.{eic.PARENT_COL}"  # "wcode.EicParent"
WCODE_LONGNAME = f"{WCODE_PREFIX}.{eic.LONGNAME_COL}"
WCODE_DISPLAYNAME = f"{WCODE_PREFIX}.{eic.DISPLAYNAME_COL}"
WCODE_PARTY = f"{WCODE_PREFIX}.{eic.PARTY_COL}"
WCODE_PARENT_EIC = f"{WCODE_PARENT_PREFIX}.{eic.CODE_COL}"  # "wcode.parent.EicCode"
WCODE_PARENT_LONGNAME = f"{WCODE_PARENT_PREFIX}.{eic.LONGNAME_COL}"


class EntsoePipeline(BasePipeline):
    """Entsoe location/coordinate finding pipeline."""

    STEPS: list[str] = [
        "_step_entsoe_eic_lookup",
        "_step_entsoe_match_by_id",
        "_step_entsoe_resolve_parent_unit",
        "_step_entsoe_match_by_parent_id",
        "_step_fuzzy_match",
        "_step_validate_fueltype",
        "_step_sibling_fallback_eic",
    ]

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        gem_loc: GEMLocator | None = None,
        ppm_loc: PPMLocator | None = None,
        eic_reg: EICCodeRegistry | None = None,
        osm_update: bool = False,
        osm_live: bool = False,
    ) -> None:
        """Initializes the child class for the Entsoe pipeline.

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. Defaults to None.
            gem_loc (GEMLocator, optional): Pre-built GEM locator to reuse. Defaults to
                None, in which case GEM is disabled.
            ppm_loc (PPMLocator, optional): Pre-built PPM locator to reuse the pan-European
                PPM CSV or global OSMPP CSV. Defaults to None, in which case a new locator
                is built.
            eic_reg (EICCodeRegistry, optional): Pre-built EIC directory registry to reuse
                and fetch the W_eicCodes.csv. Defaults to None, in which case a new
                instance is constructed.
            osm_update (bool): Re-fetch OSM data from Overpass and overwrite the local
                ``overpass_..._plants.parquet`` file even if it already exists.
                Corresponds to the ``--update`` / ``-u`` CLI flag.
            osm_live (bool): Query Overpass live on every run, ignoring and not writing
                any local file.  Corresponds to the ``--live`` CLI flag.
        """
        super().__init__(
            input_dir=input_dir,
            output_dir=output_dir,
            gem_loc=gem_loc,
            ppdb_loc=ppm_loc,
            osm_update=osm_update,
            osm_live=osm_live,
        )

        self.eic_reg: EICCodeRegistry | None = (
            eic_reg
            if eic_reg is not None
            else EICCodeRegistry(cache_dir=self.output_dir)
        )
        self.ppdb_loc: PPMLocator = (  # type: ignore[assignment]
            self.ppdb_loc if self.ppdb_loc is not None else PPMLocator()
        )

    # ------------------------------------------------------------------
    # PIPELINE STEPS (for EntsoePipeline only)
    # ------------------------------------------------------------------
    def _step_entsoe_eic_lookup(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enrich data using the 'W_eicCodes.csv' (specifically the ``wcode.*`` columns).

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with enriched data).
        """
        assert self.eic_reg is not None
        wcode_fields = list(self.eic_reg.WCODE_FIELDS)
        for col in wcode_fields:
            df[f"{WCODE_PREFIX}.{col}"] = None

        for idx, row in df.iterrows():
            eic = row.get(self.sysop_code_col)
            if pd.isna(eic) or not str(eic).strip():
                continue
            full_row = self.eic_reg.lookup_full_row(str(eic).strip())
            for col in wcode_fields:
                df.at[idx, f"{WCODE_PREFIX}.{col}"] = full_row.get(col)

        wcode_populated = df[WCODE_LONGNAME].notna().sum()
        logger.info(
            f"[{self.input_dir.name}] W_eicCodes enrichment: {wcode_populated}/{len(df)} "
            f"units found in EIC directory."
        )
        return df

    def _step_entsoe_match_by_id(self, df: pd.DataFrame) -> pd.DataFrame:
        """Find matches by directly comparing EGE EIC codes/``wcode.EicParent`` to GEM/PPM.

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated dataframe (now with direct EIC code matches).
        """
        assert self.ppdb_loc is not None

        ppdb_cols = list(self.ppdb_loc.PPM_COLS)
        for col in ppdb_cols:
            df[f"ppdb.{col}"] = None
        df["ppdb.match_source"] = None

        gem_cols = list(GEMLocator.GEM_COLS)
        for col in gem_cols:
            df[f"gem.{col}"] = None
        df["gem.match_source"] = None

        for idx, row in df[self._still_unmatched(df)].iterrows():
            eic = row.get(self.sysop_code_col)
            parent_eic = row.get(WCODE_PARENT)
            hit, source = None, None

            # 1. GEM: try the unit (generation) EIC directly
            if self.gem_loc and pd.notna(eic) and str(eic).strip():
                hit = self.gem_loc.match_by_entsoe_id(str(eic).strip())
                source = "gem_direct"

            # 2. GEM: try the parent (production) EIC from wcode.EicParent
            if (
                hit is None
                and self.gem_loc
                and pd.notna(parent_eic)
                and str(parent_eic).strip()
            ):
                hit = self.gem_loc.match_by_entsoe_id(str(parent_eic).strip())
                source = "gem_parent_direct"

            # 3. ppdb (PPM) fallback: unit EIC directly
            if hit is None and pd.notna(eic) and str(eic).strip():
                hit = self.ppdb_loc.match_by_entsoe_id(str(eic).strip())
                source = "ppdb_direct"

            # 4. ppdb (PPM) fallback: parent EIC from wcode.EicParent
            if hit is None and pd.notna(parent_eic) and str(parent_eic).strip():
                hit = self.ppdb_loc.match_by_entsoe_id(str(parent_eic).strip())
                source = "ppdb_parent_direct"

            if hit is not None:
                if source is not None and source.startswith("gem"):
                    for col in gem_cols:
                        df.at[idx, f"gem.{col}"] = hit.get(col)
                    df.at[idx, "gem.match_source"] = source
                else:
                    for col in ppdb_cols:
                        df.at[idx, f"ppdb.{col}"] = hit.get(col)
                    df.at[idx, "ppdb.match_source"] = source

        ppdb_direct_count = df["ppdb.lat"].notna().sum()
        gem_direct_count = df["gem.lat"].notna().sum()
        logger.info(
            f"[{self.input_dir.name}] Direct/EicParent match: {gem_direct_count} via GEM, "
            f"{ppdb_direct_count} via ppdb (PPM) (out of {len(df)})."
        )
        return df

    def _step_entsoe_resolve_parent_unit(self, df: pd.DataFrame) -> pd.DataFrame:
        """Find parent-units through fuzzy matching within W_eicCodes ('wcode.parent.*' cols).

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated dataframe (now with parent units identified).
        """
        assert self.eic_reg is not None

        for col in self.eic_reg.MATCH_FIELDS:
            df[f"{WCODE_PARENT_PREFIX}.{col}"] = None

        for idx, row in df[self._still_unmatched(df)].iterrows():
            parent = self.eic_reg.find_parent_production_unit(
                parent=row.get(WCODE_PARENT)
                if pd.notna(row.get(WCODE_PARENT))
                else None,
                display_name=row.get(WCODE_DISPLAYNAME)
                if pd.notna(row.get(WCODE_DISPLAYNAME))
                else None,
                long_name=row.get(WCODE_LONGNAME)
                if pd.notna(row.get(WCODE_LONGNAME))
                else None,
                responsible_party=row.get(WCODE_PARTY)
                if pd.notna(row.get(WCODE_PARTY))
                else None,
            )
            if parent is not None:
                for col in self.eic_reg.MATCH_FIELDS:
                    df.at[idx, f"{WCODE_PARENT_PREFIX}.{col}"] = parent.get(col)

        parent_found = df[WCODE_PARENT_EIC].notna().sum()
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
        assert self.ppdb_loc is not None

        gem_cols = list(GEMLocator.GEM_COLS)
        ppdb_cols = list(self.ppdb_loc.PPM_COLS)
        for idx, row in df[self._still_unmatched(df)].iterrows():
            parent_eic = row.get(WCODE_PARENT_EIC)
            if pd.isna(parent_eic) or not str(parent_eic).strip():
                continue
            if row.get(f"{WCODE_PARENT_PREFIX}.match_confidence") != "high":
                continue
            parent_eic_str = str(parent_eic).strip()

            hit = (
                self.gem_loc.match_by_entsoe_id(parent_eic_str)
                if self.gem_loc
                else None
            )
            if hit is not None:
                for col in gem_cols:
                    df.at[idx, f"gem.{col}"] = hit.get(col)
                df.at[idx, "gem.match_source"] = "gem_parent_entsoe_id"
            else:
                hit = self.ppdb_loc.match_by_entsoe_id(parent_eic_str)
                if hit is not None:
                    for col in ppdb_cols:
                        df.at[idx, f"ppdb.{col}"] = hit.get(col)
                    df.at[idx, "ppdb.match_source"] = "ppdb_parent_entsoe_id"

        ppdb_after_parent = df["ppdb.lat"].notna().sum()
        gem_after_parent = df["gem.lat"].notna().sum()
        logger.info(
            f"[{self.input_dir.name}] Match via parent EIC: {gem_after_parent} via GEM "
            f"total, {ppdb_after_parent} via ppdb (PPM) total "
            f"({ppdb_after_parent + gem_after_parent} total)."
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
        eic_parent = df[WCODE_PARENT].map(eic.safe_str)

        # OPTION 1: use fuzzy-resolved parent EIC code
        sysop_code_col = self.sysop_code_col  # define to prevent recall of property
        own_eic = (
            df[sysop_code_col].map(eic.safe_str)
            if sysop_code_col and sysop_code_col in df
            else None
        )
        parent_eic_resolved = df[WCODE_PARENT_EIC].map(eic.safe_str)
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

        long_name_key = df[WCODE_LONGNAME].map(_plant_base_key)
        long_name_key = long_name_key.map(lambda k: f"long_name:{k}" if k else None)

        # OPTION 3: group by the shared alphabetic prefix of the official EIC display name
        display_prefix = df[WCODE_DISPLAYNAME].map(
            lambda v: eic.extract_prefix(v) if pd.notna(v) else ""
        )
        display_prefix = display_prefix.map(
            lambda p: f"display_prefix:{p}" if len(p) >= 3 else None
        )

        return (
            eic_parent.combine_first(distinct_parent_eic)
            .combine_first(long_name_key)
            .combine_first(display_prefix)
        )

    # ------------------------------------------------------------------
    # HELPERS (overwrite BasePipeline methods for EntsoePipeline use)
    # ------------------------------------------------------------------
    def _add_alt_names(self, df: pd.DataFrame, matcher: NameMatrixMatcher) -> None:
        """Add alternative EGE names based on EICRegistry to matcher.

        Args:
            df (pd.DataFrame): Df
            matcher (NameMatrixMatcher): NameMatrixMatcher instance.
        """
        for _, row in df[self._still_unmatched(df)].iterrows():
            raw_name = str(row.get(self.sysop_name_col, "") or "")
            if not raw_name:
                continue

            alt_names: list[str] = []
            for name_src in (WCODE_LONGNAME, WCODE_DISPLAYNAME, WCODE_PARENT_LONGNAME):
                n = row.get(name_src)
                if pd.notna(n) and str(n).strip() and str(n).strip() != raw_name:
                    alt_names.append(str(n).strip())

            if alt_names:
                matcher.add_alternative_names(raw_name, alt_names)

    def _name_candidates(self, row: pd.Series) -> list[str | None]:
        """Define EGE candidate names to try against matcher. Overwritable by child pipeline.

        Args:
            row (pd.Series): The row to try against.

        Returns:
            list[str]: List of EGE candidate names to try against the matcher.
        """
        return [
            row.get(WCODE_LONGNAME),
            row.get(WCODE_PARENT_LONGNAME),
            row.get(self.sysop_name_col),
        ]
