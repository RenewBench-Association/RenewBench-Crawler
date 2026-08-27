# tests/coordinates/utils/test_tokenizer.py
"""Tests for the source-agnostic name tokenizer/weighting used by NameMatcher."""

import pytest

from rbc.coordinates.utils.tokenizer import (
    DEFAULT_WEIGHT,
    DEMOTE_WEIGHT,
    EXCLUDE_WEIGHT,
    NameTokenizer,
    get_weighted_token_score,
    normalize_name,
    strip_glued_generic_tokens,
    strip_separate_generic_tokens,
)

# Synthetic vocabulary, deliberately NOT imported from rbc.energy.<operator>.mappings:
# these tests pin the tokenizer's mechanics, not the operators' evolving word lists.
TEST_VOCAB: dict[str, str] = {
    "elektrijaam": "power plant",  # multi-word value, both words already generic
    "ej": "power plant elektrijaam",  # value re-using another vocabulary key
    "pumpspeicherkraftwerk": "pumped hydro",  # value word that is NOT a generic token
    "Kraftværk": "power plant",  # accented + capitalized key
    "Barragem da Usina": "dam",  # multi-word key -> unreachable by design
}


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def tok_plain() -> NameTokenizer:
    """Returns a tokenizer with no operator/country vocabulary.

    Returns:
        NameTokenizer: Tokenizer built with generic token sets only.
    """
    return NameTokenizer()


@pytest.fixture
def tok_vocab() -> NameTokenizer:
    """Returns a tokenizer carrying TEST_VOCAB on top of the generic token sets.

    Returns:
        NameTokenizer: Tokenizer built with a name_mapping.
    """
    return NameTokenizer(name_mapping=TEST_VOCAB)


# ----------------------------------
# Tests - module-level string helpers
# ----------------------------------
class TestStripHelpers:
    """Tests for strip_trailing_generic and strip_trailing_glued_generic.

    Both expect an already-normalized name, so every case feeds them through
    normalize_name first -- exactly as _generate_target_variants does.
    """

    def test_strip_trailing_generic_drops_unit_markers(self) -> None:
        """Happy path: Digits and generic unit tokens are dropped, place name survives.

        Used as a station-level fallback where the sysop name carries a unit
        number but OSM only stores the plant (e.g. just "Sloecentrale").
        """
        assert (
            strip_separate_generic_tokens(normalize_name("Sloecentrale unit 20"))
            == "sloecentrale"
        )

    @pytest.mark.parametrize("value", ["Unit 1", "Block III", ""])
    def test_strip_trailing_generic_all_generic_returns_empty(self, value: str) -> None:
        """Failure path: A fully generic name reduces to an empty string.

        Args:
            value (str): Name consisting only of generic/numeric/roman-numeral tokens.
        """
        assert strip_separate_generic_tokens(normalize_name(value)) == ""

    def test_strip_trailing_generic_raw_input_is_not_stripped(self) -> None:
        """Failure path: Un-normalized input silently survives, since matching is lowercase.

        Pins the caller's obligation: NORM_GENERIC_UNIT_TOKENS holds lowercase tokens, so
        "Unit" never matches and a raw name comes back only half-stripped.
        """
        assert (
            strip_separate_generic_tokens("Sloecentrale Unit 20") == "Sloecentrale Unit"
        )

    def test_strip_trailing_glued_generic_splits_glued_suffix(self) -> None:
        """Happy path: A unit suffix glued onto the name with no separator is stripped.

        "ENGURIUNIT_5" normalizes to one glued token "enguriunit 5", which
        strip_trailing_generic cannot split -- this regex-based pass can.
        """
        assert strip_glued_generic_tokens(normalize_name("ENGURIUNIT_5")) == "enguri"

    def test_strip_trailing_glued_generic_no_suffix_returns_input(self) -> None:
        """Failure path: A name with no recognized unit suffix comes back unchanged.

        Harmless because _generate_target_variants de-duplicates variants, so an
        unchanged name is simply not added a second time.
        """
        assert strip_glued_generic_tokens(normalize_name("Riverside")) == "riverside"


