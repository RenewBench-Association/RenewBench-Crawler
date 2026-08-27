"""Source-agnostic name tokenization and token-weighted scoring.

Splits an EGE name into weighted tokens so that a discriminative place/EGE name (e.g.
"auvere") counts far more toward a match score than a generic EGE-type word (e.g. "unit",
"g1", "he"). Used by NameMatcher to compare a target name against PPM/GEM/OSM candidate
names via the same tokenize-and-weight function on both sides, instead of each candidate
source expanding its own names ad hoc.

Weighting is dictionary-based only (GENERIC_UNIT_TOKENS / GENERIC_ENERGY_TOKENS from
mappings.py & per-operator/country name_mapping translations).
"""

import re
from dataclasses import dataclass
from pprint import pformat

from loguru import logger
from rapidfuzz import fuzz

from rbc.coordinates.mappings import GENERIC_ENERGY_TOKENS, GENERIC_UNIT_TOKENS
from rbc.coordinates.utils.values import normalize_name


@dataclass(frozen=True)
class WeightedTokens:
    """A name decomposed into its tokens and their importance weights."""

    tokens: tuple[str, ...]
    weights: tuple[float, ...]

    def as_str(self) -> str:
        """Returns class instances as string in the format "'t1':w1, 't2':w2, ...".

        Returns:
            str: formatted class instance as string.
        """
        return ", ".join(f"'{t}':{w:g}" for t, w in zip(self.tokens, self.weights))


# ---------------------------------------------------------------------------
# Independent functions (pure string operators - no vocab, no country)
# ---------------------------------------------------------------------------
NORM_GENERIC_UNIT_TOKENS = [normalize_name(t) for t in GENERIC_UNIT_TOKENS]
JOINED_GENERIC_UNIT_TOKENS = "|".join(t for t in NORM_GENERIC_UNIT_TOKENS if len(t) > 1)
NORM_GENERIC_ENERGY_TOKENS = [normalize_name(t) for t in GENERIC_ENERGY_TOKENS]

ROMAN_UNIT_NUMERALS: frozenset[str] = frozenset(
    "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split()
)


def strip_separate_generic_tokens(normalized: str | None) -> str:
    """Strip trailing generic tokens/digits from the normalized EGE name.

    This is a last-resort fallback for cases where names include unit numbers and / or generic
    unit markers (e.g. "Ensuri Unit 20", "Sloecentrale Block II") but locators only store the
    station-level name without a per-unit suffix (e.g. just "Ensuri" or "Sloecentrale").

    Args:
        normalized (str | None): The previously normalized name to process.

    Returns:
        str: Name with numeric tokens and generic unit tokens removed, or the input
            unchanged if it carries none of them.
    """
    if not normalized:
        return ""

    tokens = [
        token
        for token in normalized.split()
        if not token.isdigit()
        and token not in NORM_GENERIC_UNIT_TOKENS
        and token not in ROMAN_UNIT_NUMERALS
    ]
    return " ".join(tokens).strip()


def strip_glued_generic_tokens(normalized: str | None) -> str:
    """Strip trailing generic tokens (units) glued to the normalized EGE name.

    This is another last-resort fallback. Some naming conventions add the unit suffix
    directly onto the EGE name with no separating space/underscore (e.g. "ENGURIUNIT_5").
    The space-tokenized strip_generic_tokens won't catch these since "enguriunit" and "5"
    remain a single glued token. This is done here (e.g. "ENGURIUNIT_5" -> "enguri").

    Args:
        normalized (str | None): The previously normalized name to process.

    Returns:
        str: The name with the trailing unit-suffix removed, or the input unchanged
            if it doesn't end in a recognized unit-suffix.
    """
    if not normalized:
        return ""

    # use regex pattern based on |-joined generic unit tokens
    return re.sub(rf"(?:{JOINED_GENERIC_UNIT_TOKENS})\s*\d*$", "", normalized).strip()


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
        float: Best weighted-average token match score.
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
EXCLUDE_WEIGHT = 0.0
DEMOTE_WEIGHT = 0.1
DEFAULT_WEIGHT = 1.0

