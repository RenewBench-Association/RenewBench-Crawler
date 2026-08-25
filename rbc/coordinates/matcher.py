"""Centralized name matching utilities for coordinate finding.

This module provides a unified, lookup-based approach to fuzzy name matching
across multiple power plant data sources, namely ppdb (PPM/OSMPP), GEM, OSM.

Key Features:
- Systematic generation of name variants for both input and candidate names
- Pre-computed search index for efficient lookups
- Hard country filtering to prevent cross-country false positives
- Fuel type guardrails for validation
- Source priority: GEM > ppdb (PPM/OSMPP) > OSM
- Caching for performance
"""

from functools import cached_property

import pandas as pd
from loguru import logger

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.match_schema import (
    GEM_ADAPTER,
    OSM_ADAPTER,
    PPDB_ADAPTER,
    LocatorAdapter,
    MatchCandidate,
    MatchResult,
)
from rbc.coordinates.utils.country import normalize_operator_country_name
from rbc.coordinates.utils.fuel import is_fueltype_compatible
from rbc.coordinates.utils.tokenizer import (
    NameTokenizer,
    get_weighted_token_score,
    strip_numeric_tokens,
    strip_trailing_unit_suffix,
)
from rbc.coordinates.utils.values import is_missing, normalize_name


class NameMatcher:
    """Lookup-based fuzzy name matcher for multiple (coordinate) locator data sources.

    This class consolidates all name-based matching logic into a single, reusable component.
    It builds a searchable lookup index that maps normalized names to candidate EGEs, enabling
    efficient many-to-many matching with systematic variant generation.

    Definitions:
    - target(s): sys-op EGE(s) to find coordinates for.
    - candidate(s): EGE(s) from coordinate/locator data sources that may match.

    Features:
    - Generates all plausible name variants for both input and candidates
    - Hard country filtering to prevent cross-country false positives
    - Fuel type guardrails for validation
    - Source priority: GEM > ppdb (PPM/OSMPP) > OSM
    - Caching for repeated matches

    Example:
        >>> matcher = NameMatcher(country="Germany",gem_locator=gem_loc,ppdb_locator=ppm_loc)
        ...     osm_df=osm_df, tok=tok
        ... )
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
    }  # todo: redefine with "reliability" info!

    def __init__(
        self,
        country: str | None = None,
        gem_locator: GEMLocator | None = None,
        ppdb_locator: PPMLocator | OSMPPLocator | None = None,
        osm_df: pd.DataFrame | None = None,
        tok: NameTokenizer | None = None,
    ) -> None:
        """Initialize the name matcher.

        Args:
            country (str | None): Target country name for hard filtering (prevents
                cross-country matches). Defaults to None.
            gem_locator (GEMLocator | None): GEM locator instance for GEM candidates.
                Defaults to None.
            ppdb_locator (PPMLocator | OSMPPLocator | None): PPMLocator or OSMPPLocator
                locator for power plant database candidates. Defaults to None.
            osm_df (df | None): DataFrame with OSM power plant data.
            tok (NameTokenizer | None): NameTokenizer instance for tokenization. Defaults
                to None, in which case a vocabulary-less tokenizer is created (generic
                tokens only, no operator/country name translations).
        """
        self.target_country = country
        self.norm_target_country = normalize_operator_country_name(country)

        # Data sources
        self.gem_locator: GEMLocator | None = gem_locator
        self.ppdb_locator: PPMLocator | OSMPPLocator | None = ppdb_locator
        self.osm_df: pd.DataFrame | None = osm_df

        # Tokenizer
        self.tok: NameTokenizer = tok if tok is not None else NameTokenizer()

        # Cache for target name variants and alternatives (e.g. from EIC enrichment)
        self._target_variants: dict[str, list[str]] = {}  # name -> [variants]
        self._target_alternatives: dict[str, list[str]] = {}  # name -> [alternatives]

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------
    def add_target_alternatives(self, name: str, alt_names: list[str]) -> None:
        """Add alternative names for a target EGE's name (e.g. from EIC registry).

        Args:
            name (str): The original/primary target's name.
            alt_names (list[str]): List of alternative names to try for this target's name.
        """
        if name not in self._target_alternatives:
            self._target_alternatives[name] = []

        self._target_alternatives[name].extend(alt_names)

    def match(
        self,
        target_name: str,
        fuel_type: str | None = None,
        threshold: float = 75.0,
        weighted_threshold: float = 65.0,
    ) -> MatchResult:
        """Find the best match for a target EGE name across all candidate data sources.

        Uses a combined approach:
        1. Tries exact matches via candidate_index lookup (fast)
        2. Falls back to weighted-token scoring (s. tokenizer.py) against all valid candidates

        Args:
            target_name (str): The name to match.
            fuel_type (str | None): Fuel type for validation (overrides class default).
                Defaults to None.
            threshold (float): Minimum score (0-100) to accept an exact-lookup match
                (exact-match-plus-bonuses score). Defaults to 75.
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
                all_target_variants=[],
                top_matches=[],
            )

        # --- Preparation: Define and build all required parameters
        candidate_index = self._candidate_index
        target_variants = self._generate_target_variants(target_name)

        winning_matches: list[tuple[MatchCandidate, float]] = []  # winner collection
        all_matches: list[tuple[MatchCandidate, float]] = []  # full match collection

        # --- Approach 1: Exact matches via candidate_index lookup (fast path)
        for variant in target_variants:
            if variant in candidate_index:
                for candidate in candidate_index[variant]:
                    score = 100.0
                    score = self._adjust_score(score, candidate, fuel_type)

                    all_matches.append((candidate, score))
                    if score >= threshold:
                        winning_matches.append((candidate, score))

        # --- Approach 2: Weighted-token scoring against all candidates.
        # Each target token is matched against its best-fitting candidate token and weighted:
        # A descriptive match (e.g. "auvere") counts far more than a generic one (e.g. "g1").
        if not winning_matches:
            all_candidates = []  # get all candidates for matching
            for candidates in candidate_index.values():
                all_candidates.extend(candidates)

            for variant in target_variants:
                target_wt = self.tok.weighted_tokenize(variant)
                if not target_wt.tokens:
                    continue

                for candidate in all_candidates:
                    candidate_wt = self.tok.weighted_tokenize(candidate.norm_name)

                    score = get_weighted_token_score(target_wt, candidate_wt)
                    score = self._adjust_score(score, candidate, fuel_type)

                    all_matches.append((candidate, score))
                    if score >= weighted_threshold:
                        winning_matches.append((candidate, score))

        # --- Postprocess: Define all identified matches
        relevant_threshold = min(threshold, weighted_threshold) - 5.0

        winning_matches.sort(key=lambda x: x[1], reverse=True)  # descending by score
        all_matches.sort(key=lambda x: x[1], reverse=True)  # descending by score

        # keep best score per candidate (variants that normalize alike, score alike)
        best_per_candidate: dict[int, tuple[MatchCandidate, float]] = {}
        for cand, score in all_matches:
            prev = best_per_candidate.get(id(cand))
            if prev is None or score > prev[1]:
                best_per_candidate[id(cand)] = (cand, score)

        all_matches = sorted(
            best_per_candidate.values(), key=lambda x: x[1], reverse=True
        )
        top_matches = [
            (cand, score)
            for cand, score in all_matches[:10]
            if score >= relevant_threshold
        ]

        # get matched candidate with the best score
        best_candidate = top_matches[0][0] if top_matches else None
        best_score = top_matches[0][1] if top_matches else 0.0
        if best_candidate:
            best_candidate.match_score = best_score

        if top_matches:
            return MatchResult(
                matched=True if winning_matches else False,
                candidate=best_candidate,
                score=best_score,
                all_target_variants=target_variants,
                top_matches=top_matches,
            )

        return MatchResult(
            matched=False,
            candidate=None,
            score=0.0,
            all_target_variants=target_variants,
            top_matches=top_matches,
        )

    # ---------------------------------------------------------------------------
    # Cached properties (calculated once and re-used)
    # ---------------------------------------------------------------------------
    @cached_property
    def _candidate_index(self) -> dict[str, list[MatchCandidate]]:
        """Build the searchable candidate index/lookup cache (norm_name -> [MatchCandidates]).

        Creates a mapping of each unique normalized candidate name to the list of candidates
        that share said name from all coordinate sources, stored as MatchCandidate objects.
        As a ``@cached_property``, ``_candidate_index`` is built once and reused after.

        Returns:
            index (dict): Candidate index/lookup dict.
        """
        index: dict[str, list[MatchCandidate]] = {}

        # Collect candidates from all available sources via their adapters
        candidates: list[MatchCandidate] = []

        if self.ppdb_locator is not None:
            candidates.extend(self._build_candidates(PPDB_ADAPTER))

        if self.gem_locator is not None:
            candidates.extend(self._build_candidates(GEM_ADAPTER))

        if self.osm_df is not None and len(self.osm_df) > 0:
            candidates.extend(self._build_candidates(OSM_ADAPTER))

        # Add candidates to index by normalized name
        for candidate in candidates:
            index.setdefault(candidate.norm_name, []).append(candidate)

        logger.info(
            f"NameMatcher: Built candidate lookup for '{self.target_country}' with "
            f"{len(candidates)} total candidates, of which {len(index)} are unique."
        )
        return index

    # ---------------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------------
    def _build_candidates(self, adapter: LocatorAdapter) -> list[MatchCandidate]:
        """Build candidates from a locator source depending on its ``SourceAdapter`` config.

        Returns valid candidates by including only those that:
        - pass the country filter (if a country & location source country column are given)
        - have location coordinates (lat/lon)

        Args:
            adapter (LocatorAdapter): The locator source adapter to build candidates from.

        Returns:
            list[MatchCandidate]: A list of valid candidates as MatchCandidate objects.
        """
        df = adapter.get_df(self)
        if df is None:
            return []

        try:
            df = df.copy()
        except AttributeError:
            return []

        # Filter by country if specified and the source has a country column (OSM has none)
        if self.target_country and adapter.country_col:
            df = df[
                df[adapter.country_col].astype(str).str.lower()
                == str(self.norm_target_country).lower()
            ]

        # Filter to only rows with coordinates
        df = df.dropna(subset=[adapter.lat_col, adapter.lon_col])

        if len(df) == 0:
            return []

        candidates = []
        for _, row in df.iterrows():
            candidate = MatchCandidate.from_row(row, adapter, self.tok)
            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def _generate_target_variants(self, name: str) -> list[str]:
        """Generate all plausible variants of the target EGE's name for matching.

        Generates:
        1. Original name
        2. Normalized (lowercase, no diacritics, no special chars)
        3. Token-expanded (abbreviations -> full names)
        4. Unit-stripped (remove "Unit 5", "Block 2", etc.)
        5. Suffix-stripped (handle "ENGURIUNIT_5" -> "enguri")
        6. Alternative names (e.g. from EIC enrichment)

        Args:
            name: The base target name to generate variants for.

        Returns:
            result (list): List of unique name variants.
        """
        if name in self._target_variants:
            return self._target_variants[name]

        if is_missing(name):
            self._target_variants[name] = []
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

        # 6. Alternative names
        for alt_name in self._target_alternatives.get(name, []):
            if alt_name and alt_name not in variants:
                variants.add(alt_name)
                normalized_alt = normalize_name(alt_name)
                if normalized_alt:
                    variants.add(normalized_alt)

        # Convert to list and cache
        result = list(variants)
        self._target_variants[name] = result
        return result

    def _adjust_score(
        self, score: float, candidate: MatchCandidate, fuel: str | None
    ) -> float:
        """Apply bonus/penalty to the score for a given candidate depending on the fuel type.

        Args:
            score (float): The score to adjust.
            candidate (MatchCandidate): The candidate to adjust the score for.
            fuel (str): The candidate's fuel type.

        Returns:
            float: The adjusted score.
        """
        score += self.SOURCE_BONUS.get(candidate.source, 0.0)

        if fuel and candidate.fueltype:
            if is_fueltype_compatible(fuel, candidate.fueltype):
                score += 5.0  # match bonus
            else:
                score -= 20.0  # mismatch penalty

        return score
