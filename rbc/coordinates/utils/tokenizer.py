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
from typing import Literal

from loguru import logger
from rapidfuzz import fuzz

from rbc.coordinates.mappings import GENERIC_ENERGY_TOKENS, GENERIC_UNIT_TOKENS
from rbc.coordinates.utils.values import normalize_name

NORM_GENERIC_UNIT_TOKENS = [normalize_name(t) for t in GENERIC_UNIT_TOKENS]
NORM_GENERIC_ENERGY_TOKENS = [normalize_name(t) for t in GENERIC_ENERGY_TOKENS]

# Pattern: Find a generic unit word (+ number) glued onto the end of a token (> 3 chars)
# (e.g. "enguriunit" -> "enguri unit" / "sloeunit10" -> "sloe unit 10").
JOINED_GENERIC_UNIT_TOKENS = "|".join(
    sorted((t for t in NORM_GENERIC_UNIT_TOKENS if len(t) > 3), key=len, reverse=True)
)
GLUED_GENERIC_TOKEN_PATTERN = re.compile(
    rf"\b([a-z]{{3,}})({JOINED_GENERIC_UNIT_TOKENS})(\d{{0,3}})\b"
)
ROMAN_UNIT_NUMERALS: frozenset[str] = frozenset(
    "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split()
)

EXCLUDE_WEIGHT = 0.0
DEMOTE_WEIGHT = 0.1
DESIGNATOR_WEIGHT = 0.15  # tokens that are unit designators (e.g. '6', 'III', 'G1')
FULL_WEIGHT = 1.0  # discriminative tokens - true names we need to match!

if not FULL_WEIGHT > DESIGNATOR_WEIGHT > DEMOTE_WEIGHT > EXCLUDE_WEIGHT:
    raise ValueError("Error in defining global weight parameters!")


# ---------------------------------------------------------------------------
# Independent functions (no vocab, no country) - pure string operators
# ---------------------------------------------------------------------------
def split_camelcase(raw: str | None) -> str:
    """Split a CamelCase name into its true separate words as a EGE and rejoined with space.

    Some operators glue separate words together to build names ("ChePortileDeFier" -> "Che
    Portile De Fier"). These would become as one long meaningless token, so are split here.

    Args:
        raw (str | None): The raw (un-normalized) name to split.

    Returns:
        str: The name now split by spaces between camelCase words or '' if no changes.
    """
    if not raw or not (any(c.islower() for c in raw) and any(c.isupper() for c in raw)):
        return ""

    prev_lower = False  # whether the previous char was lowercase or not
    split_idxs = [0]  # index to use for splitting

    for idx, char in enumerate(raw):
        if prev_lower and char.isupper():
            split_idxs.append(idx)
        prev_lower = char.islower()

    tokens = [raw[i:j] for i, j in zip(split_idxs, split_idxs[1:] + [None])]
    new = " ".join(tokens).strip()
    return new if new != raw else ""


def split_glued_generic_tokens(normalized: str | None) -> str:
    """Split generic unit words glued onto the normalized EGE name into separate tokens.

    Some naming conventions add the unit word directly onto the EGE name with no separating
    space/underscore (e.g. "ENGURIUNIT_5", "energoblok 3"), leaving one long token that
    matches nothing. This splits the parts apart rather than dropping them, so the variant
    loses no information: the stem stays discriminative, the generic word is zero-weighted
    by the tokenizer anyway, and the unit number survives to tell sibling units apart
    (e.g. "ENGURIUNIT_5" -> "enguri unit 5", not "enguri").

    Args:
        normalized (str | None): The previously normalized name to process.

    Returns:
        str: The name with glued unit words split out or '' if no changes.
    """
    if not normalized:
        return ""

    new = GLUED_GENERIC_TOKEN_PATTERN.sub(
        lambda m: " ".join(group for group in m.groups() if group), normalized
    )
    return new if new != normalized else ""


# ---------------------------------------------------------------------------
# Independent functions (no vocab, no country) - weight calculation
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class WeightedTokens:
    """A name decomposed into its tokens and their importance weights."""

    tokens: tuple[str, ...]
    weights: tuple[float, ...]
    types: tuple[Literal["generic", "designator", "discriminator"], ...]  # tok type

    def as_str(self) -> str:
        """Returns instances as a string in the format "'tok1':w1, 'tok2':w2".

        Returns:
            str: formatted class instance as string.
        """
        return ", ".join(f"'{t}':{w:g}" for t, w in zip(self.tokens, self.weights))