# Short alphanumeric patterns for designating units that are not caught by the vocabulary:
# - letters+digits (e.g. "g1"/"u2"),
# - bare digits (e.g. "3"),
# - bare 1-2 letter blocks (e.g. "q"/"aa"  in "KW Boxberg Block Q"/"Neurath AA")
_SHORT_EGE_DESCRIPTOR_PATTERNS = re.compile(
    r"^(?:[a-z]{1,4}\d{1,3}|\d{1,3}|[a-z]{1,2})$"
)


class NameTokenizer:
    """Vocabulary-driven tokenization and weighting for one country."""

    def __init__(self, name_mapping: dict[str, str] | None = None) -> None:
        """Initialize the name-tokenizer class.

        Args:
            name_mapping (dict | None): The mapping dict of operator/country-specific non-
                english names and their meanings to use for building the vocabulary.
                Defaults to None.
        """
        # build vocabulary lookups
        self._exclude_vocabulary: list[str] = NORM_GENERIC_UNIT_TOKENS
        self._demote_vocabulary: dict[str, str] = {
            t: t for t in NORM_GENERIC_ENERGY_TOKENS
        }
        if name_mapping:
            self._demote_vocabulary.update(
                {normalize_name(k): normalize_name(v) for k, v in name_mapping.items()}
            )

        # build lists of vocabulary words for specific comparisons
        # 2. exclusion words: those that have more than 3 characters (no 2-letter codes!)
        self._exclude_words: list[str] = sorted(
            (w for w in self._exclude_vocabulary if len(w) >= 3),
            key=len,
            reverse=True,
        )
        # 1. demotion words: the individual values of the key-value pair dict
        self._demote_words: frozenset[str] = frozenset(
            w for v in self._demote_vocabulary.values() for w in v.split()
        )

        # Cache to store name's tokens and their weights: normalized_name -> WeightedTokens
        self._weighted_cache: dict[str, WeightedTokens] = {}

        logger.info(
            f"NameTokenizer initialized with:\n"
            f"-\texcluded vocabulary: list of {len(self._exclude_vocabulary)} with "
            f"{len(self._exclude_words)} words (for strip-glue removal)\n"
            f"-\tdemoted vocabulary: dict of {len(self._demote_vocabulary)} with "
            f"{len(self._demote_words)} words (for adding & weighting tokens)"
        )
        logger.debug(
            f"NameTokenizer initialized with:\n"
            f"{pformat(vars(self), indent=4, sort_dicts=False)}"
        )

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------
    def tokenize(self, name: str | None) -> list[str]:
        """Normalize name, split into tokens and expand/strip each token using the vocabulary.

        Exact vocabulary-keys (e.g. "he", "unit") expand to their mapped vocab value and are
        split into separate if multi-word (e.g. "ej" -> "power plant" -> 2 tok).
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
            if tok in self._exclude_vocabulary:
                out.append(tok)
            elif tok in self._demote_vocabulary:
                out.extend(self._demote_vocabulary[tok].split())
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

        - Exact exclude_vocabulary value (generic unit/plant-type word) -> EXCLUDE_WEIGHT
        - Exact demote_words value (generic energy word & fuel types) -> DEMOTE_WEIGHT
        - Short alphanumeric unit-designator pattern (g1, u2, bare digits) -> DEMOTE_WEIGHT
        - Everything else (presumed discriminative place/EGE name) -> DEFAULT_WEIGHT

        Args:
            token (str): The token to calculate weight for.

        Returns:
            float: The weight of the token.
        """
        if token in self._exclude_vocabulary:
            return EXCLUDE_WEIGHT
        if token in self._demote_words:
            return DEMOTE_WEIGHT
        if _SHORT_EGE_DESCRIPTOR_PATTERNS.match(token):
            return DEMOTE_WEIGHT
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
            for word in self._exclude_words:
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
