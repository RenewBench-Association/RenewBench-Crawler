# tests/coordinates/utils/test_tokenizer.py
"""Tests for the source-agnostic name tokenizer/weighting used by NameMatcher."""

import pytest

from rbc.coordinates.utils.tokenizer import (
    DEMOTE_WEIGHT,
    DESIGNATOR_WEIGHT,
    EXCLUDE_WEIGHT,
    FULL_WEIGHT,
    NameTokenizer,
    get_weighted_token_score,
    normalize_name,
    split_camelcase,
    split_glued_generic_tokens,
)

# Synthetic vocabulary, deliberately NOT imported from rbc.energy.<operator>.mappings:
# these tests pin the tokenizer's mechanics, not the operators' evolving word lists.
TEST_VOCAB: dict[str, str] = {
    "elektrijaam": "power plant",  # multi-word value, both words already generic
    "ej": "power plant",  # value re-using another vocabulary key
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
class TestSplitHelpers:
    """Tests for split_camelcase and split_glued_generic_tokens."""

    @pytest.mark.parametrize(
        "raw, expected_output",
        [
            ("ChePortileDeFier", "Che Portile De Fier"),
            ("CetCraiova2_CRAI2_CA", "Cet Craiova2_CRAI2_CA"),
            ("CteTurceni_TURC3_CA", "Cte Turceni_TURC3_CA"),
            ("McDonald", "Mc Donald"),
        ],
    )
    def test_splits(self, raw: str, expected_output: str) -> None:
        """Happy path: camelCase words are separated at each lower -> upper transition.

        Args:
            raw (str): Raw operator name to split.
            expected_output (str): Expected split name.
        """
        assert split_camelcase(raw) == expected_output

    @pytest.mark.parametrize(
        "raw",
        ["CET_MINT5_CA", "ROVI6", "usina hidreletrica balbina", "", None],
        ids=["all_upper", "all_upper_digit", "all_lower", "empty", "none"],
    )
    def test_no_mixed_case_returns_empty(self, raw: str | None) -> None:
        """Failure path: A name without mixed case yields '', i.e. no variant to add.

        Args:
            raw (str | None): Raw name with no lower/upper mix.
        """
        assert split_camelcase(raw) == ""

    @pytest.mark.parametrize(
        "raw", ["Isalnita_ISAL8_CA", "Usina Hidrelétrica Balbina", "Auvere EJ"]
    )
    def test_mixed_case_without_transition_returns_empty(self, raw: str) -> None:
        """Failure path: Mixed case but no lower->upper transition also yields ''.

        Args:
            raw (str): Raw name whose case never transitions lower->upper.
        """
        assert split_camelcase(raw) == ""

    @pytest.mark.parametrize(
        "raw, expected_output",
        [
            ("ENGURIUNIT_5", "enguri unit 5"),
            ("HPPEnguriUnit 3", "hppenguri unit 3"),
            ("energoblok 1", "energo blok 1"),
            ("SLOEUNIT10", "sloe unit 10"),
            ("Fynsvaerket bioblok 2", "fynsvaerket bio blok 2"),
        ],
    )
    def test_split_glued(self, raw: str, expected_output: str) -> None:
        """Happy path: stem, generic word and unit number all survive the split.

        The unit number is deliberately kept: dropping it would collapse "ENGURIUNIT_1"
        through "ENGURIUNIT_5" onto one identical variant.

        Args:
            raw (str): Raw name carrying a glued generic unit word.
            expected_output (str): Expected split name.
        """
        assert split_glued_generic_tokens(normalize_name(raw)) == expected_output

    @pytest.mark.parametrize(
        "raw",
        ["Riverside", "Svelgen", "Dormagen", "Groningen", "cogeneration", "", None],
        ids=["no_generic", "no_place", "de_place", "nl_place", "word", "empty", "none"],
    )
    def test_short_generics_and_no_match_return_empty(self, raw: str | None) -> None:
        """Failure path: <=3-char generics ("gen", "g") are excluded from the split.

        These are ordinary word endings, so splitting on them would mutilate the name
        ("cogeneration" -> "co generation", "Svelgen" -> "svel gen"). An unchanged name
        yields '', i.e. no variant to add.

        Args:
            raw (str | None): Raw name with no splittable glued generic token.
        """
        assert split_glued_generic_tokens(normalize_name(raw)) == ""

    @pytest.mark.parametrize(
        "raw",
        ["United", "Conjuncta", "Groupama", "Unitech", "Blockheizkraftwerk"],
        ids=["short_residual", "lead_conj", "lead_group", "lead_unit", "lead_block"],
    )
    def test_leading_generic_and_short_residual_not_split(self, raw: str) -> None:
        """Failure path: the generic must trail the token and leave > 3 chars behind.

        A leading generic is nearly always part of a real name, and a 1-2 char residual
        means the "generic" was really a word ending ("United" -> "unit" + "ed").

        Args:
            raw (str): Real name starting with (or barely exceeding) a generic token.
        """
        assert split_glued_generic_tokens(normalize_name(raw)) == ""


class TestGetWeightedTokenScore:
    """Tests for get_weighted_token_score.

    The function returns (true_score, debug_score): identical unless a veto fired, in
    which case true_score is 0.0 while debug_score still reports how close the candidate
    came -- which is what keeps vetoed rows readable in the review CSV.
    """

    def test_high_score(self, tok_vocab: NameTokenizer) -> None:
        """Happy path: Matching a name's tokens against itself scores 100.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        tokens = tok_vocab.weighted_tokenize("Auvere EJ- G1")
        assert get_weighted_token_score(tokens, tokens) == (100.0, 100.0)

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
        true_score, _ = get_weighted_token_score(target, candidate)
        assert true_score > 80.0

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
        true_score, _ = get_weighted_token_score(target, candidate)
        assert true_score < 50.0

    def test_zero_score_when_empty_inputs(self, tok_plain: NameTokenizer) -> None:
        """Failure path: An empty token set on either side scores 0, not an error.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        empty = tok_plain.weighted_tokenize("")
        non_empty = tok_plain.weighted_tokenize("Auvere")
        assert get_weighted_token_score(empty, non_empty) == (0.0, 0.0)
        assert get_weighted_token_score(non_empty, empty) == (0.0, 0.0)

    def test_zero_score_when_only_excluded_tokens(
        self, tok_plain: NameTokenizer
    ) -> None:
        """Failure path: A name made only of excluded tokens carries no evidence at all.

        EXCLUDE_WEIGHT is 0.0, so such a name has a total weight of 0 and must score 0
        rather than dividing by zero or scoring on generic overlap alone.
        """
        target = tok_plain.weighted_tokenize("Unit Block")
        assert sum(target.weights) == 0.0
        assert get_weighted_token_score(target, target) == (0.0, 0.0)

    def test_no_discriminative_token_is_vetoed(self, tok_plain: NameTokenizer) -> None:
        """Failure path: A name of only generic words cannot be matched, however well it fits.

        "hydro power plant" agrees perfectly with any plant of that type, so a high
        similarity says nothing about identity.

        Both scores are 0.0 here, unlike the other veto: this one short-circuits before
        scoring, since no candidate could rescue a target that names nothing. The review
        CSV therefore shows no runners-up for such a target -- read target.weighted_tokens
        instead, which shows the absent discriminator directly.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        target = tok_plain.weighted_tokenize("hydro power plant")
        candidate = tok_plain.weighted_tokenize("random hydro power plant")

        assert get_weighted_token_score(target, candidate) == (0.0, 0.0)

    def test_unmatched_discriminative_token_is_vetoed(
        self, tok_plain: NameTokenizer
    ) -> None:
        """Failure path: Generic agreement cannot carry a name whose real token is absent.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        target = tok_plain.weighted_tokenize("Auvere power plant")
        candidate = tok_plain.weighted_tokenize("Balti power plant")

        true_score, debug_score = get_weighted_token_score(target, candidate)
        assert true_score == 0.0
        assert debug_score > 0.0

    def test_unmatched_generic_token_does_not_dilute(
        self, tok_plain: NameTokenizer
    ) -> None:
        """Happy path: Boilerplate the candidate lacks must not cost a matched name.

        A candidate missing "power station" says nothing about whether it is the same
        plant, so those tokens drop out of the denominator rather than dragging the score.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        target = tok_plain.weighted_tokenize("Auvere power station")
        candidate = tok_plain.weighted_tokenize("Auvere")

        true_score, _ = get_weighted_token_score(target, candidate)
        assert true_score == 100.0

    def test_unmatched_designator_does_dilute(self, tok_plain: NameTokenizer) -> None:
        """Happy path: A unit number the candidate contradicts DOES cost the score.

        Unlike boilerplate, a differing unit designator is evidence: "Maua 3" is not
        "Maua 6". It only counts when the candidate has a designator of its own, so a
        plant-level candidate (no unit number at all) is not penalised for lacking one.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
        """
        target = tok_plain.weighted_tokenize("Auvere 6")
        wrong_unit = tok_plain.weighted_tokenize("Auvere 3")
        plant_level = tok_plain.weighted_tokenize("Auvere")

        assert get_weighted_token_score(target, wrong_unit)[0] < 100.0
        assert get_weighted_token_score(target, plant_level)[0] == 100.0

    @pytest.mark.parametrize(
        "floor, expect_match",
        [(50.0, True), (100.0, False)],
        ids=["lenient_code_style", "strict_real_style"],
    )
    def test_fuzz_ratio_floor_switches_strictness(
        self, tok_plain: NameTokenizer, floor: float, expect_match: bool
    ) -> None:
        """Happy path: The floor is what makes "real" and "code" operators behave differently.

        "aracati"/"maracai" are different places that rapidfuzz rates 85.7 -- accepted for
        code-style names full of abbreviations, refused where names are real words.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
            floor (float): Minimum rapidfuzz ratio for a token pair to count.
            expect_match (bool): Whether the pair should score above zero at that floor.
        """
        target = tok_plain.weighted_tokenize("aracati")
        candidate = tok_plain.weighted_tokenize("maracai")

        true_score, _ = get_weighted_token_score(target, candidate, floor)
        assert (true_score > 0.0) is expect_match


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
        ["Svelgen", "Dormagen", "Groningen", "generation", "cogen", "hydrogen"],
        ids=["no_place", "de_place", "nl_place", "word", "compound", "fuel"],
    )
    def test_glue_stripping_spares_short_generic_endings(
        self, tok_plain: NameTokenizer, name: str
    ) -> None:
        """Regression pin: Vocabulary words of <= 3 chars may not be stripped from a token.

        "gen" and "g" are generic unit tokens, but they are also ordinary word and place
        name endings. Were _strip_glued to consider them (as it did at length >= 3), these
        would be eaten down to "svel" / "dorma" / "gronin" / "eration" / "co" / "hydro" --
        4300 GEM names among them.

        Args:
            tok_plain (NameTokenizer): Tokenizer without a name_mapping.
            name (str): Real name starting or ending in a short generic unit token.
        """
        assert tok_plain.tokenize(name) == [name.lower()]

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
            ("Auvere", "auvere", FULL_WEIGHT),  # discriminative place name
            ("Sloe Power Station", "power", DEMOTE_WEIGHT),  # generic energy token
            ("Auvere EJ", "plant", DEMOTE_WEIGHT),  # emitted by an expansion
            ("Pumpspeicherkraftwerk X", "pumped", DEMOTE_WEIGHT),  # value-only word
            ("Auvere G1", "g1", DESIGNATOR_WEIGHT),  # letter+digit unit designator
            ("Maua Bloco 6", "6", DESIGNATOR_WEIGHT),  # bare unit number
            ("Maua Bloco 5A", "5a", DESIGNATOR_WEIGHT),  # digit+letter unit designator
            ("Santana III", "iii", DESIGNATOR_WEIGHT),  # roman unit numeral
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

    def test_real_token_outweighs_generic_ones(self, tok_vocab: NameTokenizer) -> None:
        """Happy path: One real name outweighs any number of generic tokens around it.

        Args:
            tok_vocab (NameTokenizer): Tokenizer carrying TEST_VOCAB.
        """
        target_wt = tok_vocab.weighted_tokenize("Auvere EJ")
        cand_wt = tok_vocab.weighted_tokenize("auvere")
        true_score, _ = get_weighted_token_score(target_wt, cand_wt)
        assert true_score > 80.0


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
