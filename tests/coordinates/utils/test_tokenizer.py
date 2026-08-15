# tests/coordinates/utils/test_tokenizer.py
"""Tests for the source-agnostic name tokenizer/weighting used by NameMatcher."""

import pytest

from rbc.coordinates.utils.tokenizer import (
    DEFAULT_WEIGHT,
    LOW_WEIGHT,
    NameTokenizer,
    build_vocabulary,
    get_weighted_token_score,
    normalize_name,
    strip_numeric_tokens,
    strip_trailing_unit_suffix,
)


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def tok_none() -> NameTokenizer:
    """Returns a tokenizer with no country-specific vocabulary.

    Returns:
        NameTokenizer: Tokenizer built without a country code.
    """
    return NameTokenizer(country_code=None)


@pytest.fixture
def tok_ee() -> NameTokenizer:
    """Returns a tokenizer with the Estonian vocabulary ("ej" -> "power plant ...").

    Returns:
        NameTokenizer: Tokenizer built for "EE".
    """
    return NameTokenizer(country_code="EE")


@pytest.fixture
def tok_de() -> NameTokenizer:
    """Returns a tokenizer with the German vocabulary ("kraftwerk", ...).

    Returns:
        NameTokenizer: Tokenizer built for "DE".
    """
    return NameTokenizer(country_code="DE")


# ----------------------------------
# Tests - module-level string helpers
# ----------------------------------
class TestNormalizeName:
    """Tests for normalize_name."""

    def test_normalize_name_basic(self) -> None:
        """Happy path: lowercases, strips diacritics, collapses non-alphanumeric runs."""
        assert normalize_name("  Čapljina HPP-Unit 5!  ") == "capljina hpp unit 5"
        assert normalize_name(None) == ""
        assert normalize_name("") == ""

    @pytest.mark.parametrize(
        "value",
        [
            "Auvere EJ",
            "  Balti G09 ",
            "Ünïcodé Näme",
            "ENGURIUNIT_5",
            "KW Boxberg Block Q",
        ],
    )
    def test_normalize_name_is_idempotent(self, value: str) -> None:
        """Regression pin: normalizing an already-normalized name is a no-op.

        Callers routinely hand already-normalized names back in --
        NameTokenizer.weighted_tokenize passes its own `normalized` into
        tokenize(), and NameMatcher passes `candidate.normalized` into
        weighted_tokenize(). All of that is only correct while this holds.

        Args:
            value (str): Raw name to normalize twice.
        """
        once = normalize_name(value)
        assert normalize_name(once) == once


class TestStripHelpers:
    """Tests for strip_numeric_tokens and strip_trailing_unit_suffix."""

    def test_strip_numeric_tokens_drops_unit_markers(self) -> None:
        """Happy path: digits and generic unit tokens are dropped, place name survives.

        Used as a station-level fallback where the sysop name carries a unit
        number but OSM only stores the plant (e.g. just "Sloecentrale").
        """
        assert strip_numeric_tokens("Sloecentrale unit 20") == "sloecentrale"

    def test_strip_numeric_tokens_all_generic_returns_empty(self) -> None:
        """Failure path: a fully generic name reduces to an empty string."""
        assert strip_numeric_tokens("Unit 1") == ""
        assert strip_numeric_tokens("") == ""

    def test_strip_trailing_unit_suffix_splits_glued_suffix(self) -> None:
        """Happy path: a unit suffix glued onto the name with no separator is stripped.

        "ENGURIUNIT_5" tokenizes as one glued token, so strip_numeric_tokens
        cannot catch it -- this regex-based pass can.
        """
        assert strip_trailing_unit_suffix("ENGURIUNIT_5") == "enguri"

    def test_strip_trailing_unit_suffix_no_suffix_returns_empty(self) -> None:
        """Failure path: a name with no recognized unit suffix yields an empty string.

        Empty (not the input) signals "no alternative variant to try", so the
        caller does not add a duplicate of the original name.
        """
        assert strip_trailing_unit_suffix("Riverside") == ""


