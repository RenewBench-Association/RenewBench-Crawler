# tests/coordinates/utils/test_fuel.py
"""Tests for the fuel-type tokenization and compatibility classification helpers."""

import re

import numpy as np
import pandas as pd
import pytest

from rbc.coordinates.utils.fuel import (
    FUEL_STOPWORDS,
    FUEL_TOKEN_SYNONYMS,
    FUEL_UNKNOWN,
    _tokenize_fuel,
    classify_fueltype_match,
)


class TestGlobalParameters:
    """Tests for global parameters (FUEL_TOKEN_SYNONYMS)."""

    @pytest.mark.parametrize("key", sorted(FUEL_TOKEN_SYNONYMS))
    def test_synonym_keys_are_producible_tokens(self, key: str) -> None:
        """Failure path: A synonym key that tokenization can never emit is dead config.

        Tokens are cut with `[a-z]+`, so a key like "by-product" is unreachable -- the
        label would be split into "by" and "product" before the lookup happens.

        Args:
            key (str): Parametrized key of the FUEL_TOKEN_SYNONYMS mapping.
        """
        assert re.fullmatch(r"[a-z]+", key)

    @pytest.mark.parametrize("value", sorted(set(FUEL_TOKEN_SYNONYMS.values())))
    def test_synonym_values_are_single_tokens(self, value: str) -> None:
        """Failure path: Word-wise comparisons mean synonym values cannot be multi-word.

        Values are substituted as whole tokens, so mapping "lignite" to "brown coal"
        yields the literal token "brown coal", which never compares equal to "coal".

        Args:
            value (str): Parametrized value of the FUEL_TOKEN_SYNONYMS mapping.
        """
        assert re.fullmatch(r"[a-z]+", value)

    @pytest.mark.parametrize("word", sorted(FUEL_STOPWORDS | FUEL_UNKNOWN))
    def test_stopwords_and_unknowns_are_tokenlike(self, word: str) -> None:
        """Failure path: both sets are compared against tokens, so both must look like one.

        Args:
            word (str): Parametrized entry of FUEL_STOPWORDS or FUEL_UNKNOWN.
        """
        assert re.fullmatch(r"[a-z]+", word)


