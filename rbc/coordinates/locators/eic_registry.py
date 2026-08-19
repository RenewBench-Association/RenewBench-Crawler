"""Information update for ENTSO-E EGEs using the public EIC code registry.

Provides official display-name lookup by EIC code using ENTSO-E's public EIC code
registry (no API key required). The result is used to replace generic unit names
such as "Unit 10" with their official plant name before downstream fuzzy matching
against OSM/OpenInfra.
"""

from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path

import pandas as pd
from loguru import logger
from rapidfuzz import fuzz, process

from rbc.coordinates.utils.values import strip_str
from rbc.energy.utils import RETRY_ERRORS, InvalidError, load_df_from_file

EIC_DIRECTORY_URL = (
    "https://eepublicdownloads.blob.core.windows.net/cio-lio/csv/W_eicCodes.csv"
)

# Column names in the W-type EIC CSV (semicolon-delimited, stable as of 2026)
CODE_COL = "EicCode"
DISPLAYNAME_COL = "EicDisplayName"
LONGNAME_COL = "EicLongName"
PARENT_COL = "EicParent"
PARTY_COL = "EicResponsibleParty"
STATUS_COL = "EicStatus"
TYPE_COL = "EicTypeFunctionList"

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    CODE_COL: ("eiccode", "eic_code", "eic code", "eic", "code"),
    DISPLAYNAME_COL: ("eicdisplayname", "display_name", "displayname"),
    LONGNAME_COL: ("eiclongname", "long_name", "longname"),
}

# Constants for threshold / score values
MIN_MATCH_SCORE, HIGH_MATCH_SCORE = 80.0, 90.0
EXACT_PREFIX_SCORE, PARTIAL_PREFIX_SCORE = 95.0, 85.0
MIN_PREFIX_OVERLAP = 5
PARTY_BONUS = 5.0

# Match the leading alphabetic run ('PREFIX' of '<PREFIX>_<SUFFIX>') of an EIC display name
_ALPHA_PREFIX_PATTERN = re.compile(r"^[A-Za-z]+")


def extract_prefix(name: str | None) -> str:
    """Extract the leading alphabetic run of ``name`` string (e.g. 'MGRES' from 'MGRES_G4').

    Gets the 'PREFIX' in strings following the '<PREFIX>_<SUFFIX>' naming convention,
    where 'PREFIX' is shared between child generation and parent production EGEs.

    Args:
        name (str | None): Name string to be assessed.

    Returns:
        str: Upper-case leading alphabetic prefix of ``name`` or "" if no ``name``.
    """
    clean_name = strip_str(name)
    if clean_name is None:
        return ""
    match = _ALPHA_PREFIX_PATTERN.match(clean_name)
    return match.group(0).upper() if match else ""