class TestGetWeightedTokenScore:
    """Tests for get_weighted_token_score."""

    def test_high_score(self, tok_vocab: NameTokenizer) -> None:
        """Happy path: Matching a name's tokens against itself scores 100.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        tokens = tok_vocab.weighted_tokenize("Auvere EJ- G1")
        assert get_weighted_token_score(tokens, tokens) == 100.0

    def test_high_score_when_partial_with_high_weight(
        self, tok_vocab: NameTokenizer
    ) -> None:
        """Happy path: A strong token match dominates the weighted score.

        A strong-matching discriminative token plus one non-matching low-weight token should
        still score high, since the low-weight token is suppressed by its small contribution.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        target = tok_vocab.weighted_tokenize("Auvere G1")
        candidate = tok_vocab.weighted_tokenize("Auvere G7")
        assert get_weighted_token_score(target, candidate) > 80.0

    def test_low_score_when_partial_with_low_weight(
        self, tok_vocab: NameTokenizer
    ) -> None:
        """Happy path: A shared generic token alone must not drive up the score.

        Two unrelated plants sharing only a low-weight generic descriptor must NOT
        score high -- this is the whole point of the weighting.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        target = tok_vocab.weighted_tokenize("Auvere Elektrijaam")
        candidate = tok_vocab.weighted_tokenize("Balti Elektrijaam")
        assert get_weighted_token_score(target, candidate) < 50.0

    def test_zero_score_when_empty_inputs(self, tok_plain: NameTokenizer) -> None:
        """Failure path: An empty token set on either side scores 0, not an error.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        empty = tok_plain.weighted_tokenize("")
        non_empty = tok_plain.weighted_tokenize("Auvere")
        assert get_weighted_token_score(empty, non_empty) == 0.0
        assert get_weighted_token_score(non_empty, empty) == 0.0

    def test_zero_score_when_only_excluded_tokens(
        self, tok_plain: NameTokenizer
    ) -> None:
        """Failure path: A name made only of excluded tokens carries no evidence at all.

        EXCLUDE_WEIGHT is 0.0, so such a name has a total weight of 0 and must score 0
        rather than dividing by zero or scoring on generic overlap alone.
        """
        target = tok_plain.weighted_tokenize("Unit Block")
        assert sum(target.weights) == 0.0
        assert get_weighted_token_score(target, target) == 0.0


# ----------------------------------
# Tests - NameTokenizer vocabulary construction
# ----------------------------------
class TestNameTokenizerVocabulary:
    """Tests for how NameTokenizer builds its exclude/demote lookups."""

    def test_name_mapping_is_optional(self, tok_plain: NameTokenizer) -> None:
        """Happy path: Without a name_mapping only the generic token sets apply.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        assert "elektrijaam" not in tok_plain._demote_vocabulary
        assert "power" in tok_plain._demote_words  # from GENERIC_ENERGY_TOKENS

    def test_vocabulary_keys_are_normalized(self, tok_vocab: NameTokenizer) -> None:
        """Happy path: Keys are normalized on build, so entries stay reachable.

        Lookups happen against already-normalized tokens, so a key written in its natural
        spelling ("Kraftværk") is only findable because __init__ normalizes it too.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        assert "kraftvaerk" in tok_vocab._demote_vocabulary
        assert "Kraftværk" not in tok_vocab._demote_vocabulary
        assert tok_vocab.tokenize("Skærbæk Kraftværk") == [
            "skaerbaek",
            "power",
            "plant",
        ]

    def test_demote_words_are_built_from_values_not_keys(
        self, tok_vocab: NameTokenizer
    ) -> None:
        """Regression pin: Expansion *outputs* must be demoted, not the keys they came from.

        tokenize() replaces a key with its value, so weighting the key would never fire.
        The word-level closure over the values is what stops boilerplate emitted by an
        expansion ("pumped", "power", "plant") from counting as a discriminative name.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        assert "pumped" in tok_vocab._demote_words  # only ever appears inside a value
        assert "pumpspeicherkraftwerk" not in tok_vocab._demote_words  # the key itself

    def test_multi_word_keys_are_unreachable(self, tok_vocab: NameTokenizer) -> None:
        """Failure path: A key containing a space can never match a token.

        Lookup happens per whitespace-split token, so multi-word keys are dead config.
        Pinned so the constraint is visible rather than silently swallowed.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        assert "barragem da usina" in tok_vocab._demote_vocabulary
        assert "dam" not in tok_vocab.tokenize("Barragem da Usina Tucuruí")

    def test_caches_are_not_shared_between_instances(self) -> None:
        """Failure path: Each tokenizer owns its cache, so per-init state cannot leak."""
        first, second = NameTokenizer(TEST_VOCAB), NameTokenizer(TEST_VOCAB)
        first.weighted_tokenize("Auvere EJ")
        assert second._weighted_cache == {}


