"""EIC code-based coordinate and name locators.

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
# Column names in the W-type EIC CSV (semicolon-delimited, stable as of 2026)
_EIC_COL = "EicCode"
_DISPLAY_NAME_COL = "EicDisplayName"
_LONG_NAME_COL = "EicLongName"
_HEADER = {
    "User-Agent": (
        "RenewBench Association "
        "(+https://github.com/RenewBench-Association/RenewBench-Crawler)"
    )
}

# Matches the leading alphabetic run of an EIC display name, e.g. 'MGRES_G4' -> 'MGRES',
# 'MGRES_PU' -> 'MGRES'.  Used to detect the common '<BASE>_<suffix>' naming convention
# shared between generation units and their parent production unit.
_ALPHA_PREFIX_PATTERN = re.compile(r"^[A-Za-z]+")


def _alpha_prefix(name: str | None) -> str:
    """Return the leading alphabetic run of *name*, uppercased (or "" if none)."""
    if not name:
        return ""
    match = _ALPHA_PREFIX_PATTERN.match(str(name).strip())
    return match.group(0).upper() if match else ""


def _safe_str(val: object) -> str | None:
    """Return a stripped string, or None for missing/blank values."""
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
        "EicDisplayName",
        "EicLongName",
        "EicParent",
        "EicResponsibleParty",
        "EicStatus",
        "EicTypeFunctionList",
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
            resp = requests.get(EIC_DIRECTORY_URL, timeout=60, headers=_HEADER)
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
        if _EIC_COL in self.df_eic.columns:
            self._eic_col = _EIC_COL
            if _DISPLAY_NAME_COL in self.df_eic.columns:
                self._display_name_col = _DISPLAY_NAME_COL
            if _LONG_NAME_COL in self.df_eic.columns:
                self._long_name_col = _LONG_NAME_COL
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
        """Pre-compute an EIC-code -> row-position index, once.

        ``lookup_full_row`` used to run a full string-compare scan
        (``.str.strip() == target``) over the whole 30k+ row directory on
        *every* call. Building this index once at load time turns each lookup
        into an O(1) dict access instead (first occurrence wins, same as the
        previous ``hits.iloc[0]`` behaviour).
        """
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
                val = row[col]
                result[col] = (
                    str(val).strip() if pd.notna(val) and str(val).strip() else None
                )
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
        """Find the matching parent production unit in the EIC directory.

        Tries three strategies in order:

        1. **Direct lookup** – if *eic_parent* is non-empty, look it up directly in the
           EIC directory and return that row (``match_method = "direct_parent"``).
        2. **Display-name prefix match** – many EIC entries follow a
           ``"<BASE>_<suffix>"`` naming convention where a generation unit and its
           parent production unit share the same alphabetic base token (e.g.
           ``"MGRES_G4"`` / ``"MGRES_PU"``). This catches cases where *eic_parent* is
           empty and the long names are too generic for fuzzy matching to clear the
           score threshold (``match_method = "display_prefix"``).
        3. **Fuzzy search** – filter the EIC directory to entries whose
           ``EicTypeFunctionList`` identifies them as a Production Unit, then fuzzy-match
           the generation unit's names against those entries (``match_method = "fuzzy"``).

        A +5-point bonus is applied in strategies 2 and 3 when ``EicResponsibleParty``
        also matches. Only accepted when the final score ≥ 80.

        Args:
            eic_parent (str | None): EicParent value from the generation unit's own EIC
                row (may be None or empty).
            display_name (str | None): EicDisplayName of the generation unit.
            long_name (str | None): EicLongName of the generation unit.
            responsible_party (str | None): EicResponsibleParty of the generation unit;
                used as a matching bonus.

        Returns:
            dict with keys ``EicCode``, ``EicDisplayName``, ``EicLongName``,
            ``EicResponsibleParty``, ``match_score``, ``match_confidence``
            (``"high"`` ≥ 90 / ``"medium"`` ≥ 80), ``match_method``
            (``"direct_parent"`` / ``"display_prefix"`` / ``"fuzzy"``); or ``None`` if
            no match was found.
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
        type_col = "EicTypeFunctionList"
        if type_col not in self.df_eic.columns:
            return None

        # Log distinct EicTypeFunctionList values once so callers can confirm the
        # exact string used for "Production Unit" in this version of the CSV.
        if not getattr(self, "_prod_type_logged", False):
            distinct = sorted(self.df_eic[type_col].dropna().unique().tolist())
            logger.debug(
                f"EICCodeRegistry: distinct EicTypeFunctionList values "
                f"(first 30): {distinct[:30]}"
            )
            self._prod_type_logged = True

        # The Production Unit subset (and everything derived from it below) is
        # static — it doesn't depend on the function arguments — so it's computed
        # once and cached instead of being rebuilt on every call.
        if self._df_prod_cache is None:
            prod_mask = self.df_eic[type_col].str.contains(
                r"Production.?Unit|A26", na=False, regex=True, case=False
            )
            self._df_prod_cache = self.df_eic[prod_mask].copy()
        df_prod = self._df_prod_cache
        if len(df_prod) == 0:
            logger.debug(
                "EICCodeRegistry: no Production Unit entries found in EIC "
                "directory for fuzzy parent matching."
            )
            return None

        # --- Strategy 2a: display-name prefix match (fast, high precision) ---
        # Many EIC entries follow a "<BASE>_<suffix>" naming convention where a
        # generation unit and its parent production unit share the same alphabetic
        # base token, e.g. "MGRES_G4" (generation) / "MGRES_PU" (production). This
        # catches cases where EicParent is empty and the long names are too generic
        # / dissimilar for the fuzzy fallback below to reach the score threshold.
        prefix_hit_row = None
        prefix_score = -1.0
        child_prefix = _alpha_prefix(display_name)
        if child_prefix and len(child_prefix) >= 3 and self._display_name_col:
            if self._prod_prefixes_cache is None:
                self._prod_prefixes_cache = df_prod[self._display_name_col].apply(
                    _alpha_prefix
                )
            prod_prefixes = self._prod_prefixes_cache
            exact_candidates = df_prod[prod_prefixes == child_prefix]

            if len(exact_candidates) > 0:
                df_prefix_candidates = exact_candidates
                base_score = 95.0
            else:
                # Require a reasonably long shared prefix (not just an exact
                # containment) to avoid false groupings via generic plant-type
                # abbreviations shared by many unrelated plants across countries
                # (e.g. "HPP" for "Hydro Power Plant" — "HPPENGURIUNIT" (Georgia)
                # trivially startswith "HPP", which would otherwise wrongly match
                # e.g. Bulgaria's "HPP_SESTRIMO").
                min_prefix_overlap = 5
                contains_mask = prod_prefixes.apply(
                    lambda p: (
                        bool(p)
                        and min(len(p), len(child_prefix)) >= min_prefix_overlap
                        and (p.startswith(child_prefix) or child_prefix.startswith(p))
                    )
                )
                df_prefix_candidates = df_prod[contains_mask]
                base_score = 85.0

            if len(df_prefix_candidates) == 1:
                prefix_hit_row = df_prefix_candidates.iloc[0]
                prefix_score = base_score
            elif len(df_prefix_candidates) > 1:
                # Multiple candidates share the prefix — disambiguate via long-name
                # fuzzy score among just this small subset.
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
                prefix_score = min(base_score, 80.0 + best_sub_score * 0.15)
                logger.debug(
                    f"EICCodeRegistry: {len(df_prefix_candidates)} production units "
                    f"share display-name prefix '{child_prefix}' — picked best long-name match."
                )

        if prefix_hit_row is not None:
            # Apply responsible-party bonus
            party_col = "EicResponsibleParty"
            if (
                responsible_party
                and party_col in prefix_hit_row.index
                and pd.notna(prefix_hit_row[party_col])
                and str(responsible_party).strip()
                == str(prefix_hit_row[party_col]).strip()
            ):
                prefix_score = min(100.0, prefix_score + 5.0)

            confidence = "high" if prefix_score >= 90 else "medium"
            return {
                "EicCode": _safe_str(prefix_hit_row[self._eic_col]),
                "EicDisplayName": _safe_str(prefix_hit_row.get(self._display_name_col))
                if self._display_name_col
                else None,
                "EicLongName": _safe_str(prefix_hit_row.get(self._long_name_col))
                if self._long_name_col
                else None,
                "EicResponsibleParty": _safe_str(prefix_hit_row.get(party_col))
                if party_col in prefix_hit_row.index
                else None,
                "match_score": prefix_score,
                "match_confidence": confidence,
                "match_method": "display_prefix",
            }

        # --- Strategy 2b: fuzzy match against Production Unit entries ---
        # Build candidate name list from production unit long/display names (cached,
        # since it's static and would otherwise be rebuilt on every call).
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

        # Build query names from the generation unit (prefer LongName)
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

        if best_score < 80 or best_match_name is None:
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
        party_col = "EicResponsibleParty"
        if (
            responsible_party
            and party_col in hit_row.index
            and pd.notna(hit_row[party_col])
            and str(responsible_party).strip() == str(hit_row[party_col]).strip()
        ):
            best_score = min(100.0, best_score + 5.0)

        if best_score < 80:
            return None

        confidence = "high" if best_score >= 90 else "medium"

        return {
            "EicCode": _safe_str(hit_row[self._eic_col]),
            "EicDisplayName": _safe_str(hit_row.get(self._display_name_col))
            if self._display_name_col
            else None,
            "EicLongName": _safe_str(hit_row.get(self._long_name_col))
            if self._long_name_col
            else None,
            "EicResponsibleParty": _safe_str(hit_row.get(party_col))
            if party_col in hit_row.index
            else None,
            "match_score": best_score,
            "match_confidence": confidence,
            "match_method": "fuzzy",
        }