def get_weighted_token_score(
    target: WeightedTokens, candidate: WeightedTokens, fuzz_ratio_floor: float = 60.0
) -> tuple[float, float]:
    """Get the weighted-average best-token-match score between two WeightedTokens (0-100).

    Each token in the target is matched against its best-fitting candidate token via
    rapidfuzz.ratio (weighted by importance and normalized by total weight).
    True distinctive name matches are rewarded far more than incidental matches on generic
    (low-weight) tokens (e.g. two different EGEs both having "g1" are not weighted highly).

    For reference, some examples for rapidfuzz.ratio results for different combinations.
    Ratio retruns a float strictly in [0, 100]:
        - no same letter:       fuzz.ratio("flores", "maua") = 0
        - one same letter:      fuzz.ratio("flores", "jaraqui") = ~15
        - few same letters:     fuzz.ratio("turceni", "isalnita") = ~25
        - same letters mixed:   fuzz.ratio("flores", "sofler") = 50
        - same ending:          fuzz.ratio("tambaqui", "jaraqui") = ~65
        - one vowel diff:       fuzz.ratio("flores", "floras") = ~80
        - one extra letter:     fuzz.ratio("auvere", "auverre") = ~90
        - identical:            fuzz.ratio("turceni", "turceni") = 100

    Args:
        target (WeightedTokens): WeightedTokens to score.
        candidate (WeightedTokens): WeightedTokens to score.
        fuzz_ratio_floor (float, optional): The minimum rapidfuzz ratio for a token pair
            to count. If below it, the score is 0 (no partial credit). 100.0 is an exact
            match; 0.0 disables the rule (meaning completely different tokens match).
            Defaults to 60.0.

    Returns:
        tuple[float, float]: True best weighted token match score,
            and the debugging score (what the score would have been without the vetoes)
    """
    if not target.tokens or not candidate.tokens or sum(target.weights) <= 0:
        return 0.0, 0.0

    if not 0.0 <= fuzz_ratio_floor <= 100.0:
        logger.error(
            f"fuzz_ratio_floor is set as '{fuzz_ratio_floor}', which is outside the range "
            f"of (0, 100). Using the argument default '50.0' instead..."
        )
        fuzz_ratio_floor = 50.0

    # if a target doesn't have any discriminative (full weight) tokens, it can't be matched!
    target_has_discriminator = any(t == "discriminator" for t in target.types)
    if not target_has_discriminator:
        return 0.0, 0.0

    candidate_has_designator = any(t == "designator" for t in candidate.types)
    target_discriminator_matched = False
    weighted_sum = 0.0  # score numerator
    counted_weight = 0.0  # score denominator

    for tok, weight, ttype in zip(target.tokens, target.weights, target.types):
        max_ratio = max((fuzz.ratio(tok, c) for c in candidate.tokens), default=0.0)

        # if ratio is below the limit, the two tokens are too dissimilar to be a match!
        if max_ratio < fuzz_ratio_floor:
            max_ratio = 0.0
        elif ttype == "discriminator":
            target_discriminator_matched = True

        weighted_sum += weight * max_ratio

        # add the token's weight to denominator IF it's discriminative / a unit designator
        # OR if it was matched -> prevents unmatched generic target tokens diluting the score
        if (
            ttype == "discriminator"
            or (ttype == "designator" and candidate_has_designator)
            or max_ratio > 0
        ):
            counted_weight += weight

    score = weighted_sum / counted_weight if counted_weight > 0.0 else 0.0

    # ensure that at least one discriminative (full weight) token was matched
    if not target_discriminator_matched:
        return 0.0, score

    return score, score


