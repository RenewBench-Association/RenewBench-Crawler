"""Source-agnostic name tokenization and token-weighted scoring.

Splits an EGE name into weighted tokens so that a discriminative place/EGE name (e.g.
"auvere") counts far more toward a match score than a generic EGE-type word (e.g. "unit",
"g1", "he"). Used by NameMatcher to compare a target name against PPM/GEM/OSM candidate
names via the same tokenize-and-weight function on both sides, instead of each candidate
source expanding its own names ad hoc.

Weighting is dictionary-based only (GENERIC_UNIT_TOKENS / PLANT_NAME_EXPANSIONS
/ COUNTRY_PLANT_NAME_EXPANSIONS from mappings.py).
"""

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz

from rbc.coordinates.mappings import (
    COUNTRY_PLANT_NAME_EXPANSIONS,
    GENERIC_UNIT_TOKENS,
    PLANT_NAME_EXPANSIONS,
)
from rbc.coordinates.utils.values import strip_lower_str


@dataclass(frozen=True)
class WeightedTokens:
    """A name decomposed into its tokens and their importance weights."""

    tokens: tuple[str, ...]
    weights: tuple[float, ...]


# ---------------------------------------------------------------------------
# Independent functions (pure string operators - no vocab, no country)
# ---------------------------------------------------------------------------
def normalize_name(value: str | None) -> str:
    """Normalize a power plant name for robust cross-source matching.

    Lowercase, strip diacritics, replace non-alphanumeric runs with a single
    space, collapse whitespace.
    """
    text = strip_lower_str(value)
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
    normalized = normalize_name(value)
    if not normalized:
        return ""

    tokens = [
        token
        for token in normalized.split()
        if not token.isdigit() and token not in GENERIC_UNIT_TOKENS
    ]
    return " ".join(tokens).strip()


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
    normalized = normalize_name(value)
    if not normalized:
        return ""

    # Build regex pattern from multi-character unit tokens
    unit_words = "|".join(token for token in GENERIC_UNIT_TOKENS if len(token) > 1)
    if not unit_words:
        return normalized

    stripped = re.sub(rf"(?:{unit_words})\s*\d*$", "", normalized).strip()
    return stripped if stripped and stripped != normalized else ""


def get_weighted_token_score(
    target: WeightedTokens, candidate: WeightedTokens
) -> float:
    """Get the weighted-average best-token-match score between two WeightedTokens (0-100).

    Each token in the target is matched against its best-fitting candidate token via
    rapidfuzz.ratio (weighted by importance and normalized by total weight).
    True distinctive name matches are rewarded far more than incidental matches on generic
    (low-weight) tokens (e.g. two different EGEs both having "g1" are not weighted highly).

    Args:
        target (WeightedTokens): WeightedTokens to score.
        candidate (WeightedTokens): WeightedTokens to score.

    Returns:
        float: Weighted-average best token match score.
    """
    if not target.tokens or not candidate.tokens:
        return 0.0

    total_weight = sum(target.weights)
    if total_weight <= 0:
        return 0.0

    weighted_sum = sum(
        weight * max(fuzz.ratio(tok, c) for c in candidate.tokens)
        for tok, weight in zip(target.tokens, target.weights)
    )
    return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# Country-/vocabulary-based class functionality
# ---------------------------------------------------------------------------
LOW_WEIGHT = 0.1
DEFAULT_WEIGHT = 1.0

# Short alphanumeric patterns for designating units that are not caught by the vocabulary:
# - letters+digits (e.g. "g1"/"u2"),
# - bare digits (e.g. "3"),
# - bare 1-2 letter blocks (e.g. "q"/"aa"  in "KW Boxberg Block Q"/"Neurath AA")
_SHORT_EGE_DESCRIPTOR_PATTERNS = re.compile(
    r"^(?:[a-z]{1,4}\d{1,3}|\d{1,3}|[a-z]{1,2})$"
)


@lru_cache(maxsize=None)
def build_vocabulary(country_code: str | None) -> dict[str, str]:
    """Merge GENERIC_UNIT_TOKENS + PLANT_NAME_EXPANSIONS + country overrides into vocabulary.

    Keys are the vocabulary words/abbreviations; values are their meanings/def expansions
    (generic words map to themselves). Independent of NameTokenizer instance state.

    Args:
        country_code (str | None): The country code to check for overrides. Defaults to None.

    Returns:
        vocabulary (dict): Vocabulary words and their expansions.
    """
    vocabulary: dict[str, str] = {tok: tok for tok in GENERIC_UNIT_TOKENS}
    vocabulary.update(PLANT_NAME_EXPANSIONS)
    if country_code:
        vocabulary.update(COUNTRY_PLANT_NAME_EXPANSIONS.get(country_code, {}))
    return vocabulary