# ----------------------------------
# Tests - NameTokenizer.tokenize
# ----------------------------------
class TestNameTokenizerTokenize:
    """Tests for NameTokenizer.tokenize."""

    def test_split_and_expand_vocab_keys(self, tok_vocab: NameTokenizer) -> None:
        """Happy path: Exact vocabulary keys expand to their (multi-word) meaning.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        assert tok_vocab.tokenize("Auvere EJ- G1") == [
            "auvere",
            "power",
            "plant",
            "elektrijaam",
            "g1",
        ]

    @pytest.mark.parametrize("name", ["unit", "block", "generator"])
    def test_excluded_tokens_are_kept_whole(
        self, tok_plain: NameTokenizer, name: str
    ) -> None:
        """Regression pin: An excluded token stays one token instead of one per character.

        `list.extend` on a str iterates its characters, so "unit" once came back as
        ['u', 'n', 'i', 't'].

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
            name (str): Name that is itself a single excluded token.
        """
        assert tok_plain.tokenize(name) == [name]

    def test_split_glued_name(self, tok_plain: NameTokenizer) -> None:
        """Happy path: A glued unit word is stripped off a non-vocabulary token.

        "hpp" is not in any current dictionary, so only the trailing "unit" strips --
        this pins the actual (documented) gap, not the aspirational "river" result.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        assert tok_plain.tokenize("hppriverunit") == ["hppriver"]

    @pytest.mark.parametrize(
        "name",
        ["Solaris", "Windsor", "Gaspar", "Plantation"],
    )
    def test_glue_stripping_spares_real_names(
        self, tok_vocab: NameTokenizer, name: str
    ) -> None:
        """Regression pin: Only unit designators may be stripped from inside a token.

        _strip_glued draws on GENERIC_UNIT_TOKENS alone. Were it to draw on the whole
        vocabulary (which holds "solar", "wind", "gas", "plant"), these place names would
        be eaten down to "is" / "sor" / "par" / "ation".

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
            name (str): Real name containing a generic energy word as a substring.
        """
        assert tok_vocab.tokenize(name) == [name.lower()]

    @pytest.mark.parametrize(
        "name",
        ["riverside", "auvere", "unit"],
        ids=["no_overlap", "only_short_words_match", "is_vocab_word_itself"],
    )
    def test_no_split(self, tok_plain: NameTokenizer, name: str) -> None:
        """Happy path: No split/stripping if nothing matches or a special case applies.

        1. The name has no overlap with the vocabulary.
        2. Only short words match (nothing >= 3 letters) -> no accidental stripping!
        3. The name itself is a whole vocabulary word.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
            name (str): The name that is both input and output of tokenization.
        """
        assert tok_plain.tokenize(name) == [name]

    @pytest.mark.parametrize("name", [None, "   ", ""])
    def test_no_tokens_when_empty(self, tok_plain: NameTokenizer, name: str) -> None:
        """Failure path: Missing/blank names tokenize to an empty list, not an error.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
            name (str): Missing/blank name to provide as input.
        """
        assert tok_plain.tokenize(name) == []


# ----------------------------------
# Tests - NameTokenizer weighting
# ----------------------------------
class TestNameTokenizerWeights:
    """Tests for NameTokenizer token weighting."""

    @pytest.mark.parametrize(
        "name, token, expected_output",
        [
            ("Auvere", "auvere", DEFAULT_WEIGHT),  # discriminative place name
            ("Sloe Power Station", "power", DEMOTE_WEIGHT),  # generic energy token
            ("Auvere EJ", "elektrijaam", DEMOTE_WEIGHT),  # emitted by an expansion
            ("Pumpspeicherkraftwerk X", "pumped", DEMOTE_WEIGHT),  # value-only word
            ("Auvere G1", "g1", DEMOTE_WEIGHT),  # short unit designator
            ("Sloe unit 20", "unit", EXCLUDE_WEIGHT),  # generic unit token
        ],
    )
    def test_get_weight(
        self, tok_vocab: NameTokenizer, name: str, token: str, expected_output: float
    ) -> None:
        """Happy path: Each weight tier is assigned to the right kind of token.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
            name (str): Name to tokenize and weight.
            token (str): Token expected in the result.
            expected_output (float): Expected weight of that token.
        """
        wt = tok_vocab.weighted_tokenize(name)
        assert dict(zip(wt.tokens, wt.weights))[token] == expected_output

    def test_discriminative_token_outweighs_generic_ones(
        self, tok_vocab: NameTokenizer
    ) -> None:
        """Happy path: One real name outweighs any number of generic tokens around it.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        wt = tok_vocab.weighted_tokenize("Auvere EJ")
        assert (
            get_weighted_token_score(wt, tok_vocab.weighted_tokenize("auvere")) > 80.0
        )


# ----------------------------------
# Tests - NameTokenizer cache
# ----------------------------------
class TestNameTokenizerCache:
    """Tests for NameTokenizer's weighted-token cache."""

    def test_cache_returns_repeatedly(self, tok_vocab: NameTokenizer) -> None:
        """Happy path: The cache (read-through) returns the same object each time.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        first = tok_vocab.weighted_tokenize("Auvere EJ")
        assert tok_vocab.weighted_tokenize("Auvere EJ") is first

    def test_cache_key_is_normalized_name(self, tok_vocab: NameTokenizer) -> None:
        """Happy path: Different spellings resolving to one normalization share an entry.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        first = tok_vocab.weighted_tokenize("Auvere EJ")
        assert tok_vocab.weighted_tokenize("  auvere   ej  ") is first
        assert list(tok_vocab._weighted_cache) == ["auvere ej"]