class TestGetWeightedTokenScore:
    """Tests for get_weighted_token_score."""

    def test_high_score(self, tok_ee: NameTokenizer) -> None:
        """Happy path: Matching a name's tokens against itself scores 100.

        Args:
            tok_ee (NameTokenizer): Tokenizer for "EE".
        """
        tokens = tok_ee.weighted_tokenize("Auvere EJ- G1")
        assert get_weighted_token_score(tokens, tokens) == 100.0

    def test_high_score_when_partial_with_high_weight(
        self, tok_ee: NameTokenizer
    ) -> None:
        """Happy path: A strong token match dominates the weighted score.

        A strong-matching discriminative token plus one non-matching low-weight token should
        still score high, since the low-weight token is suppressed by its small contribution.

        Args:
            tok_ee (NameTokenizer): Tokenizer for "EE".
        """
        target = tok_ee.weighted_tokenize("Auvere G1")
        candidate = tok_ee.weighted_tokenize("Auvere G7")
        assert get_weighted_token_score(target, candidate) > 80.0

    def test_low_score_when_partial_with_low_weight(
        self, tok_ee: NameTokenizer
    ) -> None:
        """Happy case: A generic token match (shared) alone must not drive up the score.

        Two unrelated plants sharing only a low-weight generic descriptor must NOT score high.

        Args:
            tok_ee (NameTokenizer): Tokenizer for "EE".
        """
        target = tok_ee.weighted_tokenize("Auvere G1")
        candidate = tok_ee.weighted_tokenize("Narva G1")
        assert get_weighted_token_score(target, candidate) < 50.0

    def test_zero_score_when_empty_inputs(self, tok_none: NameTokenizer) -> None:
        """Failure path: An empty token set on either side scores 0, not an error.

        Args:
            tok_none (NameTokenizer): Tokenizer without country vocabulary.
        """
        empty = tok_none.weighted_tokenize("")
        non_empty = tok_none.weighted_tokenize("Auvere")
        assert get_weighted_token_score(empty, non_empty) == 0.0
        assert get_weighted_token_score(non_empty, empty) == 0.0


# ----------------------------------
# Tests - build_vocabulary
# ----------------------------------
class TestBuildVocabulary:
    """Tests for build_vocabulary."""

    def test_country_specific_vocabulary(self) -> None:
        """Happy path: country-specific vocabulary entries only apply to their country."""
        ee_vocab = build_vocabulary("EE")
        default_vocab = build_vocabulary(None)
        de_vocab = build_vocabulary("DE")
        assert "ej" in ee_vocab
        assert "ej" not in default_vocab
        assert "ej" not in de_vocab
        assert "kraftwerk" in de_vocab
        assert "kraftwerk" not in ee_vocab

    def test_vocabulary_is_shared_between_instances(self) -> None:
        """Happy path: lru_cached, so instances share one dict, not a copy (no rebuilding).

        Vocabulary must be treated as read-only. Mutating it through one tokenizer would
        corrupt every other one in the process, therefore the private `_vocabulary`.
        """
        assert NameTokenizer("EE")._vocabulary is NameTokenizer("EE")._vocabulary