# ---------------------------------------------------------------------------
# Country-/vocabulary-based class functionality
# ---------------------------------------------------------------------------
class NameTokenizer:
    """Vocabulary-driven tokenization and weighting for one country."""

    # Pattern: split a glued unit number off the end of a token >= 3 chars (e.g. "turc4")
    _GLUED_UNIT_NUMBER_PATTERN = re.compile(r"([a-z]{3,})(\d{1,3})")

    # Pattern: short alphanumeric combinations to identify unit designations:
    # - letter(s)+digit(s) (e.g. "g1", "u2", "uni2"),
    # - digit(s)+letter (e.g. "5a")
    # - bare digits (e.g. "3"),
    # - bare 1-2 letter blocks (e.g. "q"/"aa"  in "KW Boxberg Block Q"/"Neurath AA")
    _UNIT_DESIGNATOR_PATTERNS = re.compile(
        r"^(?:[a-z]{1,3}\d{1,3}|\d{1,3}[a-z]|\d{1,3}|[a-z]{1,2})$"
    )

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
        # 1. exclusion words: those with more than 3 characters (no "g"/"gen") for stripping
        self._exclude_words: list[str] = sorted(
            (w for w in self._exclude_vocabulary if len(w) > 3),
            key=len,
            reverse=True,
        )
        # 2. demotion words: the individual values of the key-value pairs (the vocab dict)
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

        # split into tokens: by space (" ") and by glued units at token ends
        tokens = normalized.split()
        tokens = self._split_glued_unit_number(tokens)

        out: list[str] = []
        for tok in tokens:
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
        types, weights = (
            zip(*(self._get_type_and_weight(t) for t in tokens)) if tokens else ((), ())
        )

        result = WeightedTokens(tokens, weights, types)
        self._weighted_cache[normalized] = result
        return result

    # ---------------------------------------------------------------------------
    # Helper methods: tokenize
    # ---------------------------------------------------------------------------
    def _split_glued_unit_number(self, tokens: list[str]) -> list[str]:
        """Split a trailing unit number off its letter stem ("turc3" -> "turc", "3").

        This is included here in the class so that it is applied to ALL target variants!
        Operators glue unit numbers onto a name fragment, which is otherwise counted - and
        potentially demoted - as one token, so the name is lost. This method:
        - splits a token (with >= 3 chars & trailing number) into two separate tokens, e.g.
            tokens: ("turc3") -> name: "turc", unit designator: "3"
            tokens: ("mint5") -> name: "mint", unit designator: "5"
        - skip names where a fuller version already exists (including the abbreviation
          adds a full-weight token that brings score down):
            tokens: ("isalnita, isal8") -> name: "isalnita", unit designator: "8"

        Args:
            tokens (list[str]): Normalized tokens of one name.

        Returns:
            list[str]: Tokens with glued unit numbers split out.
        """
        out: list[str] = []
        for tok in tokens:
            match = self._GLUED_UNIT_NUMBER_PATTERN.fullmatch(tok)
            if match:
                name, designator = match.groups()
                in_other_tok = any(t != tok and t.startswith(name) for t in tokens)
                out.extend([name, designator] if not in_other_tok else [designator])
            else:
                out.append(tok)

        return out

    def _strip_glued(self, token: str) -> str:
        """Repeatedly strip known vocabulary words off the start or end of a token.

        Only whole unit-related vocabulary words of length > 3 are considered. This prevents
        2-letter
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

    # ---------------------------------------------------------------------------
    # Helper methods: weighting
    # ---------------------------------------------------------------------------
    def _get_type_and_weight(self, token: str) -> tuple[str, float]:
        """Dictionary-based token classification (importance) and derived weight.

        - Exact exclude_vocabulary value (generic unit/plant-type word) -> EXCLUDE_WEIGHT
        - Exact demote_words value (generic energy word & fuel types) -> DEMOTE_WEIGHT
        - Short alphanumeric unit-designator pattern ('u1', '3') -> DESIGNATOR_WEIGHT
        - Everything else (presumed discriminative place/EGE name) -> FULL_WEIGHT

        Args:
            token (str): The token to calculate type and weight for.

        Returns:
            str, float: The token classification and its derived weight.
        """
        if token in self._exclude_vocabulary:
            return "generic", EXCLUDE_WEIGHT
        if token in self._demote_words:
            return "generic", DEMOTE_WEIGHT
        if self.is_unit_designator(token):
            return "designator", DESIGNATOR_WEIGHT
        return "discriminator", FULL_WEIGHT

    def is_unit_designator(self, token: str) -> bool:
        """Whether a token designates a unit (number/letter) rather than describing it.

        Args:
            token (str): The token to check.

        Returns:
            bool: Whether the token is a unit designator. True if it is.
        """
        return (
            bool(self._UNIT_DESIGNATOR_PATTERNS.match(token))
            or token in ROMAN_UNIT_NUMERALS
        )
