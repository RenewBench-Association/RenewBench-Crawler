"""Source-agnostic name tokenization and token-weighted scoring.

Splits a power-plant name into weighted tokens so that a discriminative
place/plant name (e.g. "auvere") counts far more toward a match score than
a generic unit/plant-type word (e.g. "unit", "g1", "he"). Used by
NameMatrixMatcher to compare a target name against PPM/GEM/OSM candidate
names via the same tokenize-and-weight function on both sides, instead of
each candidate source expanding its own names ad hoc.

Weighting is dictionary-based only (GENERIC_UNIT_TOKENS / PLANT_NAME_EXPANSIONS
/ COUNTRY_PLANT_NAME_EXPANSIONS from mappings.py) -- no corpus-frequency
statistics.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from rapidfuzz import fuzz

from rbc.coordinates.mappings import (
    COUNTRY_PLANT_NAME_EXPANSIONS,
    GENERIC_UNIT_TOKENS,
    PLANT_NAME_EXPANSIONS,
)

LOW_WEIGHT = 0.1
DEFAULT_WEIGHT = 1.0

# Short alphanumeric unit-designator patterns not otherwise caught by the
# vocabulary: "g1"/"u2" (letters+digits), bare digits like "3", or a bare
# 1-2 letter block designator ("q", "h", "aa") as seen in e.g. "KW Boxberg
# Block Q" / "Neurath F" / "Weisweiler H".
UNIT_DESIGNATOR_RE = re.compile(r"^(?:[a-z]{1,4}\d{1,3}|\d{1,3}|[a-z]{1,2})$")

# Minimum length of a vocabulary word considered by the *glued-name stripper*
# (strip_vocabulary_glued). Vocabulary contains 2-letter ENTSO-E abbreviation
# codes (he/te/ve/fe/ne/re) that are meant to match as a *whole* token (see
# tokenize_and_expand's exact-key branch) -- allowing the stripper to also
# treat them as strippable prefixes/suffixes causes false positives on
# ordinary place names that merely happen to end in those two letters, e.g.
# "auvere" ends in "re" then (after stripping) "ve", which would otherwise
# mangle it down to "au". Restricting the stripper to length>=3 words avoids
# this while still handling genuinely glued cases like "hpp"+"river"+"unit".
MIN_STRIP_WORD_LEN = 3


def normalize_name(value: Optional[str]) -> str:
    """Normalize a power plant name for robust cross-source matching.

    Lowercase, strip diacritics, replace non-alphanumeric runs with a single
    space, collapse whitespace.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN, without importing pandas
        return ""

    text = str(value).lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@lru_cache(maxsize=None)
def build_vocabulary(country_code: Optional[str]) -> dict[str, str]:
    """Merge GENERIC_UNIT_TOKENS + PLANT_NAME_EXPANSIONS + country overrides.

    Keys are the strippable/expandable vocabulary words; values are what an
    exact-key match expands to (generic unit tokens map to themselves).
    """
    vocabulary: dict[str, str] = {tok: tok for tok in GENERIC_UNIT_TOKENS}
    vocabulary.update(PLANT_NAME_EXPANSIONS)
    if country_code:
        vocabulary.update(COUNTRY_PLANT_NAME_EXPANSIONS.get(country_code, {}))
    return vocabulary


def strip_vocabulary_glued(token: str, vocabulary: dict[str, str]) -> str:
    """Repeatedly strip a known vocabulary word off the start or end of `token`.

    Only whole vocabulary words of length >= MIN_STRIP_WORD_LEN are
    considered (see module docstring for why short 2-letter entries are
    excluded here). Returns the residual token, unchanged if nothing strips.
    """
    words = sorted(
        (w for w in vocabulary if len(w) >= MIN_STRIP_WORD_LEN),
        key=len,
        reverse=True,
    )
    current = token
    changed = True
    while changed and current:
        changed = False
        for word in words:
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


def tokenize_and_expand(name: Optional[str], country_code: Optional[str]) -> list[str]:
    """Normalize, split, and expand/strip each token against the vocabulary.

    Exact vocabulary-key tokens (e.g. "he", "unit") expand to their mapped
    value (split into separate tokens if multi-word, e.g. "ej" -> "power
    plant elektrijaam" -> 3 tokens). Non-vocabulary tokens are passed through
    the bidirectional glued-name stripper as a fallback.
    """
    vocabulary = build_vocabulary(country_code)
    normalized = normalize_name(name)
    if not normalized:
        return []

    out: list[str] = []
    for tok in normalized.split():
        if tok in vocabulary:
            out.extend(vocabulary[tok].split())
        else:
            stripped = strip_vocabulary_glued(tok, vocabulary)
            out.append(stripped if stripped else tok)
    return out


def token_weight(token: str, vocabulary: dict[str, str]) -> float:
    """Dictionary-based token importance weight (no corpus-frequency stats).

    - Exact vocabulary key (generic unit/plant-type word) -> LOW_WEIGHT
    - Short alphanumeric unit-designator pattern (g1, u2, bare digits) -> LOW_WEIGHT
    - Everything else (presumed discriminative place/plant name) -> DEFAULT_WEIGHT
    """
    if token in vocabulary:
        return LOW_WEIGHT
    if UNIT_DESIGNATOR_RE.match(token):
        return LOW_WEIGHT
    return DEFAULT_WEIGHT


@dataclass(frozen=True)
class WeightedTokens:
    """A name decomposed into tokens paired with their importance weights."""

    tokens: tuple[str, ...]
    weights: tuple[float, ...]


def weighted_tokenize(
    name: Optional[str], country_code: Optional[str]
) -> WeightedTokens:
    """Tokenize + expand `name`, then weight each resulting token."""
    vocabulary = build_vocabulary(country_code)
    tokens = tuple(tokenize_and_expand(name, country_code))
    weights = tuple(token_weight(tok, vocabulary) for tok in tokens)
    return WeightedTokens(tokens=tokens, weights=weights)


def weighted_token_score(target: WeightedTokens, candidate: WeightedTokens) -> float:
    """Weighted-average best-token-match score between two WeightedTokens, 0-100.

    Each target token is matched against its best-fitting candidate token via
    rapidfuzz.ratio, weighted by importance, normalized by total weight.
    Rewards true discriminative-name matches far more than incidental
    matches on generic/low-weight tokens (e.g. two different plants both
    having a "g1" unit).
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
