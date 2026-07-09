"""Centralized name matching utilities for coordinate finding.

This module provides a unified, matrix-based approach to fuzzy name matching
across multiple power plant data sources (GEM, PPM, OSM).

Key Features:
- Systematic generation of name variants for both input and candidate names
- Pre-computed search matrix for efficient lookups
- Hard country filtering to prevent cross-country false positives
- Fuel type guardrails for validation
- Source priority (GEM > PPM > OSM)
- Caching for performance
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

import pandas as pd
from loguru import logger

from rbc.coordinates import tokenizer as _tokenizer
from rbc.coordinates.mappings import GENERIC_UNIT_TOKENS
from rbc.coordinates.tokenizer import (
    weighted_token_score,
    weighted_tokenize,
)

if TYPE_CHECKING:
    from rbc.coordinates.locator_gem import GEMLocator
    from rbc.coordinates.locator_ppm import PPMLocator


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class MatchCandidate:
    """A single matching candidate from a data source."""

    name: str
    normalized: str
    source: str  # 'gem', 'ppm', 'osm'
    fueltype: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    country: Optional[str]
    source_id: Optional[str]
    match_score: float = 0.0
    confidence: str = "hight"  # 'high', 'medium', 'low'
    other_names: str = ""  # GEM-specific: comma-separated alternate names


@dataclass
class MatchResult:
    """Result of a name matching operation."""

    matched: bool
    candidate: Optional[MatchCandidate]
    score: float
    variants_tried: list[str]
    top_candidates: list[MatchCandidate]  # Top 5 for debugging


@dataclass(frozen=True)
class SourceAdapter:
    """Column-mapping config that lets one candidate builder serve any source.

    Replaces the 3 near-duplicate, hardcoded ``_build_ppm_candidates`` /
    ``_build_gem_candidates`` / ``_build_osm_candidates`` methods with a
    single generic builder (see ``NameMatrixMatcher._build_candidates``)
    parameterized per source.
    """

    source: str  # 'ppm', 'gem', 'osm'
    get_df: Callable[["NameMatrixMatcher"], Optional[pd.DataFrame]]
    name_col: str
    country_col: Optional[str]  # None if the source has no country column (e.g. OSM)
    fueltype_col: str
    id_col: str
    lat_col: str = "lat"
    lon_col: str = "lon"
    other_names_col: Optional[str] = None  # GEM only: comma-joined alt names
    confidence_fn: Callable[[pd.Series], str] = lambda row: "medium"


PPM_ADAPTER = SourceAdapter(
    source="ppm",
    get_df=lambda m: getattr(m._ppm_locator, "df_europe", None),
    name_col="Name",
    country_col="Country",
    fueltype_col="Fueltype",
    id_col="id",
    confidence_fn=lambda row: "high" if pd.notna(row.get("EIC")) else "medium",
)

GEM_ADAPTER = SourceAdapter(
    source="gem",
    get_df=lambda m: getattr(m._gem_locator, "df_gem", None),
    name_col="plant_name",
    country_col="Country",
    fueltype_col="Fueltype",
    id_col="gem_unit_id",
    other_names_col="other_names",
    confidence_fn=lambda row: "high",
)

OSM_ADAPTER = SourceAdapter(
    source="osm",
    # OSM's alt-name tag variants (name:en, alt_name, old_name, ...) are
    # already exploded into separate rows sharing the same OSM_ID upstream
    # (locator_osm_api.py), so no other_names_col/extra handling is needed
    # here -- iterating rows picks them up for free.
    get_df=lambda m: m._osm_df,
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
    - Source priority: GEM > PPM > OSM
    - Caching for repeated matches

    Example:
        >>> matcher = NameMatrixMatcher(
        ...     country="Germany",
        ...     gem_locator=gem_loc,
        ...     ppm_locator=ppm_loc,
        ...     osm_df=osm_data
        ... )
        >>> result = matcher.match("Enguri Unit 5", fuel_type="hydro")
        >>> if result.matched:
        ...     print(f"Found: {result.candidate.name} at ({result.candidate.lat}, {result.candidate.lon})")
    """

    # Source priority bonuses (added to fuzzy match scores)
    SOURCE_BONUS: dict[str, float] = {
        "gem": 3.0,
        "ppm": 2.0,
        "osm": 1.0,
    }

    def __init__(
        self,
        country: Optional[str] = None,
        country_code: Optional[str] = None,
        fuel_type: Optional[str] = None,
        gem_locator: Optional["GEMLocator"] = None,
        ppm_locator: Optional["PPMLocator"] = None,
        osm_df: Optional[pd.DataFrame] = None,
    ) -> None:
        """Initialize the name matrix matcher.

        Args:
            country: Country name for hard filtering (prevents cross-country matches).
            country_code: ISO-2 country code for token expansion.
            fuel_type: Optional fuel type for pre-filtering candidates.
            gem_locator: Optional GEMLocator instance for GEM candidates.
            ppm_locator: Optional PPMLocator instance for PPM candidates.
            osm_df: Optional DataFrame with OSM power plant data.
        """
        self.country = country
        self.country_code = country_code
        self.fuel_type = fuel_type

        # Name variant cache: original_name -> [variants]
        self._variant_cache: dict[str, list[str]] = {}

        # Candidate matrix: normalized_name -> [MatchCandidate]
        self._matrix: dict[str, list[MatchCandidate]] = {}
        self._matrix_built = False

        # Weighted-token cache: normalized_name -> WeightedTokens. Keyed by
        # the normalized string (not the candidate object), so it's a pure
        # function of (normalized, self.country_code) and never needs
        # invalidation -- also gives free cache hits across the many
        # candidates that already share a normalized name (matrix buckets).
        self._weighted_tokens_cache: dict[str, "_tokenizer.WeightedTokens"] = {}

        # Data sources (lazy-loaded)
        self._gem_locator: Optional["GEMLocator"] = gem_locator
        self._ppm_locator: Optional["PPMLocator"] = ppm_locator
        self._osm_df: Optional[pd.DataFrame] = osm_df

        # Track added alternative names for EIC enrichment
        self._alternative_names: dict[str, list[str]] = {}

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def add_alternative_names(self, base_name: str, alt_names: list[str]) -> None:
        """Add alternative names for a base name (e.g., from EIC directory).

        Args:
            base_name: The original/primary name.
            alt_names: List of alternative names to try for this base name.
        """
        if base_name not in self._alternative_names:
            self._alternative_names[base_name] = []
        self._alternative_names[base_name].extend(alt_names)
        # Invalidate cache since we added new names
        self._matrix_built = False

    def generate_name_variants(self, name: str) -> list[str]:
        """Generate all plausible name variants for matching.

        Generates:
        1. Original name
        2. Normalized (lowercase, no diacritics, no special chars)
        3. Token-expanded (abbreviations -> full names)
        4. Unit-stripped (remove "Unit 5", "Block 2", etc.)
        5. Suffix-stripped (handle "ENGURIUNIT_5" -> "enguri")
        6. Alternative names from EIC enrichment

        Args:
            name: The base name to generate variants for.

        Returns:
            List of unique name variants.
        """
        if name in self._variant_cache:
            return self._variant_cache[name]

        variants: set[str] = set()

        # Skip empty names
        if not name or pd.isna(name):
            self._variant_cache[name] = []
            return []

        # 1. Original name
        variants.add(name)

        # 2. Normalized
        normalized = self.normalize_name(name)
        if normalized:
            variants.add(normalized)

        # 3. Token-expanded
        if normalized:
            expanded = self.expand_plant_tokens(normalized, self.country_code)
            if expanded:
                variants.add(expanded)

        # 4. Unit-stripped
        stripped_numeric = self.strip_numeric_tokens(name)
        if stripped_numeric:
            variants.add(stripped_numeric)
            # Also add normalized version of stripped
            normalized_stripped = self.normalize_name(stripped_numeric)
            if normalized_stripped:
                variants.add(normalized_stripped)
                # Also add country-expanded version of stripped
                expanded_stripped = self.expand_plant_tokens(
                    normalized_stripped, self.country_code
                )
                if expanded_stripped and expanded_stripped != normalized_stripped:
                    variants.add(expanded_stripped)

        # 5. Suffix-stripped
        stripped_suffix = self.strip_trailing_unit_suffix(name)
        if stripped_suffix and stripped_suffix != name:
            variants.add(stripped_suffix)
            normalized_suffix = self.normalize_name(stripped_suffix)
            if normalized_suffix:
                variants.add(normalized_suffix)
                # Also add country-expanded version of suffix-stripped
                expanded_suffix = self.expand_plant_tokens(
                    normalized_suffix, self.country_code
                )
                if expanded_suffix and expanded_suffix != normalized_suffix:
                    variants.add(expanded_suffix)

        # 6. Alternative names from EIC enrichment
        for alt_name in self._alternative_names.get(name, []):
            if alt_name and alt_name not in variants:
                variants.add(alt_name)
                normalized_alt = self.normalize_name(alt_name)
                if normalized_alt:
                    variants.add(normalized_alt)

        # Convert to list and cache
        result = list(variants)
        self._variant_cache[name] = result
        return result

    def build_matrix(self) -> dict[str, list[MatchCandidate]]:
        """Build the searchable candidate matrix.

        Creates a mapping from normalized names to lists of matching candidates.
        The matrix is cached and only rebuilt when sources change or new
        alternative names are added.

        Returns:
            Dictionary mapping normalized_name -> [MatchCandidate]
        """
        if self._matrix_built:
            return self._matrix

        self._matrix = {}

        # Collect candidates from all available sources via their adapters
        candidates: list[MatchCandidate] = []

        if self._ppm_locator is not None:
            candidates.extend(self._build_candidates(PPM_ADAPTER))

        if self._gem_locator is not None:
            candidates.extend(self._build_candidates(GEM_ADAPTER))

        if self._osm_df is not None and len(self._osm_df) > 0:
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

    # Default score threshold for the weighted-token scoring tier (Approach 2
    # below). NOT the same scale as `threshold` (which gauges the old
    # exact-match-plus-bonuses score, ~100+): this is a weighted average of
    # 0-100 per-token rapidfuzz.ratio scores plus the same source/fuel
    # bonuses, so it needs its own, separately-calibrated cutoff.
    DEFAULT_WEIGHTED_THRESHOLD: float = 65.0

    def match(
        self,
        target_name: str,
        fuel_type: Optional[str] = None,
        threshold: int = 85,
        weighted_threshold: Optional[float] = None,
    ) -> MatchResult:
        """Find the best match for a target name across all data sources.

        Uses a combined approach:
        1. First tries exact matches via matrix lookup (fast)
        2. Falls back to source-agnostic weighted-token scoring (see
           rbc.coordinates.tokenizer) against all valid candidates

        Args:
            target_name: The name to match.
            fuel_type: Optional fuel type for validation (overrides class default).
            threshold: Minimum score (0-100) to accept an exact-matrix match.
                Defaults to 85.
            weighted_threshold: Minimum score (0-100) to accept a weighted-token
                match. Defaults to DEFAULT_WEIGHTED_THRESHOLD.

        Returns:
            MatchResult with matched candidate or None if no match found.
        """
        if not target_name or pd.isna(target_name):
            return MatchResult(
                matched=False,
                candidate=None,
                score=0.0,
                variants_tried=[],
                top_candidates=[],
            )

        # Use provided fuel_type or fall back to class default
        effective_fuel = fuel_type if fuel_type is not None else self.fuel_type

        # Generate all variants for the target name
        target_variants = self.generate_name_variants(target_name)

        # Build matrix if not already built
        matrix = self.build_matrix()

        # Debug: log matrix size for this country
        if self.country:
            logger.debug(
                f"NameMatrixMatcher: matrix built for {self.country} with {len(matrix)} unique normalized names"
            )

        # Collect all potential matches
        all_matches: list[tuple[MatchCandidate, float]] = []

        # Get all candidates for fuzzy matching (we'll use this for all approaches)
        all_candidates = []
        for candidates in matrix.values():
            all_candidates.extend(candidates)

        # Approach 1: Exact matches via matrix lookup (fast path)
        for variant in target_variants:
            if variant in matrix:
                for candidate in matrix[variant]:
                    if self._is_valid_candidate(candidate, effective_fuel):
                        score = 100.0 + self.SOURCE_BONUS.get(candidate.source, 0.0)
                        if effective_fuel and candidate.fueltype:
                            if self._is_fueltype_compatible(
                                effective_fuel, candidate.fueltype
                            ):
                                score += 5.0
                            else:
                                score -= 20.0
                        if score >= threshold:
                            all_matches.append((candidate, score))

        # Approach 2: Source-agnostic weighted-token scoring (see
        # rbc.coordinates.tokenizer.weighted_token_score) against all valid
        # candidates. Each target token is matched against its best-fitting
        # candidate token, weighted by importance, so a true discriminative
        # name match (e.g. "auvere") counts far more than an incidental
        # match on a generic/unit token shared across unrelated plants
        # (e.g. "g1").
        if not all_matches:
            effective_weighted_threshold = (
                weighted_threshold
                if weighted_threshold is not None
                else self.DEFAULT_WEIGHTED_THRESHOLD
            )
            valid_candidates = [
                candidate
                for candidate in all_candidates
                if self._is_valid_candidate(candidate, effective_fuel)
            ]
            for variant in target_variants:
                target_wt = weighted_tokenize(variant, self.country_code)
                if not target_wt.tokens:
                    continue
                for candidate in valid_candidates:
                    candidate_wt = self._weighted_tokenize_cached(candidate.normalized)
                    score = weighted_token_score(target_wt, candidate_wt)
                    score += self.SOURCE_BONUS.get(candidate.source, 0.0)
                    if effective_fuel and candidate.fueltype:
                        if self._is_fueltype_compatible(
                            effective_fuel, candidate.fueltype
                        ):
                            score += 5.0
                        else:
                            score -= 20.0
                    if score >= effective_weighted_threshold:
                        all_matches.append((candidate, score))

        # Sort by score (descending)
        all_matches.sort(key=lambda x: x[1], reverse=True)

        # Extract top 5 candidates for debugging
        top_candidates = [m[0] for m in all_matches[:5]]

        # Check if we have a match
        if all_matches:
            best_candidate = all_matches[0][0]
            best_score = all_matches[0][1]
            best_candidate.match_score = best_score

            return MatchResult(
                matched=True,
                candidate=best_candidate,
                score=best_score,
                variants_tried=target_variants,
                top_candidates=top_candidates,
            )

        return MatchResult(
            matched=False,
            candidate=None,
            score=0.0,
            variants_tried=target_variants,
            top_candidates=top_candidates,
        )

    def _weighted_tokenize_cached(self, normalized: str) -> "_tokenizer.WeightedTokens":
        """Memoized `weighted_tokenize(normalized, self.country_code)`.

        The same (small) set of candidates is rescanned for every unmatched
        target row within a country, so without this cache the weighted
        scoring tier recomputes identical tokenization/weighting work
        thousands of times over on large candidate pools (observed: full
        24-zone run time went from ~60s to ~11min without this cache).
        """
        cached = self._weighted_tokens_cache.get(normalized)
        if cached is None:
            cached = weighted_tokenize(normalized, self.country_code)
            self._weighted_tokens_cache[normalized] = cached
        return cached

    def _is_valid_candidate(
        self, candidate: "MatchCandidate", fuel_type: Optional[str] = None
    ) -> bool:
        """Check if a candidate is valid for matching (has coordinates, passes country filter)."""
        # Skip candidates without coordinates
        if candidate.lat is None or candidate.lon is None:
            return False

        # Hard country filter: candidate must match our country
        if self.country and candidate.country:
            # Normalize both country names for comparison (handles zone-specific aliases)
            normalized_self_country = self._normalize_country_for_matching(self.country)
            normalized_candidate_country = self._normalize_country_for_matching(
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

    def _normalize_country_for_matching(self, country: str | None) -> str | None:
        """Normalize country names to match PPM database country names.

        This handles zone-specific country aliases (e.g., 'Germany (TransnetBW)',
        'Great Britain / National Grid') and maps them to their base country names
        (e.g., 'Germany', 'United Kingdom') as used in PPM.

        Args:
            country: Country name that may include zone-specific suffixes.

        Returns:
            Normalized country name or None if no normalization possible.
        """
        if not country:
            return None

        country = str(country).strip()
        import re

        # Step 1: Extract the base country name by removing zone-specific suffixes
        # Handle patterns like "Germany (TransnetBW)" -> "Germany"
        base_country = re.sub(r"\s*\([^)]*\)\s*$", "", country).strip()

        # Step 2: Handle slash-separated aliases like "Great Britain / National Grid" -> "Great Britain"
        if "/" in base_country:
            # Split by slash and take the first part (the actual country name)
            parts = [part.strip() for part in base_country.split("/")]
            # Take the first non-empty part
            base_country = parts[0] if parts else base_country

        # Step 3: Handle known aliases that need special mapping
        # PPM uses "United Kingdom" but ENTSO-E uses "Great Britain" in some cases
        alias_mappings = {
            "great britain": "united kingdom",
            "gb": "united kingdom",
        }
        base_country_lower = base_country.lower()
        if base_country_lower in alias_mappings:
            return alias_mappings[base_country_lower]

        # Step 4: Clean up any remaining artifacts
        base_country = base_country.strip()

        if base_country:
            return base_country

        # Step 5: Fallback to original country if we couldn't normalize
        return country

    def _get_ppm_country_name(self, country: str | None) -> str | None:
        """Get the country name as it appears in PPM database.

        This handles the case where PPM uses slightly different country names
        than what we have in our metadata.
        """
        if not country:
            return None

        # Map known aliases to PPM country names
        ppm_country_aliases = {
            "estonia": "Estonia",
            "ee": "Estonia",
            "switzerland": "Switzerland",
            "ch": "Switzerland",
            "germany": "Germany",
            "de": "Germany",
            "france": "France",
            "fr": "France",
        }

        country_lower = str(country).strip().lower()
        return ppm_country_aliases.get(country_lower, country)

    # ---------------------------------------------------------------------------
    # Private Candidate Builder
    # ---------------------------------------------------------------------------

    def _build_candidates(self, adapter: SourceAdapter) -> list[MatchCandidate]:
        """Build candidates from any source via its :class:`SourceAdapter` config.

        Replaces the former per-source ``_build_ppm_candidates`` /
        ``_build_gem_candidates`` / ``_build_osm_candidates`` methods with one
        generic builder, field-for-field equivalent (country/fuel filters,
        coordinate/name requirements, confidence rule, other_names).
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
            normalized_country = self._normalize_country_for_matching(self.country)
            source_country_name = self._get_ppm_country_name(normalized_country)
            if source_country_name:
                df = df[
                    df[adapter.country_col].astype(str).str.lower()
                    == str(source_country_name).lower()
                ]

        # Filter by fuel type if specified
        if self.fuel_type:
            df = df[
                df[adapter.fueltype_col].apply(
                    lambda x: self._is_fueltype_compatible(self.fuel_type, x)
                )
            ]

        # Filter to only rows with coordinates
        df = df.dropna(subset=[adapter.lat_col, adapter.lon_col])

        if len(df) == 0:
            return []

        candidates = []
        for _, row in df.iterrows():
            name_val = row[adapter.name_col]
            name = str(name_val) if pd.notna(name_val) else ""
            if not name:
                continue

            # Normalize and expand plant name tokens for better cross-language
            # matching, via the shared source-agnostic tokenizer so target and
            # candidate names are tokenized identically.
            normalized = self.normalize_name(name)
            expanded = " ".join(_tokenizer.tokenize_and_expand(name, self.country_code))

            other_names = ""
            if adapter.other_names_col:
                other_names_val = row.get(adapter.other_names_col)
                other_names = str(other_names_val) if pd.notna(other_names_val) else ""

            country_val = row.get(adapter.country_col) if adapter.country_col else None

            candidates.append(
                MatchCandidate(
                    name=name,
                    normalized=expanded if expanded else normalized,
                    source=adapter.source,
                    fueltype=str(row[adapter.fueltype_col])
                    if pd.notna(row[adapter.fueltype_col])
                    else None,
                    lat=float(row[adapter.lat_col])
                    if pd.notna(row[adapter.lat_col])
                    else None,
                    lon=float(row[adapter.lon_col])
                    if pd.notna(row[adapter.lon_col])
                    else None,
                    country=str(country_val) if pd.notna(country_val) else None,
                    source_id=str(row.get(adapter.id_col))
                    if pd.notna(row.get(adapter.id_col))
                    else None,
                    confidence=adapter.confidence_fn(row),
                    other_names=other_names,
                )
            )

        return candidates

    # ---------------------------------------------------------------------------
    # Static Helper Methods
    # ---------------------------------------------------------------------------

    @staticmethod
    def normalize_name(value: Optional[str]) -> str:
        """Normalize power plant names for robust cross-source matching.

        Delegates to :func:`rbc.coordinates.tokenizer.normalize_name`.

        Args:
            value: The name to normalize.

        Returns:
            Normalized name string.
        """
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            return ""
        return _tokenizer.normalize_name(value)

    @staticmethod
    def expand_plant_tokens(normalized: str, country_code: Optional[str] = None) -> str:
        """Expand known plant-type abbreviations and local names to canonical English.

        Delegates to :func:`rbc.coordinates.tokenizer.tokenize_and_expand`, so
        target- and candidate-side names go through the same source-agnostic
        logic (including glued-name stripping), rather than matcher.py
        maintaining its own separate token-expansion pass.

        Args:
            normalized: Already-normalized (lowercase, diacritic-free) name.
            country_code: Optional ISO-2 country code for country-specific expansions.

        Returns:
            Name with known tokens replaced/stripped, joined back into a string.
        """
        if not normalized:
            return normalized
        return " ".join(_tokenizer.tokenize_and_expand(normalized, country_code))

    @staticmethod
    def strip_numeric_tokens(value: str) -> str:
        """Return a simplified normalized name for station-level fallback matching.

        This is a last-resort fallback for cases where ENTSO-E names include unit
        numbers and generic unit markers (e.g. "Unit 20", "Sloecentrale unit 20")
        but OSM only stores the station-level feature without a per-unit suffix
        (e.g. just "Sloecentrale").

        Args:
            value: The name to process.

        Returns:
            Name with numeric tokens and generic unit tokens removed.
        """
        normalized = NameMatrixMatcher.normalize_name(value)
        if not normalized:
            return ""

        tokens = [
            token
            for token in normalized.split()
            if not token.isdigit() and token not in GENERIC_UNIT_TOKENS
        ]
        return " ".join(tokens).strip()

    @staticmethod
    def strip_trailing_unit_suffix(value: str) -> str:
        """Strip a trailing unit-suffix glued directly onto the plant name.

        Some ENTSO-E naming conventions concatenate the unit suffix directly onto
        the plant name with no separating space/underscore (e.g. "ENGURIUNIT_5" -> "enguri"),
        which the space-tokenized strip_numeric_tokens cannot catch since
        "enguriunit" and "5" would otherwise remain a single glued token.

        Args:
            value: The name to process.

        Returns:
            The name with the trailing unit-suffix removed, or empty string if
            the name doesn't end in a recognized unit-suffix.
        """
        normalized = NameMatrixMatcher.normalize_name(value)
        if not normalized:
            return ""

        # Build regex pattern from multi-character unit tokens
        unit_words = "|".join(token for token in GENERIC_UNIT_TOKENS if len(token) > 1)
        if not unit_words:
            return normalized

        stripped = re.sub(rf"(?:{unit_words})\s*\d*$", "", normalized).strip()
        return stripped if stripped and stripped != normalized else ""

    @staticmethod
    def _is_fueltype_compatible(eg_type: Optional[str], pp_type: Optional[str]) -> bool:
        """Validate if the eg fuel type matches the pp database fuel type.

        Handles basic string cleaning and empty values gracefully.

        Args:
            eg_type: Fuel type from energy generation data.
            pp_type: Fuel type from power plant database.

        Returns:
            True if types are compatible, False otherwise.
        """
        from rbc.energy.entsoe.mappings import FUELTYPE_MAPPINGS

        if pd.isna(eg_type) or pd.isna(pp_type):
            return True  # If one dataset lacks a type, we pass it but remain cautious

        # Normalize to canonical labels
        def _normalize_type(value: Optional[str]) -> str:
            if value is None or pd.isna(value):
                return ""
            raw = str(value).strip()
            mapped = FUELTYPE_MAPPINGS.get(raw, raw)
            return str(mapped).lower().strip()

        eg_clean = _normalize_type(eg_type)
        pp_clean = _normalize_type(pp_type)

        # Check if one contains the other
        return eg_clean in pp_clean or pp_clean in eg_clean