# ----------------------------------
# Tests - NameTokenizer
# ----------------------------------
class TestNameTokenizerTokenize:
    """Tests for NameTokenizer.tokenize."""

    def test_split_and_expand_vocab_keys(self, tok_ee: NameTokenizer) -> None:
        """Happy path: Exact vocabulary keys expand to their (multi-word) meaning.

        Args:
            tok_ee (NameTokenizer): Tokenizer for "EE".
        """
        tokens = tok_ee.tokenize("Auvere EJ- G1")
        assert tokens == ["auvere", "power", "plant", "elektrijaam", "g1"]

    def test_split_glued_name(self, tok_none: NameTokenizer) -> None:
        """Happy path: A glued vocabulary word is stripped off a non-vocabulary token.

        "hpp" is not in any current dictionary, so only the trailing "unit"
        strips -- this pins the actual (documented) gap, not the aspirational
        "river" result. If "hpp" is ever added to GENERIC_UNIT_TOKENS, this
        assertion should flip to "river".

        Args:
            tok_none (NameTokenizer): Tokenizer without country vocabulary.
        """
        assert tok_none.tokenize("hppriverunit") == ["hppriver"]

    @pytest.mark.parametrize(
        "name",
        ["riverside", "auvere", "unit"],
        ids=["no_overlap", "only_short_words_match", "is_vocab_word_itself"],
    )
    def test_no_split(self, tok_none: NameTokenizer, name: str) -> None:
        """Happy path: No name split/stripping if nothing matches or a special case applies.

        1. The name has no overlap with the vocabulary.
        2. Only short words match (nothing >= 3 letters) -> no accidental stripping!
        3. The name itself is a whole vocabulary word.

        Args:
            tok_none (NameTokenizer): Tokenizer without country vocabulary.
            name (str): The name that is input and output of tokenization.
        """
        assert tok_none.tokenize(name) == [name]

    def test_no_tokens_when_empty(self, tok_none: NameTokenizer) -> None:
        """Failure path: missing/blank names tokenize to an empty list, not an error.

        Args:
            tok_none (NameTokenizer): Tokenizer without country vocabulary.
        """
        assert tok_none.tokenize(None) == []
        assert tok_none.tokenize("   ") == []


class TestNameTokenizerWeights:
    """Tests for NameTokenizer token weighting."""

    @pytest.mark.parametrize(
        "name, t1, t2, score",
        [
            ("Auvere EJ- G1", "auvere", "g1", 49),
            ("Auvere G1", "auvere", "g1", 91),
            ("Neurath F", "neurath", "f", 91),
        ],
    )
    def test_tokenize_weight(
        self, tok_ee: NameTokenizer, name: str, t1: str, t2: str, score: int
    ) -> None:
        """Happy path: The discriminative place name outweighs the generic EGE descriptor.

        Args:
            tok_ee (NameTokenizer): Tokenizer for "EE".
            name (str): The name to get tokens and their weights for.
            t1 (str): An extracted token #1 with high weight.
            t2 (str): An extracted token #2 with low weight.
            score (int): The score that the weighted tokens will achieve.
        """
        wt = tok_ee.weighted_tokenize(name)
        weights = dict(zip(wt.tokens, wt.weights))
        assert weights[t1] == DEFAULT_WEIGHT
        assert weights[t2] == LOW_WEIGHT
        assert (
            round(get_weighted_token_score(wt, tok_ee.weighted_tokenize(t1))) == score
        )


class TestNameTokenizerCache:
    """Tests for NameTokenizer's weighted-token cache."""

    def test_cache_returns_repeatedly(self, tok_ee: NameTokenizer) -> None:
        """Happy path: the cache (read-through) returns the same object each time.

        Args:
            tok_ee (NameTokenizer): Tokenizer for "EE".
        """
        first = tok_ee.weighted_tokenize("Auvere EJ")
        assert tok_ee.weighted_tokenize("Auvere EJ") is first

    def test_cache_key_is_normalized_name(self, tok_ee: NameTokenizer) -> None:
        """Happy path: Different names that resolve to same normalization share one entry.

        Args:
            tok_ee (NameTokenizer): Tokenizer for "EE".
        """
        first = tok_ee.weighted_tokenize("Auvere EJ")
        assert tok_ee.weighted_tokenize("  auvere   ej  ") is first
        assert list(tok_ee._weighted_cache) == ["auvere ej"]

    def test_caches_are_not_shared_between_instances(self) -> None:
        """Failure path: Each tokenizer owns its cache, so per-init state cannot leak."""
        first, second = NameTokenizer("EE"), NameTokenizer("EE")
        first.weighted_tokenize("Auvere EJ")
        assert second._weighted_cache == {}
