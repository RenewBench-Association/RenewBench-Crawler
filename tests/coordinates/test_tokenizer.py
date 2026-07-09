# tests/coordinates/test_tokenizer.py
"""Tests for the source-agnostic name tokenizer/weighting used by NameMatrixMatcher."""

from rbc.coordinates.tokenizer import (
    DEFAULT_WEIGHT,
    LOW_WEIGHT,
    base_name_key,
    build_vocabulary,
    normalize_name,
    strip_vocabulary_glued,
    token_weight,
    tokenize_and_expand,
    weighted_token_score,
    weighted_tokenize,
)


def test_normalize_name_basic():
    """Happy path for normalize_name.

    Lowercases, strips diacritics, and collapses non-alphanumeric runs to a
    single space; None/empty input returns an empty string.
    """
    assert normalize_name("  Čapljina HPP-Unit 5!  ") == "capljina hpp unit 5"
    assert normalize_name(None) == ""
    assert normalize_name("") == ""


def test_auvere_tokenize_and_weight():
    """Happy path for tokenize_and_expand/token_weight on the Auvere worked example.

    "auvere" is the discriminative place name and must get DEFAULT_WEIGHT,
    while "g1" is a unit designator and must get LOW_WEIGHT.
    """
    vocab = build_vocabulary("EE")
    tokens = tokenize_and_expand("Auvere EJ- G1", country_code="EE")
    assert "auvere" in tokens
    assert "g1" in tokens
    assert token_weight("auvere", vocab) == DEFAULT_WEIGHT
    assert token_weight("g1", vocab) == LOW_WEIGHT


def test_glued_name_bidirectional_strip():
    """Happy path for strip_vocabulary_glued on a name with a glued unit suffix.

    "hpp" is not in any current dictionary, so only the trailing "unit"
    strips -- this pins the actual (documented) gap, not the aspirational
    "river" result. If "hpp" is ever added to GENERIC_UNIT_TOKENS, this
    assertion should flip to "river".
    """
    vocab = build_vocabulary(None)
    assert strip_vocabulary_glued("hppriverunit", vocab) == "hppriver"


def test_strip_vocabulary_glued_no_short_word_collision():
    """Regression pin: short vocabulary keys must not false-strip inside place names.

    2-letter ENTSO-E abbreviation keys (he/te/ve/fe/ne/re) must NOT be
    stripped as accidental suffixes/prefixes of unrelated place names --
    "auvere" ends in "re" and, after one strip, "ve" -- both are vocabulary
    keys, but stripping them would mangle "auvere" down to "au".
    """
    vocab = build_vocabulary(None)
    assert strip_vocabulary_glued("auvere", vocab) == "auvere"


def test_strip_vocabulary_glued_no_match():
    """Failure path for strip_vocabulary_glued when no vocabulary word overlaps."""
    vocab = build_vocabulary(None)
    assert strip_vocabulary_glued("riverside", vocab) == "riverside"


def test_strip_vocabulary_glued_whole_word_untouched():
    """Edge case: a token that IS itself a whole vocabulary word is left alone.

    tokenize_and_expand handles whole-word vocabulary tokens via its
    exact-key branch instead, before ever calling the stripper.
    """
    vocab = build_vocabulary(None)
    assert strip_vocabulary_glued("unit", vocab) == "unit"


def test_generic_token_collision_adversarial():
    """Adversarial case: a shared generic token alone must not drive up the score.

    Two unrelated plants sharing only a low-weight generic unit designator
    ("g1") must NOT score high just because of that shared token.
    """
    target = weighted_tokenize("Auvere G1", country_code="EE")
    candidate = weighted_tokenize("Narva G1", country_code="EE")
    score = weighted_token_score(target, candidate)
    assert score < 50.0


def test_weighted_token_score_self_match_is_high():
    """Happy path: matching a name's tokens against themselves scores 100."""
    tokens = weighted_tokenize("Auvere EJ- G1", country_code="EE")
    assert weighted_token_score(tokens, tokens) == 100.0


def test_weighted_token_score_partial_match_dominated_by_high_weight_token():
    """One strong discriminative-token match should dominate the weighted score.

    A strong-matching discriminative token plus one non-matching low-weight
    token should still score high, since the low-weight token is suppressed
    by its small contribution to the weighted average.
    """
    target = weighted_tokenize("Auvere G1", country_code="EE")
    candidate = weighted_tokenize("Auvere G7", country_code="EE")
    score = weighted_token_score(target, candidate)
    assert score > 80.0


def test_weighted_token_score_empty_inputs():
    """Failure path: an empty token set on either side scores 0, not an error."""
    empty = weighted_tokenize("", country_code=None)
    non_empty = weighted_tokenize("Auvere", country_code=None)
    assert weighted_token_score(empty, non_empty) == 0.0
    assert weighted_token_score(non_empty, empty) == 0.0


def test_bare_single_letter_unit_designator_is_low_weight():
    """Regression pin: bare 1-2 letter block designators must get LOW_WEIGHT.

    Seen in real ENTSO-E names with no trailing digit, e.g. "KW Boxberg
    Block Q" / "Neurath F" / "Weisweiler H".
    """
    vocab = build_vocabulary("DE")
    assert token_weight("q", vocab) == LOW_WEIGHT
    assert token_weight("f", vocab) == LOW_WEIGHT
    target = weighted_tokenize("Neurath F", country_code="DE")
    candidate = weighted_tokenize("Neurath", country_code="DE")
    assert weighted_token_score(target, candidate) > 80.0


def test_country_specific_vocabulary():
    """Happy path: country-specific vocabulary entries only apply to their country."""
    ee_vocab = build_vocabulary("EE")
    default_vocab = build_vocabulary(None)
    de_vocab = build_vocabulary("DE")
    assert "ej" in ee_vocab
    assert "ej" not in default_vocab
    assert "ej" not in de_vocab
    assert "kraftwerk" in de_vocab
    assert "kraftwerk" not in ee_vocab


def test_base_name_key_collapses_sibling_units():
    """Happy path: units differing only by a unit designator share one base key.

    Used to derive a non-EIC sibling-unit grouping key for the standard
    pipeline (operators with no EIC/wcode data at all).
    """
    assert base_name_key("Plant X Unit 1", country_code=None) == base_name_key(
        "Plant X Unit 2", country_code=None
    )


def test_base_name_key_all_generic_returns_none():
    """Failure path: a name with no discriminative tokens has no base key.

    Every token_weight rule that can classify a token LOW_WEIGHT (vocabulary
    membership, or the bare-1-2-letter/1-3-digit UNIT_DESIGNATOR_RE branches)
    guarantees any surviving DEFAULT_WEIGHT token is already >=3 chars, so an
    explicit length guard on the joined key would be unreachable -- this case
    (zero survivors) is the only way to end up with no usable key.
    """
    assert base_name_key("Unit 1", country_code=None) is None
    assert base_name_key("Q1", country_code=None) is None
