"""Centralized name matching utilities for coordinate finding.

This module provides a unified, matrix-based approach to fuzzy name matching
across multiple power plant data sources, namely ppdb (PPM/OSMPP), GEM, OSM.

Key Features:
- Systematic generation of name variants for both input and candidate names
- Pre-computed search matrix for efficient lookups
- Hard country filtering to prevent cross-country false positives
- Fuel type guardrails for validation
- Source priority: GEM > ppdb (PPM/OSMPP) > OSM
- Caching for performance
"""

from dataclasses import dataclass
from typing import Callable

import pandas as pd
from loguru import logger

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.utils.country import (
    get_ppm_country_name,
    normalize_country_for_matching,
)
from rbc.coordinates.utils.fuel import is_fueltype_compatible
from rbc.coordinates.utils.tokenizer import (
    NameTokenizer,
    get_weighted_token_score,
    normalize_name,
    strip_numeric_tokens,
    strip_trailing_unit_suffix,
)
from rbc.coordinates.utils.values import is_missing, strip_str


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class MatchCandidate:
    """A single matching candidate from a data source."""

    name: str
    normalized: str
    source: str  # 'ppdb' (= ppm/osmpp), 'gem', 'osm'
    fueltype: str | None
    lat: float | None
    lon: float | None
    country: str | None
    source_id: str | None
    match_score: float = 0.0
    confidence: str = "high"  # 'high', 'medium', 'low'
    other_names: str = ""  # GEM-specific: comma-separated alternate names


@dataclass
class MatchResult:
    """Result of a name matching operation."""

    matched: bool
    candidate: MatchCandidate | None
    score: float
    variants_tried: list[str]
    top_candidates: list[MatchCandidate]  # Top 5 for debugging


@dataclass(frozen=True)
class SourceAdapter:
    """Column-mapping config that lets one candidate builder serve any source.

    Replaces hardcoded candidate building per locator source with a single generic builder
    (see ``NameMatrixMatcher._build_candidates``).
    """

    source: str  # 'ppdb' (= ppm/osmpp), 'gem', 'osm'
    get_df: Callable[["NameMatrixMatcher"], pd.DataFrame | None]
    name_col: str
    country_col: str | None  # None if the source has no country column (e.g. OSM)
    fueltype_col: str
    id_col: str
    lat_col: str = "lat"
    lon_col: str = "lon"
    other_names_col: str | None = None  # GEM only: comma-joined alt names
    confidence_fn: Callable[[pd.Series], str] = lambda row: "medium"


GEM_ADAPTER = SourceAdapter(
    source="gem",
    get_df=lambda m: getattr(m.gem_locator, "df_gem", None),
    name_col="plant_name",
    country_col="Country",
    fueltype_col="Fueltype",
    id_col="gem_unit_id",
    other_names_col="other_names",
    confidence_fn=lambda row: "high",
)

# todo: confidence def means PPDB all non-entsoe operators have "medium" confidence level
PPDB_ADAPTER = SourceAdapter(
    source="ppdb",
    get_df=lambda m: getattr(m.ppdb_locator, "df", None),
    name_col="Name",
    country_col="Country",
    fueltype_col="Fueltype",
    id_col="id",
    confidence_fn=lambda row: "high" if pd.notna(row.get("EIC")) else "medium",
)

OSM_ADAPTER = SourceAdapter(
    source="osm",
    get_df=lambda m: m.osm_df,  # duplicated rows for each alt name (s. osm_api.py)
    name_col="Name",
    country_col=None,  # no country column; relies on the matrix-level filter
    fueltype_col="Fueltype",
    id_col="OSM_ID",
    confidence_fn=lambda row: "medium",
)