class NameTokenizer:
    """Vocabulary-driven tokenization and weighting for one country."""

    def __init__(self, country_code: str | None = None) -> None:
        """Initialize the name-tokenizer class.

        Args:
            country_code (str | None): The country code (ISO3166-1:alpha-2 code) to use for
                tokenization. Defaults to None.
        """
        self.country_code = country_code
        self._vocabulary = build_vocabulary(country_code)

        # list of whole vocabulary words = more than 3 characters (excludes 2-letter codes!)
        self._vocabulary_words = sorted(
            (w for w in self._vocabulary if len(w) >= 3),
            key=len,
            reverse=True,
        )

        # Cache to store name's tokens and their weights: normalized_name -> WeightedTokens
        self._weighted_cache: dict[str, WeightedTokens] = {}

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------
    def tokenize(self, name: str | None) -> list[str]:
        """Normalize name, split into tokens and expand/strip each token using the vocabulary.

        Exact vocabulary-keys (e.g. "he", "unit") expand to their mapped vocab value and are
        split into separate if multi-word (e.g. "ej" -> "power plant elektrijaam" -> 3 tok).
        Non-vocabulary tokens go to the bidirectional glued-name stripper as a fallback.

        Args:
            name (str | None): The name to tokenize.

        Returns:
            list[str]: The name's (normalized and expanded) tokens.
        """
        normalized = normalize_name(name)
        if not normalized:
            return []

        out: list[str] = []
        for tok in normalized.split():  # split into tokens
            if tok in self._vocabulary:
                out.extend(self._vocabulary[tok].split())
            else:
                stripped = self._strip_glued(tok)
                out.append(stripped if stripped else tok)
        return out

    def weighted_tokenize(self, name: str | None) -> WeightedTokens:
        """Normalize, tokenize and expand `name` (``tokenize``), then weight each token.

        Args:
            name (str | None): The name to tokenize and weight.

        Returns:
            WeightedTokens: The name's (normalized and expanded) weighted tokens.
        """
        normalized = normalize_name(name)
        cached = self._weighted_cache.get(normalized)
        if cached is not None:
            return cached

        tokens = tuple(self.tokenize(normalized))
        weights = tuple(self._get_weight(tok) for tok in tokens)

        result = WeightedTokens(tokens, weights)
        self._weighted_cache[normalized] = result
        return result

    # ---------------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------------
    def _get_weight(self, token: str) -> float:
        """Dictionary-based token importance weight (no corpus-frequency stats).

        - Exact vocabulary key (generic unit/plant-type word) -> LOW_WEIGHT
        - Short alphanumeric unit-designator pattern (g1, u2, bare digits) -> LOW_WEIGHT
        - Everything else (presumed discriminative place/plant name) -> DEFAULT_WEIGHT

        Args:
            token (str): The token to calculate weight for.

        Returns:
            float: The weight of the token.
        """
        if token in self._vocabulary:
            return LOW_WEIGHT
        if _SHORT_EGE_DESCRIPTOR_PATTERNS.match(token):
            return LOW_WEIGHT
        return DEFAULT_WEIGHT

    def _strip_glued(self, token: str) -> str:
        """Repeatedly strip known vocabulary words off the start or end of a token.

        Only whole vocabulary words of length >= 3 are considered. This prevents 2-letter
        codes (he/te/...) from being falsely matched and the accidental removal of
        important name parts (e.g. place name "auvere" → "auve" → "au").

        Args:
            token (str): The token to inspect and strip (e.g. "riverunit").

        Returns:
            str: The stripped residual token (e.g. "river") or the input if nothing changed.
        """
        current = token
        changed = True
        while changed and current:
            changed = False
            for word in self._vocabulary_words:
                if len(word) >= len(current):
                    continue
                if current.startswith(word):
                    current = current[len(word) :]
                    changed = True
                    break
                if current.endswith(word):
                    current = current[: len(current) - len(word)]
                    changed = True
                    break
        return current