class EICCodeRegistry:
    """Name-enrichment locator backed by ENTSO-E's public EIC code registry.

    Downloads the official EIC code publication on first use and optionally caches
    it locally.  Provides EIC code → official display name lookups so that generic
    ENTSO-E unit names (e.g. "Unit 10") can be replaced with their registered plant
    name before fuzzy-matching against OSM.

    Attributes:
        cache_dir (Path | None): Directory used for caching the downloaded registry.
        df (pd.DataFrame): Parsed EIC code registry. Has the columns:
            [
                'EicCode', 'EicDisplayName', 'EicLongName', 'EicParent',
                'EicResponsibleParty', 'EicStatus', 'MarketParticipantPostalCode',
                'MarketParticipantIsoCountryCode', 'MarketParticipantVatCode',
                'EicTypeFunctionList', 'type'
            ]
    """

    # Fields returned by lookup_full_row
    WCODE_FIELDS: tuple[str, ...] = (
        DISPLAYNAME_COL,
        LONGNAME_COL,
        PARENT_COL,
        PARTY_COL,
        STATUS_COL,
        TYPE_COL,
    )
    # Fields returned by find_parent_production_unit
    MATCH_FIELDS: tuple[str, ...] = (
        CODE_COL,
        *WCODE_FIELDS,
        "match_score",
        "match_confidence",
        "match_method",
    )

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize EICCodeRegistry.

        Args:
            cache_dir (Path, optional): Directory for caching the downloaded registry.
                Defaults to None, in which case no caching occurs.
        """
        self.cache_dir = cache_dir
        self.df: pd.DataFrame = pd.DataFrame()
        self._eic_index: dict[str, int] = {}

        # setup registry
        self._load()
        self._build_eic_index()

    # ------------------------------------------------------------------
    # Cached properties (calculated once and re-used)
    # ------------------------------------------------------------------
    @cached_property
    def _production_df(self) -> pd.DataFrame:
        """Get dataframe of EIC entries defined as being "Production Unit" EGEs.

        Returns:
            pd.DataFrame: Df of "Production Unit" EGEs or empty one, if no TYPE_COL exists.
        """
        if TYPE_COL not in self.df.columns:
            logger.warning(
                f"EICCodeRegistry: No {TYPE_COL} column exists, no production df!"
            )
            return pd.DataFrame()

        # log EicTypeFunctionList once so exact string can be confirmed in this CSV version
        distinct = sorted(self.df[TYPE_COL].dropna().unique().tolist())
        logger.debug(f"EICCodeRegistry: {TYPE_COL} values include:\n{distinct[:30]}")

        mask = self.df[TYPE_COL].str.contains(
            r"Production.?Unit|A26", na=False, regex=True, case=False
        )
        return self.df[mask].copy()

    @cached_property
    def _production_prefixes(self) -> pd.Series:
        """Get prefixes of EIC's "Production Unit" EGEs with ``<prefix>_<suffix>`` matching.

        Returns:
            pd.Series: List of prefixes of "Production Unit" EGEs.
        """
        return self._production_df[DISPLAYNAME_COL].apply(extract_prefix)

    @cached_property
    def _production_candidates(self) -> list[str]:
        """Build static candidate list of "Production Unit" EGE's long/display names once.

        Returns:
            list[str]: List of EGE candidates.
        """
        candidates: list[str] = []
        for col in (LONGNAME_COL, DISPLAYNAME_COL):
            if col in self._production_df.columns:
                candidates.extend(
                    self._production_df[col].dropna().str.strip().tolist()
                )
        seen: set[str] = set()
        unique_candidates: list[str] = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                unique_candidates.append(c)
        return unique_candidates

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Download and parse the ENTSO-E W-type EIC code CSV."""
        cache_path = (
            Path(self.cache_dir, "eic_directory.csv") if self.cache_dir else None
        )

        if cache_path and cache_path.exists():
            logger.info(f"EICCodeRegistry: loading from cache '{cache_path}'")
            self.df = load_df_from_file(cache_path, sep=";", dtype=str)
            self._check_columns()
            return

        try:
            logger.info("EICCodeRegistry: downloading ENTSO-E W-type EIC codes...")
            self.df = load_df_from_file(EIC_DIRECTORY_URL, sep=";", dtype=str)
            self._check_columns()

            if cache_path and not self.df.empty:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.df.to_csv(cache_path, sep=";", index=False)
                logger.info(f"EICCodeRegistry: cached to '{cache_path}'")

        except (*RETRY_ERRORS, InvalidError) as e:
            logger.warning(
                f"EICCodeRegistry: download failed ({e}). "
                "Name enrichment via EIC directory will be unavailable."
            )

    def _check_columns(self) -> None:
        """Ensure columns that hold relevant info exist; rename if they're not the default."""
        cols = self.df.columns
        cols_lower = {c.strip().lower(): c for c in cols}
        renames = {
            cols_lower[alias]: default
            for default, aliases in _COLUMN_ALIASES.items()
            if default not in cols
            for alias in aliases
            if alias in cols_lower
        }
        if renames:
            logger.info(
                f"EICCodeRegistry: Default column names not present; renaming required. "
                f"\nNormalized columns: {renames}"
            )
            self.df = self.df.rename(columns=renames)

        if CODE_COL not in self.df.columns:
            logger.warning(
                f"EICCodeRegistry: Could not identify required columns (EIC code and names)! "
                f"\nAvailable columns: {list(self.df.columns)}"
            )
            self.df = pd.DataFrame()

        logger.info(f"EICCodeRegistry initialized: {len(self.df)} entries")

    def _build_eic_index(self) -> None:
        """Pre-compute an index for EIC codes and their row positions once (for 30k+ rows)."""
        if self.df.empty:
            return

        index: dict[str, int] = {}
        for pos, code in enumerate(self.df[CODE_COL]):
            if clean_code := strip_str(code):
                index.setdefault(clean_code, pos)
        self._eic_index = index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def lookup_full_row(self, eic_code: str) -> dict[str, str | None]:
        """Return selected W_eicCodes fields for an EIC code as a flat dict.

        Args:
            eic_code (str): ENTSO-E EIC code to look up.

        Returns:
            dict: Select columns and values for a given EIC code, with columns as keys:
            ``EicDisplayName``, ``EicLongName``, ``EicParent``, ``EicResponsibleParty``,
            ``EicStatus``, ``EicTypeFunctionList``. Values are stripped strings or None.
        """
        clean_code = strip_str(eic_code)
        if self.df.empty or clean_code is None:
            return {}

        pos = self._eic_index.get(clean_code)
        if pos is None:
            return {}

        row = self.df.iloc[pos]
        result: dict[str, str | None] = {}
        for col in self.WCODE_FIELDS:
            if col in row.index:
                result[col] = strip_str(row[col])
            else:
                result[col] = None
        return result

    def find_parent_production_unit(
        self,
        parent: str | None,
        display_name: str | None,
        long_name: str | None,
        responsible_party: str | None,
    ) -> dict[str, str | float | None] | None:
        """Find the matching parent production EGE in the EIC directory for a generation EGE.

        Use one of three strategies:
        1. Direct lookup (``match_method = "direct_parent"``):
            If `eic_parent` is not empty, look it up directly in the EIC and return that row.
        2. Display-name prefix match (``match_method = "display_prefix"``):
            Many EIC entries follow a ``"<PREFIX>_<SUFFIX>"`` naming convention where a
            generation EGE and parent production EGE share the same alphabetic prefix token
            (e.g. "MGRES_G4", "MGRES_PU"). Find cases where `eic_parent` is empty and the long
            names are too generic/dissimilar for the fuzzy fallback (3.) to reach the score.
        3. Fuzzy search (``match_method = "fuzzy"``):
            Filter the EIC to entries whose ``EicTypeFunctionList`` identifies them as a
            "Production Unit", then fuzzy-match the generation EGE's names against those.

        A +5-point bonus is applied to 2. and 3. when ``EicResponsibleParty`` also matches.
        Only accepted when the final score ≥ 80. Match confidence is "high" when ≥ 90.

        Args:
            parent (str | None): EicParent value from the generation EGE's own EIC row.
            display_name (str | None): EicDisplayName of the generation EGE.
            long_name (str | None): EicLongName of the generation EGE.
            responsible_party (str | None): EicResponsibleParty of the generation EGE;
                used as a matching bonus.

        Returns:
            dict | None: Details on the identified matching parent production EGE with keys
            ``EicCode``, ``EicDisplayName``, ``EicLongName``, ``EicParent``,
            `EicResponsibleParty``, ``EicStatus``, ``EicTypeFunctionList``,
            ``match_score``, ``match_confidence`` (high ≥ 90 / medium ≥ 80),
            ``match_method`` ("direct_parent" / "display_prefix" / "fuzzy")
            or None if no match was found.
        """
        if self.df.empty:
            return None

        # === Strategy 1: direct parent EIC lookup ===
        if (hit := self._match_direct_parent(parent)) is not None:
            return hit

        # --- Strategies 2 & 3: match against "Production Unit" entries ---
        # compute the static "Production Unit" EGE subset (and its derivations) once
        if self._production_df.empty:
            logger.warning("EICCodeRegistry: No 'Production Unit' EGEs in EIC!")
            return None

        # === Strategy 2: display-name prefix match (fast, high precision) ===
        if (
            hit := self._match_prefix(display_name, long_name, responsible_party)
        ) is not None:
            return hit

        # === Strategy 3: fuzzy match against "Production Unit" entries ===
        return self._match_fuzzy(display_name, long_name, responsible_party)

    # ------------------------------------------------------------------
    # Strategy & general helper methods
    # ------------------------------------------------------------------
    def _match_direct_parent(
        self, parent: str | None
    ) -> dict[str, str | float | None] | None:
        """Strategy 1: direct parent EIC lookup.

        Args:
            parent (str | None): EICParent value from the generation EGE's own EIC row.

        Returns:
            dict | None: Details on the matched EGE, if a parent exists and match was found.
        """
        parent_code = strip_str(parent)
        if parent_code is None:
            return None

        pos = self._eic_index.get(parent_code)
        if pos is None:
            return None

        return self._build_match_result(
            row=self.df.iloc[pos], score=100.0, method="direct_parent"
        )

    def _match_prefix(
        self, display_name: str | None, long_name: str | None, party: str | None
    ) -> dict[str, str | float | None] | None:
        """Strategy 2: display-name prefix match (fast, high precision).

        Args:
            display_name (str | None): EICDisplayName of the generation EGE.
            long_name (str | None): EICLongName of the generation EGE.
            party (str | None): EICResponsibleParty of the generation EGE.

        Returns:
            dict | None: Details on the matched EGE, if a match was found.
        """
        prefix_hit_row = None
        prefix_score = -1.0
        child_prefix = extract_prefix(display_name)
        if child_prefix and len(child_prefix) >= 3:
            prod_prefixes = self._production_prefixes
            exact_candidates = self._production_df[prod_prefixes == child_prefix]

            if len(exact_candidates) > 0:
                df_prefix_candidates = exact_candidates
                base_score = EXACT_PREFIX_SCORE
            else:
                # requires a reasonably long shared prefix to avoid false groupings
                # e.g. wrong match: "HPPENGURIUNIT" (GE) → "HPP_SESTRIMO" (BG) due to "HPP"
                contains_mask = prod_prefixes.apply(
                    lambda p: (
                        bool(p)
                        and min(len(p), len(child_prefix)) >= MIN_PREFIX_OVERLAP
                        and (p.startswith(child_prefix) or child_prefix.startswith(p))
                    )
                )
                df_prefix_candidates = self._production_df[contains_mask]
                base_score = PARTIAL_PREFIX_SCORE

            if len(df_prefix_candidates) == 1:
                prefix_hit_row = df_prefix_candidates.iloc[0]
                prefix_score = base_score

            elif len(df_prefix_candidates) > 1:
                # multiple candidates share prefix: find match in subset with long-name fuzzy
                best_sub_score = -1.0
                for _, cand_row in df_prefix_candidates.iterrows():
                    cand_long = cand_row.get(LONGNAME_COL)
                    sub_score = (
                        fuzz.token_set_ratio(long_name, cand_long)
                        if long_name and strip_str(cand_long)
                        else 0.0
                    )
                    if sub_score > best_sub_score:
                        best_sub_score = sub_score
                        prefix_hit_row = cand_row
                prefix_score = min(base_score, MIN_MATCH_SCORE + best_sub_score * 0.15)
                logger.debug(
                    f"EICCodeRegistry: {len(df_prefix_candidates)} production units share "
                    f"display-name prefix '{child_prefix}' — picked best long-name match."
                )

        if prefix_hit_row is None:
            return None

        return self._build_match_result(
            row=prefix_hit_row, score=prefix_score, method="display_prefix", party=party
        )

    def _match_fuzzy(
        self, display_name: str | None, long_name: str | None, party: str | None
    ) -> dict[str, str | float | None] | None:
        """Strategy 3: fuzzy match against "Production Unit" entries.

        Args:
            display_name (str | None): EICDisplayName of the generation EGE.
            long_name (str | None): EICLongName of the generation EGE.
            party (str | None): EICResponsibleParty of the generation EGE.

        Returns:
            dict | None: Details on the matched EGE, if a match was found.
        """
        # Build the static candidate name list from production EGE long/display names once
        unique_candidates = self._production_candidates
        if not unique_candidates:
            return None

        # Build query names from the generation EGE (prefer LongName)
        unit_names = [n for n in map(strip_str, (long_name, display_name)) if n]
        if not unit_names:
            return None

        best_score = -1.0
        best_match_name: str | None = None
        for unit_name in unit_names:
            hit = process.extractOne(
                unit_name, unique_candidates, scorer=fuzz.token_set_ratio
            )
            if hit and float(hit[1]) > best_score:
                best_score = float(hit[1])
                best_match_name = str(hit[0])

        if best_match_name is None:
            return None

        # Locate the matching row in self._production_df
        hit_row = None
        for col in (LONGNAME_COL, DISPLAYNAME_COL):
            if col in self._production_df.columns:
                matches = self._production_df[
                    self._production_df[col].str.strip() == best_match_name
                ]
                if len(matches) > 0:
                    hit_row = matches.iloc[0]
                    break

        if hit_row is None:
            return None

        return self._build_match_result(
            row=hit_row, score=best_score, method="fuzzy", party=party
        )

    @staticmethod
    def _build_match_result(
        row: pd.Series, score: float, method: str, party: str | None = None
    ) -> dict[str, str | float | None] | None:
        """Build the match result dict to be returned by ``find_parent_production_unit``.

        Args:
            row (pandas.Series): Matched production EGE data row.
            score (float): Matching score achieved by the row.
            method (str): Method by which the match was found (e.g. "direct_parent").
            party (str | None): EicResponsibleParty of the generation EGE;
                used as a matching bonus. Defaults to None, when no bonus is applied.

        Returns:
            dict[str, str | float | None] | None: Dictionary of match result details
                or None if score is lower than threshold.
        """
        if party and strip_str(row.get(PARTY_COL)) == strip_str(party):
            score = min(100.0, score + PARTY_BONUS)

        if score < MIN_MATCH_SCORE:
            return None

        return {
            CODE_COL: strip_str(row[CODE_COL]),  # keep direct; should not fail quietly!
            DISPLAYNAME_COL: strip_str(row.get(DISPLAYNAME_COL)),
            LONGNAME_COL: strip_str(row.get(LONGNAME_COL)),
            PARENT_COL: strip_str(row.get(PARENT_COL)),
            PARTY_COL: strip_str(row.get(PARTY_COL)),
            STATUS_COL: strip_str(row.get(STATUS_COL)),
            TYPE_COL: strip_str(row.get(TYPE_COL)),
            "match_score": score,
            "match_confidence": "high" if score >= HIGH_MATCH_SCORE else "medium",
            "match_method": method,
        }