# ----------------------------------
# Tests (main utilities)
# ----------------------------------
class TestClassifyFueltypeMatch:
    """Tests for the utility function classify_fueltype_match."""

    @pytest.mark.parametrize(
        "sysop_type, loc_type, expected_output",
        [
            # --- exact: identical token sets (after normalization/synonyms) ---
            ("wind", "Wind", "exact"),
            ("coal", "Lignite", "exact"),
            ("gas", "LNG", "exact"),
            ("hydro", "Hydroelectric", "exact"),
            # --- compatible: sets overlap without being identical ---
            ("gas", "fossil gas: gas, fossil liquids: heavy fuel oil", "compatible"),
            ("fossil gas", "natural gas", "compatible"),
            # --- mismatch: no overlap at all ---
            ("wind", "solar", "mismatch"),
            ("nuclear", "coal", "mismatch"),
            ("hydro", "bioenergy: agricultural waste (solids)", "mismatch"),
        ],
    )
    def test(self, sysop_type: str, loc_type: str, expected_output: str) -> None:
        """Happy + failure paths: Overlapping labels agree, disjoint ones are rejected.

        Args:
            sysop_type (str): Fuel type of the operator's EGE.
            loc_type (str): Fuel type of the locator's EGE.
            expected_output (str): Expected compatibility level.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == expected_output

    @pytest.mark.parametrize(
        "loc_type",
        [
            "bioenergy: refuse (landfill gas)",
            "bioenergy: agricultural waste (solids)",
            "bioenergy: wood & other biomass (solids)",
        ],
    )
    def test_broad_sysop_matches_specific_loc(self, loc_type: str) -> None:
        """Happy path: A multi-word sysop label can match with specific locator labels.

        These three are the real ONS/Brazil rejections that motivated moving from
        substring containment to token-set overlap.

        Args:
            loc_type (str): Fuel type of the locator's EGE.
        """
        sysop_type = "thermal (coal/gas/oil/waste/biomass)"
        assert classify_fueltype_match(sysop_type, loc_type) == "compatible"

    @pytest.mark.parametrize(
        "sysop_type, loc_type",
        [
            (None, "Wind"),
            ("Wind", None),
            (np.nan, np.nan),
            ("", "Wind"),
            ("unknown", "unknown"),  # identical, but carries no information
            ("none", "none"),
            ("wind", "unknown"),
            ("unknown", "unknown gas"),  # overlap is the marker itself, not a fuel
            ("unknown gas", "wind"),  # marker present, no real overlap
        ],
    )
    def test_unknown_types(self, sysop_type: str | None, loc_type: str | None) -> None:
        """Failure path: Missing or unknown-only labels classify as "unknown", not a match.

        "unknown" must not be reported as "exact" just because both sides say it, and it
        must never be counted as evidence of overlap.

        Args:
            sysop_type (str | None): Fuel type of the operator's EGE.
            loc_type (str | None): Fuel type of the locator's EGE.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == "unknown"

    @pytest.mark.parametrize(
        "sysop_type, loc_type, expected_output",
        [
            ("unknown gas", "gas", "compatible"),
            ("unknown gas", "unknown gas", "exact"),
        ],
    )
    def test_unknown_does_not_mask_real_fuel(
        self, sysop_type: str, loc_type: str, expected_output: str
    ) -> None:
        """Happy path: A type str mixing an unknown token with a real fuel keeps the fuel.

        Guards the `<= FUEL_UNKNOWN` (subset) test against being weakened to `&`
        (intersection), which would discard the informative half of the label.

        Args:
            sysop_type (str): Fuel type of the operator's EGE.
            loc_type (str): Fuel type of the locator's EGE.
            expected_output (str): Expected compatibility level.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == expected_output


# ----------------------------------
# Tests (helpers)
# ----------------------------------
class TestTokenizeFuel:
    """Tests for helper _tokenize_fuel."""

    @pytest.mark.parametrize(
        "value, expected_output",
        [
            ("Wind Onshore", ("wind", "onshore")),
            ("Óleo Diesel", ("oleo", "oil")),  # diacritics stripped + synonym applied
            ("fossil gas: LNG", ("fossil", "gas", "gas")),
            ("heavy, fuel oil", ("heavy", "oil")),  # "fuel" is excluded (stopword)
            (
                "bioenergy: refuse (landfill gas)",
                ("bioenergy", "refuse", "waste", "gas"),
            ),
            ("Hydroelectric", ("hydro",)),
            ("Photovoltaic", ("solar",)),
        ],
    )
    def test(self, value: str, expected_output: tuple[str, ...]) -> None:
        """Happy path: Labels normalize, expand via synonyms and drop stopwords.

        Additionally, order is preserved (tokens return in the order they are in the label).

        Args:
            value (str): Fuel label to provide as input.
            expected_output (tuple[str, ...]): Expected tokens returned by the function.
        """
        assert _tokenize_fuel(value) == expected_output

    @pytest.mark.parametrize(
        "value", [None, np.nan, pd.NA, pd.NaT, "", "   ", "123", "-"]
    )
    def test_empty_for_missing_or_wordless_values(self, value: str | None) -> None:
        """Failure path: Missing values and labels with no words tokenize to nothing.

        This is what lets classify_fueltype_match drop its former `pd.isna` guard.

        Args:
            value (str | None): Missing/wordless value to provide as input.
        """
        assert _tokenize_fuel(value) == ()

    def test_caching(self) -> None:
        """Happy path: LRU cache handles repeated calls correctly.

        Via is_compatible_fueltype, tokenize_fuel is used in NameMatcher's inner candidate
        loop, so caching is what keeps cost down (plain call is ~17x slower than a cached).
        """
        _tokenize_fuel.cache_clear()
        _tokenize_fuel("Fossil Hard coal")
        _tokenize_fuel("Fossil Hard coal")

        assert _tokenize_fuel.cache_info().hits == 1