# ---------------------------------------------------------------------------
# Main Matcher Class
# ---------------------------------------------------------------------------
class NameMatrixMatcher:
    """Matrix-based fuzzy name matcher across multiple data sources.

    This class consolidates all name-based matching logic into a single,
    reusable component. It builds a searchable matrix that maps normalized
    names to candidate power plants, enabling efficient many-to-many matching
    with systematic variant generation.

    Features:
    - Generates all plausible name variants for both input and candidates
    - Hard country filtering to prevent cross-country false positives
    - Fuel type guardrails for validation
    - Source priority: GEM > ppdb (PPM/OSMPP) > OSM
    - Caching for repeated matches

    Example:
        >>> matcher = NameMatrixMatcher(country="Germany",gem_locator=gem_loc,osm_df=osm_data)
        >>> result = matcher.match("Enguri Unit 5", fuel_type="hydro")
        >>> if result.matched:
        ...     candidate = result.candidate
        ...     print(f"Found: {candidate.name} at ({candidate.lat}, {candidate.lon})")
    """

    # Source priority bonuses (added to fuzzy match scores)
    SOURCE_BONUS: dict[str, float] = {
        "gem": 3.0,
        "ppdb": 2.0,
        "osm": 1.0,
    }

    def __init__(
        self,
        country: str | None = None,
        country_code: str | None = None,
        fuel_type: str | None = None,
        gem_locator: GEMLocator | None = None,
        ppdb_locator: PPMLocator | OSMPPLocator | None = None,
        osm_df: pd.DataFrame | None = None,
        tok: NameTokenizer | None = None,
    ) -> None:
        """Initialize the name matrix matcher.

        Args:
            country (str | None): Country name for hard filtering (prevents cross-country
                matches). Defaults to None.
            country_code (str | None): ISO3166-alpha-2 country code for token expansion.
                Defaults to None.
            fuel_type (str | None): Fuel type for pre-filtering candidates. Defaults to None.
            gem_locator (GEMLocator | None): GEM locator instance for GEM candidates.
                Defaults to None.
            ppdb_locator (PPMLocator | OSMPPLocator | None): PPMLocator or OSMPPLocator
                locator for power plant database candidates. Defaults to None.
            osm_df (df | None): DataFrame with OSM power plant data.
            tok (NameTokenizer | None): NameTokenizer instance for tokenization.
        """
        self.country = country
        self.country_code = country_code
        self.fuel_type = fuel_type

        # Data sources (lazy-loaded)
        self.gem_locator: GEMLocator | None = gem_locator
        self.ppdb_locator: PPMLocator | OSMPPLocator | None = ppdb_locator
        self.osm_df: pd.DataFrame | None = osm_df

        # Tokenizer
        self.tok: NameTokenizer = (
            tok if tok is not None else NameTokenizer(country_code)
        )

        # Cache of name variants: name -> [variants]
        self._name_variants: dict[str, list[str]] = {}
        # Alternative names (e.g. from EIC enrichment): name -> [alternatives]
        self._alternative_names: dict[str, list[str]] = {}

        # Candidate matrix: normalized_name -> [MatchCandidate]
        self._matrix: dict[str, list[MatchCandidate]] = {}
        self._matrix_built = False

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------
    def add_alternative_names(self, name: str, alt_names: list[str]) -> None:
        """Add alternative names for a base name (e.g., from EIC directory).

        Args:
            name (str): The original/primary name.
            alt_names (list[str]): List of alternative names to try for this base name.
        """
        if name not in self._alternative_names:
            self._alternative_names[name] = []

        self._alternative_names[name].extend(alt_names)
        self._matrix_built = False  # invalidate cache since new names were added

    def generate_name_variants(self, name: str) -> list[str]:
        """Generate all plausible name variants for matching.

        Generates:
        1. Original name
        2. Normalized (lowercase, no diacritics, no special chars)
        3. Token-expanded (abbreviations -> full names)
        4. Unit-stripped (remove "Unit 5", "Block 2", etc.)
        5. Suffix-stripped (handle "ENGURIUNIT_5" -> "enguri")
        6. Alternative names (e.g. from EIC enrichment)

        Args:
            name: The base name to generate variants for.

        Returns:
            result (list): List of unique name variants.
        """
        if name in self._name_variants:
            return self._name_variants[name]

        if is_missing(name):
            self._name_variants[name] = []
            return []  # skip empty names

        variants: set[str] = set()

        # 1. Original name
        variants.add(name)

        # 2. Normalized name
        normalized = normalize_name(name)
        if normalized:
            variants.add(normalized)

        # 3. Token-expanded name
        if normalized:
            expanded = " ".join(self.tok.tokenize(normalized))
            if expanded:
                variants.add(expanded)

        # 4. Unit-stripped name & country-expanded unit-stripped
        stripped_numeric = strip_numeric_tokens(name)
        if stripped_numeric:
            variants.add(stripped_numeric)

            expanded_stripped = " ".join(self.tok.tokenize(stripped_numeric))
            if expanded_stripped and expanded_stripped != stripped_numeric:
                variants.add(expanded_stripped)

        # 5. Suffix-stripped name & country-expanded suff-stripped
        stripped_suffix = strip_trailing_unit_suffix(name)
        if stripped_suffix and stripped_suffix != name:
            variants.add(stripped_suffix)

            expanded_suffix = " ".join(self.tok.tokenize(stripped_suffix))
            if expanded_suffix and expanded_suffix != stripped_suffix:
                variants.add(expanded_suffix)

        # 6. Alternative names from EIC enrichment
        for alt_name in self._alternative_names.get(name, []):
            if alt_name and alt_name not in variants:
                variants.add(alt_name)
                normalized_alt = normalize_name(alt_name)
                if normalized_alt:
                    variants.add(normalized_alt)

        # Convert to list and cache
        result = list(variants)
        self._name_variants[name] = result
        return result

    def build_matrix(self) -> dict[str, list[MatchCandidate]]:
        """Build the searchable candidate matrix.

        Creates a mapping from normalized names to lists of matching candidates.
        The matrix is cached and only rebuilt when sources change or new
        alternative names are added.

        Returns:
            dict: Dictionary mapping normalized_name -> [MatchCandidate]
        """
        if self._matrix_built:
            return self._matrix

        self._matrix = {}

        # Collect candidates from all available sources via their adapters
        candidates: list[MatchCandidate] = []

        if self.ppdb_locator is not None:
            candidates.extend(self._build_candidates(PPDB_ADAPTER))

        if self.gem_locator is not None:
            candidates.extend(self._build_candidates(GEM_ADAPTER))

        if self.osm_df is not None and len(self.osm_df) > 0:
            candidates.extend(self._build_candidates(OSM_ADAPTER))

        # Index candidates by normalized name
        for candidate in candidates:
            if candidate.normalized not in self._matrix:
                self._matrix[candidate.normalized] = []
            self._matrix[candidate.normalized].append(candidate)

        self._matrix_built = True
        logger.debug(
            f"NameMatrixMatcher: built matrix with {len(candidates)} candidates"
        )

        return self._matrix

    def match(
        self,
        target_name: str,
        fuel_type: str | None = None,
        threshold: float = 85.0,
        weighted_threshold: float = 65.0,
    ) -> MatchResult:
        """Find the best match for a target name across all data sources.

        Uses a combined approach:
        1. First tries exact matches via matrix lookup (fast)
        2. Falls back to weighted-token scoring (s. tokenizer.py) against all valid candidates

        Args:
            target_name (str): The name to match.
            fuel_type (str | None): Fuel type for validation (overrides class default).
                Defaults to None.
            threshold (float): Minimum score (0-100) to accept an exact-matrix match
                (exact-match-plus-bonuses score). Defaults to 85.
            weighted_threshold (float): Minimum score (0-100) to accept a weighted token
                match (weighted average of per-token rapidfuzz.ratio scores plus the same
                source/fuel bonuses). Defaults to 65.

        Returns:
            MatchResult with matched candidate or None if no match found.
        """
        if is_missing(target_name):
            return MatchResult(
                matched=False,
                candidate=None,
                score=0.0,
                variants_tried=[],
                top_candidates=[],
            )

        # --- Define vars in preparation for matching
        effective_fuel = fuel_type if fuel_type is not None else self.fuel_type

        # Generate all variants for the target name
        target_name_variants = self.generate_name_variants(target_name)

        # Build matrix (if not already built)
        matrix = self.build_matrix()
        if self.country:
            logger.debug(
                f"NameMatrixMatcher: matrix built for {self.country} with {len(matrix)} "
                f"unique normalized names"
            )

        # Collect all potential matches
        all_matches: list[tuple[MatchCandidate, float]] = []

        # --- Approach 1: Exact matches via matrix lookup (fast path)
        for variant in target_name_variants:
            if variant in matrix:
                for candidate in matrix[variant]:
                    if self._is_valid_candidate(candidate):
                        score = 100.0 + self.SOURCE_BONUS.get(candidate.source, 0.0)
                        if effective_fuel and candidate.fueltype:
                            if is_fueltype_compatible(
                                effective_fuel, candidate.fueltype
                            ):
                                score += 5.0
                            else:
                                score -= 20.0

                        if score >= threshold:
                            all_matches.append((candidate, score))

        # --- Approach 2: Weighted-token scoring against all valid candidates.
        # Each target token is matched against its best-fitting candidate token and weighted
        # by importance, so a true discriminative name match (e.g. "auvere") counts far
        # more than a match on a generic/unit token shared by unrelated plants (e.g. "g1").
        if not all_matches:
            all_candidates = []  # get all candidates for matching
            for candidates in matrix.values():
                all_candidates.extend(candidates)

            valid_candidates = [
                c for c in all_candidates if self._is_valid_candidate(c)
            ]
            for variant in target_name_variants:
                target_wt = self.tok.weighted_tokenize(variant)
                if not target_wt.tokens:
                    continue

                for candidate in valid_candidates:
                    candidate_wt = self.tok.weighted_tokenize(candidate.normalized)

                    score = get_weighted_token_score(target_wt, candidate_wt)
                    score += self.SOURCE_BONUS.get(candidate.source, 0.0)
                    if effective_fuel and candidate.fueltype:
                        if is_fueltype_compatible(effective_fuel, candidate.fueltype):
                            score += 5.0
                        else:
                            score -= 20.0

                    if score >= weighted_threshold:
                        all_matches.append((candidate, score))

        # --- Postprocess all identified matches
        all_matches.sort(key=lambda x: x[1], reverse=True)  # descending by score
        top_candidates = [m[0] for m in all_matches[:5]]  # top 5 for debugging

        if all_matches:
            best_candidate = all_matches[0][0]
            best_score = all_matches[0][1]
            best_candidate.match_score = best_score

            return MatchResult(
                matched=True,
                candidate=best_candidate,
                score=best_score,
                variants_tried=target_name_variants,
                top_candidates=top_candidates,
            )

        return MatchResult(
            matched=False,
            candidate=None,
            score=0.0,
            variants_tried=target_name_variants,
            top_candidates=top_candidates,
        )

    def _is_valid_candidate(self, candidate: "MatchCandidate") -> bool:
        """Check if a candidate is valid for matching (has coordinate, passes country filter).

        Args:
            candidate (MatchCandidate): The candidate to check.

        Returns:
            bool: True if the candidate is valid, False otherwise.
        """
        # Skip candidates without coordinates
        if candidate.lat is None or candidate.lon is None:
            return False

        # Hard country filter: candidate must match our country
        if self.country and candidate.country:
            # Normalize both country names for comparison (handles zone-specific aliases)
            normalized_self_country = normalize_country_for_matching(self.country)
            normalized_candidate_country = normalize_country_for_matching(
                candidate.country
            )

            if normalized_self_country and normalized_candidate_country:
                if (
                    normalized_self_country.lower()
                    != normalized_candidate_country.lower()
                ):
                    return False
            elif self.country.lower() != candidate.country.lower():
                return False

        return True

    # ---------------------------------------------------------------------------
    # Private Candidate Builder
    # ---------------------------------------------------------------------------
    def _build_candidates(self, adapter: SourceAdapter) -> list[MatchCandidate]:
        """Build candidates from a source depending on its `SourceAdapter` config.

        Args:
            adapter (SourceAdapter): The source adapter to build candidates from.

        Returns:
            list[MatchCandidate]: A list of matching candidates.
        """
        df = adapter.get_df(self)
        if df is None:
            return []

        try:
            df = df.copy()
        except AttributeError:
            return []

        # Filter by country if specified and the source has a country column
        # (OSM has none; relies on the matrix-level country filter instead).
        if self.country and adapter.country_col:
            normalized_country = normalize_country_for_matching(self.country)
            source_country_name = get_ppm_country_name(normalized_country)
            if source_country_name:
                df = df[
                    df[adapter.country_col].astype(str).str.lower()
                    == str(source_country_name).lower()
                ]

        # Filter by fuel type if specified
        if self.fuel_type:
            df = df[
                df[adapter.fueltype_col].apply(
                    lambda x: is_fueltype_compatible(self.fuel_type, x)
                )
            ]

        # Filter to only rows with coordinates
        df = df.dropna(subset=[adapter.lat_col, adapter.lon_col])

        if len(df) == 0:
            return []

        candidates = []
        for _, row in df.iterrows():
            name = strip_str(row[adapter.name_col])
            if name is None:
                continue

            # Normalize and expand plant name tokens for better cross-language
            # matching, via the shared source-agnostic tokenizer so target and
            # candidate names are tokenized identically.
            normalized = normalize_name(name)
            expanded = " ".join(self.tok.tokenize(name))

            other_names = ""
            if adapter.other_names_col:
                other_names = strip_str(row.get(adapter.other_names_col)) or ""

            candidates.append(
                MatchCandidate(
                    name=name,
                    normalized=expanded if expanded else normalized,
                    source=adapter.source,
                    fueltype=strip_str(row[adapter.fueltype_col]),
                    lat=float(row[adapter.lat_col])
                    if pd.notna(row[adapter.lat_col])
                    else None,
                    lon=float(row[adapter.lon_col])
                    if pd.notna(row[adapter.lon_col])
                    else None,
                    country=strip_str(row.get(adapter.country_col))
                    if adapter.country_col
                    else None,
                    source_id=strip_str(row.get(adapter.id_col)),
                    confidence=adapter.confidence_fn(row),
                    other_names=other_names,
                )
            )

        return candidates
