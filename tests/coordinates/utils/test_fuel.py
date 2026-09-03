# tests/coordinates/utils/test_fuel.py
"""Tests for the fuel-type tokenization and compatibility classification helpers."""

import re

import numpy as np
import pandas as pd
import pytest

from rbc.coordinates.utils.fuel import (
    FUEL_COMBUSTION_FAMILY,
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

    @pytest.mark.parametrize("member", sorted(FUEL_COMBUSTION_FAMILY))
    def test_family_members_are_producible_tokens(self, member: str) -> None:
        """Failure path: A family member tokenization can never emit is dead config.

        The family is compared against tokenized labels, so a multi-word or hyphenated
        member would never be found. It must also survive its own synonym mapping --
        listing "lignite" would be dead, since that is rewritten to "coal" first.

        Args:
            member (str): Parametrized member of the FUEL_COMBUSTION_FAMILY set.
        """
        assert re.fullmatch(r"[a-z]+", member)
        assert _tokenize_fuel(member) == (member,)

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
        "sysop_type, loc_type",
        [
            ("wind", "Wind"),
            ("coal", "Lignite"),
            ("gas", "LNG"),
            ("hydro", "Hydroelectric"),
        ],
        ids=["wind", "coal", "gas", "hydro"],
    )
    def test_exact_is_match(self, sysop_type: str, loc_type: str) -> None:
        """Happy path: All exact label matches are classified as expected ("exact").

        This ensures normalization works and synonyms translation is applied.

        Args:
            sysop_type (str): Fuel type of the operator's EGE.
            loc_type (str): Fuel type of the locator's EGE.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == "exact"

    @pytest.mark.parametrize(
        "sysop_type, loc_type",
        [
            ("gas", "fossil gas: gas, fossil liquids: heavy fuel oil"),
            ("fossil gas", "natural gas"),
            ("thermal (coal/gas/oil/waste/biomass)", "bioenergy (landfill gas)"),
            ("thermal (coal/gas/oil/waste/biomass)", "bioenergy: agri waste (solids)"),
            ("thermal (coal/gas/oil/waste/biomass)", "fossil fuel: diesel oil"),
        ],
        ids=["gas1", "gas2", "gas3", "waste", "oil"],
    )
    def test_compatible_is_match(self, sysop_type: str, loc_type: str) -> None:
        """Happy path: All overlapping label are classified as expected ("compatible").

        Args:
            sysop_type (str): Fuel type of the operator's EGE.
            loc_type (str): Fuel type of the locator's EGE.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == "compatible"

    @pytest.mark.parametrize(
        "sysop_type, loc_type",
        [
            ("peat", "lignite"),
            ("peat", "Solid Biomass"),
            ("peat", "bioenergy: wood & other biomass (solids), other: other"),
            ("peat", "oil"),
            ("peat", "fossil liquids: diesel"),
            ("thermal (coal/gas/oil/waste/biomass)", "bioenergy: paper mill wastes"),
        ],
        ids=["lignite", "solid_biomass", "wood", "oil", "diesel", "wastes"],
    )
    def test_family_is_match(self, sysop_type: str, loc_type: str) -> None:
        """Happy path: Two labels that both burn something are never vetoed outright.

        No locators use "peat" at all -- Ireland's peat plants appear as diesel,
        fuel oil, lignite or biomass depending on the curator -- so a strict veto rejects
        matches whose coordinates are correct. These seven pairs are the real ONS/ENTSO-E
        rejections the family level was introduced for.

        Args:
            sysop_type (str): Fuel type of the operator's EGE.
            loc_type (str): Fuel type of the locator's EGE.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == "family"

    @pytest.mark.parametrize(
        "sysop_type, loc_type",
        [
            ("thermal (coal/gas/oil/waste/biomass)", "solar"),
            ("hydroelectric", "solar"),
            ("wind", "solar"),
            ("thermal (coal/gas/oil/waste/biomass)", "wind"),
            ("wind", "fossil gas: natural gas"),
            ("hydroelectric", "oil"),
            ("hydroelectric", "fossil"),
            ("solar", "hydro"),
            ("nuclear", "coal"),
        ],
    )
    def test_family_not_too_broad(self, sysop_type: str, loc_type: str) -> None:
        """Regression pin: Only combustion types share a family -- everything else is vetoed.

        Wind, solar, hydro and nuclear stay distinct from each other and from the family.
        This is what stops the family level from admitting name matches with distinctly
        different fuel types. If any of these ever returns "family", the umbrella is too wide.

        Args:
            sysop_type (str): Fuel type of the operator's EGE.
            loc_type (str): Fuel type of the locator's EGE.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == "mismatch"

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
    def test_unknown_is_match(
        self, sysop_type: str | None, loc_type: str | None
    ) -> None:
        """Happy path: Missing or unknown-only labels classify as "unknown", not a match.

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

    @pytest.mark.parametrize(
        "sysop_type, loc_type",
        [
            ("wind", "solar"),
            ("nuclear", "coal"),
            ("hydro", "bioenergy: agricultural waste (solids)"),
        ],
        ids=["wind_v_solar", "nuclear_v_coal", "hydro_v_bioenergy"],
    )
    def test_mismatch_is_no_match(self, sysop_type: str, loc_type: str) -> None:
        """Failure path: All labels that don't match are classified as expected ("mismatch").

        Args:
            sysop_type (str): Fuel type of the operator's EGE.
            loc_type (str): Fuel type of the locator's EGE.
        """
        assert classify_fueltype_match(sysop_type, loc_type) == "mismatch"


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
