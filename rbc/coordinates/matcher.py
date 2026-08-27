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
    LOCATOR_ADAPTERS,
    LOCATOR_RELIABILITY,
    LocatorAdapter,
    MatchCandidate,
    MatchResult,
)
from rbc.coordinates.utils.country import normalize_operator_country_name
from rbc.coordinates.utils.fuel import classify_fueltype_match
from rbc.coordinates.utils.tokenizer import (
    NameTokenizer,
    get_weighted_token_score,
    strip_glued_generic_tokens,
    strip_separate_generic_tokens,
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
        >>> result = matcher.match("Enguri Unit 5",fueltype="hydro")
        >>> if result.matched:
        ...     candidate = result.candidate
        ...     print(f"Found: {candidate.name} at ({candidate.lat}, {candidate.lon})")
    """

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
        fueltype: str | None = None,
        threshold: float = 75.0,
        weighted_threshold: float = 65.0,
    ) -> MatchResult:
        """Find the best match for a target EGE name across all candidate data sources.

        Uses a combined approach:
        1. Tries exact matches via candidate_index lookup (fast)
        2. Falls back to weighted-token scoring (s. tokenizer.py) against all valid candidates

        Args:
            target_name (str): The name to match.
            fueltype (str | None): Fuel type for validation (overrides class default).
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
                target_variants=[],
                target_wt_strings=[],
                top_matches=[],
            )

        # --- Preparation: Define and build all required parameters
        candidate_index = self._candidate_index
        target_variants = self._generate_target_variants(target_name)
        target_wts = [self.tok.weighted_tokenize(v) for v in target_variants]

        # full match collection: MatchCandidate, score, target tok&weights, candidate
        # WeightedTokens
        all_matches: list[tuple[MatchCandidate, float]] = []
        winning_matches: list[tuple[MatchCandidate, float]] = []  # winner collection

        # --- Approach 1: Exact matches via candidate_index lookup (fast path)
        for variant in target_variants:
            if variant in candidate_index:
                for candidate in candidate_index[variant]:
                    score = 100.0
                    score = self._adjust_score(score, fueltype, candidate.fueltype)

                    all_matches.append((candidate, score))
                    if score >= threshold:
                        winning_matches.append((candidate, score))

            # if a variant has been matched, stop 'descending' down the list
            if winning_matches:
                break

        # --- Approach 2: Weighted-token scoring against all candidates.
        # Each target token is matched against its best-fitting candidate token and weighted:
        # A descriptive match (e.g. "auvere") counts far more than a generic one (e.g. "g1").
        if not winning_matches:
            all_candidates = []  # get all candidates for matching
            for candidates in candidate_index.values():
                all_candidates.extend(candidates)

            for target_wt in target_wts:
                if not target_wt.tokens:
                    continue

                for candidate in all_candidates:
                    candidate_wt = self.tok.weighted_tokenize(candidate.norm_name)

                    score = get_weighted_token_score(target_wt, candidate_wt)
                    score = self._adjust_score(score, fueltype, candidate.fueltype)

                    all_matches.append((candidate, score))
                    if score >= weighted_threshold:
                        winning_matches.append((candidate, score))

                # if a variant has been matched, stop descending
                if winning_matches:
                    break

        # --- Postprocess: Define all identified matches
        # 1. Sort matches:
        # winners: first by score (highest first), then by adapter (most reliable first)
        winning_matches.sort(
            key=lambda x: (x[1], LOCATOR_RELIABILITY.get(x[0].source, 0)),
            reverse=True,
        )
        # all: only by score (highest first)
        all_matches.sort(key=lambda x: x[1], reverse=True)

        # 2. keep best score per candidate variants (if same normalized name, same score)
        best_per_candidate: dict[int, tuple[MatchCandidate, float]] = {}
        for cand, score in all_matches:
            prev = best_per_candidate.get(id(cand))
            if prev is None or score > prev[1]:
                best_per_candidate[id(cand)] = (cand, score)

        # 3. Get top matches as top-10 of all that score above the relevant threshold
        all_matches = sorted(
            best_per_candidate.values(), key=lambda x: x[1], reverse=True
        )
        top_matches = [
            (cand, score)
            for cand, score in all_matches[:10]
            if score >= min(threshold, weighted_threshold) - 5.0
        ]

        # 4. Get matched candidate with the best score
        if winning_matches:
            best_candidate, best_score = winning_matches[0]
        elif top_matches:
            best_candidate, best_score = top_matches[0]
        else:
            best_candidate, best_score = None, 0.0

        return MatchResult(
            matched=True if winning_matches else False,
            candidate=best_candidate,
            score=best_score,
            target_variants=target_variants,
            target_wt_strings=[wt.as_str() for wt in target_wts],
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

        # Collect candidates from all available locators via their adapters
        candidates: list[MatchCandidate] = []

        for adapter in LOCATOR_ADAPTERS:  # in order of locator reliability!
            candidates.extend(self._build_candidates(adapter))

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
        if df is None or len(df) == 0:
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
        """Generate all plausible variants of a target EGE's name for matching.

        Generates ordered list, with most specific variants first. ``match()`` iterates
        through this list and stops as soon as a winner is found, so the order is important.
        Steps 4. and 5. deliberately remove the unit number, so if they're compared before
        the full name, unit-precise matches may be missed (e.g. "Mauá Bloco 6" -> "maua",
        which matches "Mauá 3" exactly as well as "Mauá 6").

        1. Alternative names (e.g. from EIC enrichment) --- authoritative variant(s)
        2. Raw name
        3. Normalized --- lowercase, no diacritics/special char ("ENGURUNIT_5" -> "engurunit)
        4. Word-stripped --- removes separate, generic tokens ("Enguri Unit 5" -> "Enguri")
        5. Glue-stripped --- removes glued, generic tokens ("ENGURIUNIT_5" -> "enguri")

        Methods 3.-5. also include token-expanded variants, where abbreviations are turned
        into full names.

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

        # Define variants as ordered list, with most specific first
        variants: list[str] = []

        def add(v: str | None) -> None:
            """Add a variant to the target EGE's variant list if it isn't already present.

            Args:
                v (str | None): The variant to add to the list.
            """
            if v and v not in variants:
                variants.append(v)

        # 1. Alternative names
        for alt_name in self._target_alternatives.get(name, []):
            add(alt_name)
            add(normalize_name(alt_name))

        # 2. Raw name & 3. Normalized name --- baseline
        add(name)
        normalized = normalize_name(name)
        add(normalized)
        add(" ".join(self.tok.tokenize(normalized)))  # tokenized variant

        # 4. Name stripped of trailing space-separated generic tokens
        stripped_separate = strip_separate_generic_tokens(normalized=normalized)
        add(stripped_separate)
        add(" ".join(self.tok.tokenize(stripped_separate)))  # tokenized variant

        # 5. Name stripped of trailing glued generic tokens
        stripped_glued = strip_glued_generic_tokens(normalized=normalized)
        add(stripped_glued)
        add(" ".join(self.tok.tokenize(stripped_glued)))  # tokenized variant

        # Store to cache and return
        logger.info(f"Target variants for {name}:\t{' | '.join(variants)}.")
        self._target_variants[name] = variants
        return variants

    @staticmethod
    def _adjust_score(
        score: float, target_fuel: str | None, candidate_fuel: str | None
    ) -> float:
        """Adjust score for a given candidate depending on whether the fuel types match.

        Get fuel type match level with the classify_fueltype_match helper, define handling
        based on the classification str.

        Args:
            score (float): The score to adjust.
            target_fuel (str | None): The target's fuel type. Defaults to None.
            candidate_fuel (str | None): The candidate's fuel type. Defaults to None.

        Returns:
            float: The adjusted score.
        """
        level = classify_fueltype_match(target_fuel, candidate_fuel)
        if level == "mismatch":  # redefine to 0
            return 0.0
        elif level == "unknown":  # leave score unchanged
            return score

        # bonus for correct match ("exact" or "compatible")
        score += 5.0
        return score
