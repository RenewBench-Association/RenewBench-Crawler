"""Information update for ENTSO-E EGEs using the public EIC code registry.

Provides official display-name lookup by EIC code using ENTSO-E's public EIC code
registry (no API key required). The result is used to replace generic unit names
such as "Unit 10" with their official plant name before downstream fuzzy matching
against OSM/OpenInfra.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import requests
from loguru import logger
from rapidfuzz import fuzz, process

EIC_DIRECTORY_URL = (
    "https://eepublicdownloads.blob.core.windows.net/cio-lio/csv/W_eicCodes.csv"
)
HEADER = {
    "User-Agent": (
        "RenewBench-Crawler/1.0 "
        "(+https://github.com/RenewBench-Association/RenewBench-Crawler)"
    )
}

# Column names in the W-type EIC CSV (semicolon-delimited, stable as of 2026)
EIC_COL = "EicCode"
DISPLAY_NAME_COL = "EicDisplayName"
LONG_NAME_COL = "EicLongName"
PARENT_COL = "EicParent"
PARTY_COL = "EicResponsibleParty"
STATUS_COL = "EicStatus"
TYPE_COL = "EicTypeFunctionList"

# Constants for threshold / score values
MIN_MATCH_SCORE, HIGH_MATCH_SCORE = 80.0, 90.0
EXACT_PREFIX_SCORE, PARTIAL_PREFIX_SCORE = 95.0, 85.0
MIN_PREFIX_OVERLAP = 5
PARTY_BONUS = 5.0

# Match the leading alphabetic run ('BASE' of '<BASE>_<suffix>') of an EIC display name
_ALPHA_PREFIX_PATTERN = re.compile(r"^[A-Za-z]+")


def alpha_prefix(name: str | None) -> str:
    """Extract the leading alphabetic run of ``name`` string (e.g. 'MGRES' from 'MGRES_G4').

    Gets the 'BASE' in strings following the '<BASE>_<suffix>' naming convention,
    where 'BASE' is shared between child generation and parent production EGEs.

    Args:
        name (str | None): Name string to be assessed.

    Returns:
        str | None: Upper-case leading alphabetic prefix of ``name`` or "" if no ``name``.
    """
    if not name:
        return ""
    match = _ALPHA_PREFIX_PATTERN.match(str(name).strip())
    return match.group(0).upper() if match else ""


def safe_str(val: object) -> str | None:
    """Return a safe string (stripped) from a provided object.

    Args:
        val (object): Value to be stripped.

    Returns:
        str | None: Stripped string or None if value is missing/blank.
    """
    return str(val).strip() if pd.notna(val) and str(val).strip() else None


class EICCodeRegistry:
    """Name-enrichment locator backed by ENTSO-E's public EIC code registry.

    Downloads the official EIC code publication on first use and optionally caches
    it locally.  Provides EIC code → official display name lookups so that generic
    ENTSO-E unit names (e.g. "Unit 10") can be replaced with their registered plant
    name before fuzzy-matching against OSM.

    Attributes:
        cache_dir (Path | None): Directory used for caching the downloaded registry.
        df_eic (pd.DataFrame): Parsed EIC code registry.
    """

    # Fields returned by lookup_full_row
    WCODE_FIELDS: tuple[str, ...] = (
        DISPLAY_NAME_COL,
        LONG_NAME_COL,
        PARENT_COL,
        PARTY_COL,
        STATUS_COL,
        TYPE_COL,
    )

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize EICCodeRegistry.

        Args:
            cache_dir (Path, optional): Directory for caching the downloaded registry.
                Defaults to None (no caching).
        """
        self.cache_dir = cache_dir
        self.df_eic: pd.DataFrame = pd.DataFrame()
        self._eic_col: str | None = None
        self._display_name_col: str | None = None
        self._long_name_col: str | None = None
        self._eic_index: dict[str, int] = {}
        self._df_prod_cache: pd.DataFrame | None = None
        self._prod_prefixes_cache: pd.Series | None = None
        self._prod_candidates_cache: list[str] | None = None
        self._load()

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
            self.df_eic = pd.read_csv(cache_path, sep=";", dtype=str)
            self._detect_columns()
            return

        try:
            logger.info("EICCodeRegistry: downloading ENTSO-E W-type EIC codes...")
            resp = requests.get(EIC_DIRECTORY_URL, timeout=60, headers=HEADER)
            resp.raise_for_status()

            self.df_eic = pd.read_csv(io.StringIO(resp.text), sep=";", dtype=str)
            self._detect_columns()

            if cache_path and not self.df_eic.empty:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.df_eic.to_csv(cache_path, sep=";", index=False)
                logger.info(f"EICCodeRegistry: cached to '{cache_path}'")

        except requests.RequestException as e:
            logger.warning(
                f"EICCodeRegistry: download failed ({e}). "
                "Name enrichment via EIC directory will be unavailable."
            )

    def _detect_columns(self) -> None:
        """Detect which columns hold EIC codes and display/long names."""
        # Prefer known stable column names from the W-type CSV format.
        if EIC_COL in self.df_eic.columns:
            self._eic_col = EIC_COL
            if DISPLAY_NAME_COL in self.df_eic.columns:
                self._display_name_col = DISPLAY_NAME_COL
            if LONG_NAME_COL in self.df_eic.columns:
                self._long_name_col = LONG_NAME_COL
            logger.info(f"EICCodeRegistry initialized: {len(self.df_eic)} entries")
            self._build_eic_index()
            return

        # Fallback: case-insensitive detection for cached files with different format.
        cols_lower = {c.strip().lower(): c for c in self.df_eic.columns}
        for candidate in ("eiccode", "eic_code", "eic code", "eic", "code"):
            if candidate in cols_lower:
                self._eic_col = cols_lower[candidate]
                break
        for candidate in ("eicdisplayname", "display_name", "displayname", "name"):
            if candidate in cols_lower:
                self._display_name_col = cols_lower[candidate]
                break

        for candidate in ("eiclongname", "long_name", "longname"):
            if candidate in cols_lower:
                self._long_name_col = cols_lower[candidate]
                break

        if self._eic_col and (self._display_name_col or self._long_name_col):
            logger.info(
                f"EICCodeRegistry initialized: {len(self.df_eic)} entries | "
                f"EIC col='{self._eic_col}' | "
                f"long='{self._long_name_col}' | display='{self._display_name_col}'"
            )
        else:
            logger.warning(
                "EICCodeRegistry: could not identify required columns. "
                f"Available: {list(self.df_eic.columns)}"
            )
        self._build_eic_index()

    def _build_eic_index(self) -> None:
        """Pre-compute an index for EIC codes and their row positions once (for 30k+ rows)."""
        if len(self.df_eic) == 0 or not self._eic_col:
            return

        index: dict[str, int] = {}
        for pos, code in enumerate(self.df_eic[self._eic_col]):
            if pd.notna(code):
                index.setdefault(str(code).strip(), pos)
        self._eic_index = index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def lookup_full_row(self, eic_code: str) -> dict[str, str | None]:
        """Return selected W_eicCodes fields for an EIC code as a flat dict.

        Args:
            eic_code (str): ENTSO-E EIC code to look up.

        Returns:
            dict with keys EicDisplayName, EicLongName, EicParent,
            EicResponsibleParty, EicStatus, EicTypeFunctionList.  Values are
            stripped strings or None.  Returns an empty dict if not found.
        """
        if len(self.df_eic) == 0 or not self._eic_col or not eic_code:
            return {}

        pos = self._eic_index.get(str(eic_code).strip())
        if pos is None:
            return {}

        row = self.df_eic.iloc[pos]
        result: dict[str, str | None] = {}
        for col in self.WCODE_FIELDS:
            if col in row.index:
                result[col] = safe_str(row[col])
            else:
                result[col] = None
        return result

    def find_parent_production_unit(
        self,
        eic_parent: str | None,
        display_name: str | None,
        long_name: str | None,
        responsible_party: str | None,
    ) -> dict[str, str | float | None] | None:
        """Find the matching parent production EGE in the EIC directory for a generation EGE.

        Use one of three strategies:
        1. Direct lookup (``match_method = "direct_parent"``):
            If `eic_parent` is not empty, look it up directly in the EIC and return that row.
        2. Display-name prefix match (``match_method = "display_prefix"``):
            Many EIC entries follow a ``"<BASE>_<suffix>"`` naming convention where a
            generation EGE and its parent production EGE share the same alphabetic base token
            (e.g. "MGRES_G4", "MGRES_PU"). Find cases where `eic_parent` is empty and the long
            names are too generic/dissimilar for the fuzzy fallback (3.) to reach the score.
        3. Fuzzy search (``match_method = "fuzzy"``):
            Filter the EIC to entries whose ``EicTypeFunctionList`` identifies them as a
            "Production Unit", then fuzzy-match the generation EGE's names against those.

        A +5-point bonus is applied to 2. and 3. when ``EicResponsibleParty`` also matches.
        Only accepted when the final score ≥ 80. Match confidence is "high" when ≥ 90.

        Args:
            eic_parent (str | None): EicParent value from the generation EGE's own EIC row.
            display_name (str | None): EicDisplayName of the generation EGE.
            long_name (str | None): EicLongName of the generation EGE.
            responsible_party (str | None): EicResponsibleParty of the generation EGE;
                used as a matching bonus.

        Returns:
            dict | None: Details on the identified matching parent production EGE with keys
            ``EicCode``, ``EicDisplayName``, ``EicLongName``, `EicResponsibleParty``,
            ``match_score``, ``match_confidence`` (high ≥ 90 / medium ≥ 80),
            ``match_method`` ("direct_parent" / "display_prefix" / "fuzzy")
            or None if no match was found.
        """
        if len(self.df_eic) == 0 or not self._eic_col:
            return None

        # --- Strategy 1: direct parent EIC lookup ---
        if eic_parent and str(eic_parent).strip():
            parent_data = self.lookup_full_row(str(eic_parent).strip())
            if parent_data:
                return {
                    "EicCode": str(eic_parent).strip(),
                    **parent_data,
                    "match_score": 100.0,
                    "match_confidence": "high",
                    "match_method": "direct_parent",
                }

        # --- Strategy 2: fuzzy match against Production Unit entries ---
        if TYPE_COL not in self.df_eic.columns:
            return None

        # Log EicTypeFunctionList once so exact string can be confirmed in this CSV version
        if not getattr(self, "_prod_type_logged", False):
            distinct = sorted(self.df_eic[TYPE_COL].dropna().unique().tolist())
            logger.debug(
                f"EICCodeRegistry: distinct EicTypeFunctionList values "
                f"(first 30): {distinct[:30]}"
            )
            self._prod_type_logged = True

        # Compute the static "Production Unit" EGE subset (and its derivations) once
        if self._df_prod_cache is None:
            prod_mask = self.df_eic[TYPE_COL].str.contains(
                r"Production.?Unit|A26", na=False, regex=True, case=False
            )
            self._df_prod_cache = self.df_eic[prod_mask].copy()
        df_prod = self._df_prod_cache
        if len(df_prod) == 0:
            logger.debug(
                "EICCodeRegistry: no 'Production Unit' EGE entries found in EIC "
                "directory for fuzzy parent matching."
            )
            return None

        # --- Strategy 2: display-name prefix match (fast, high precision) ---
        prefix_hit_row = None
        prefix_score = -1.0
        child_prefix = alpha_prefix(display_name)
        if child_prefix and len(child_prefix) >= 3 and self._display_name_col:
            if self._prod_prefixes_cache is None:
                self._prod_prefixes_cache = df_prod[self._display_name_col].apply(
                    alpha_prefix
                )
            prod_prefixes = self._prod_prefixes_cache
            exact_candidates = df_prod[prod_prefixes == child_prefix]

            if len(exact_candidates) > 0:
                df_prefix_candidates = exact_candidates
                base_score = EXACT_PREFIX_SCORE
            else:
                # Requires a reasonably long shared prefix to avoid false groupings
                # E.g. wrong match: "HPPENGURIUNIT" (GE) → "HPP_SESTRIMO" (BG) due to "HPP"
                contains_mask = prod_prefixes.apply(
                    lambda p: (
                        bool(p)
                        and min(len(p), len(child_prefix)) >= MIN_PREFIX_OVERLAP
                        and (p.startswith(child_prefix) or child_prefix.startswith(p))
                    )
                )
                df_prefix_candidates = df_prod[contains_mask]
                base_score = PARTIAL_PREFIX_SCORE

            if len(df_prefix_candidates) == 1:
                prefix_hit_row = df_prefix_candidates.iloc[0]
                prefix_score = base_score
            elif len(df_prefix_candidates) > 1:
                # Multiple candidates share prefix: find match in subset with long-name fuzzy
                best_sub_score = -1.0
                for _, cand_row in df_prefix_candidates.iterrows():
                    cand_long = (
                        cand_row.get(self._long_name_col)
                        if self._long_name_col
                        else None
                    )
                    sub_score = (
                        fuzz.token_set_ratio(long_name, cand_long)
                        if long_name and cand_long and pd.notna(cand_long)
                        else 0.0
                    )
                    if sub_score > best_sub_score:
                        best_sub_score = sub_score
                        prefix_hit_row = cand_row
                prefix_score = min(base_score, MIN_MATCH_SCORE + best_sub_score * 0.15)
                logger.debug(
                    f"EICCodeRegistry: {len(df_prefix_candidates)} production units "
                    f"share display-name prefix '{child_prefix}' — picked best long-name match."
                )

        if prefix_hit_row is not None:
            # Apply responsible-party bonus
            if (
                responsible_party
                and PARTY_COL in prefix_hit_row.index
                and pd.notna(prefix_hit_row[PARTY_COL])
                and str(responsible_party).strip()
                == str(prefix_hit_row[PARTY_COL]).strip()
            ):
                prefix_score = min(100.0, prefix_score + PARTY_BONUS)

            confidence = "high" if prefix_score >= HIGH_MATCH_SCORE else "medium"
            return {
                "EicCode": safe_str(prefix_hit_row[self._eic_col]),
                "EicDisplayName": safe_str(prefix_hit_row.get(self._display_name_col))
                if self._display_name_col
                else None,
                "EicLongName": safe_str(prefix_hit_row.get(self._long_name_col))
                if self._long_name_col
                else None,
                "EicResponsibleParty": safe_str(prefix_hit_row.get(PARTY_COL))
                if PARTY_COL in prefix_hit_row.index
                else None,
                "match_score": prefix_score,
                "match_confidence": confidence,
                "match_method": "display_prefix",
            }

        # --- Strategy 3: fuzzy match against "Production Unit" entries ---
        # Build the static candidate name list from production EGE long/display names once
        if self._prod_candidates_cache is None:
            candidates: list[str] = []
            for col in (self._long_name_col, self._display_name_col):
                if col and col in df_prod.columns:
                    candidates.extend(df_prod[col].dropna().str.strip().tolist())
            seen: set[str] = set()
            unique_candidates: list[str] = []
            for c in candidates:
                if c and c not in seen:
                    seen.add(c)
                    unique_candidates.append(c)
            self._prod_candidates_cache = unique_candidates
        unique_candidates = self._prod_candidates_cache
        if not unique_candidates:
            return None

        # Build query names from the generation EGE (prefer LongName)
        unit_names: list[str] = []
        for n in (long_name, display_name):
            if n and str(n).strip():
                unit_names.append(str(n).strip())
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

        if best_score < MIN_MATCH_SCORE or best_match_name is None:
            return None

        # Locate the matching row in df_prod
        hit_row = None
        for col in (self._long_name_col, self._display_name_col):
            if col and col in df_prod.columns:
                matches = df_prod[df_prod[col].str.strip() == best_match_name]
                if len(matches) > 0:
                    hit_row = matches.iloc[0]
                    break
        if hit_row is None:
            return None

        # Apply responsible-party bonus
        if (
            responsible_party
            and PARTY_COL in hit_row.index
            and pd.notna(hit_row[PARTY_COL])
            and str(responsible_party).strip() == str(hit_row[PARTY_COL]).strip()
        ):
            best_score = min(100.0, best_score + PARTY_BONUS)

        if best_score < MIN_MATCH_SCORE:
            return None

        confidence = "high" if best_score >= HIGH_MATCH_SCORE else "medium"

        return {
            "EicCode": safe_str(hit_row[self._eic_col]),
            "EicDisplayName": safe_str(hit_row.get(self._display_name_col))
            if self._display_name_col
            else None,
            "EicLongName": safe_str(hit_row.get(self._long_name_col))
            if self._long_name_col
            else None,
            "EicResponsibleParty": safe_str(hit_row.get(PARTY_COL))
            if PARTY_COL in hit_row.index
            else None,
            "match_score": best_score,
            "match_confidence": confidence,
            "match_method": "fuzzy",
        }
