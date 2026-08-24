# tests/coordinates/utils/test_values.py
"""Tests for the shared NaN-safe value-changing helpers."""

import numpy as np
import pandas as pd
import pytest

from rbc.coordinates.utils.values import (
    is_missing,
    normalize_name,
    strip_lower_str,
    strip_str,
)


class TestNormalizeName:
    """Tests for normalize_name."""

    def test_normalize_name(self) -> None:
        """Happy path: Lowercases, strips diacritics, collapses non-alphanumeric runs."""
        assert normalize_name("  Čapljina HPP-Unit 5!  ") == "capljina hpp unit 5"

    @pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
    def test_normalize_name_missing(self, value: str | None) -> None:
        """Failure path: Missing/blank values normalize to an empty string, not an error.

        Args:
            value (str | None): Missing value to provide as input.
        """
        assert normalize_name(value) == ""

    @pytest.mark.parametrize(
        "value, expected_output",
        [
            ("kraftværk", "kraftvaerk"),
            ("Skærbækværket", "skaerbaekvaerket"),
            ("vindmøllepark", "vindmollepark"),
            ("słoneczna", "sloneczna"),
            ("Straße", "strasse"),
            ("Đerdap", "derdap"),
            ("Þjórsá", "thjorsa"),
            ("Måløy", "maloy"),  # "å" decomposes, "ø" does not
        ],
    )
    def test_normalize_name_transliterates_atomic_letters(
        self, value: str, expected_output: str
    ) -> None:
        """Happy path: Single-codepoint letters become ASCII instead of word separators.

        NFKD only decomposes base+diacritic pairs, so letters like "æ"/"ø"/"ł"/"ß" survive
        it and would otherwise be swallowed by the `[^a-z0-9]` pass -- shattering a Danish
        name into fragments ("skaerbaekvaerket" vs "sk rb kv rket") on both sides of a match.

        Args:
            value (str): Name containing an atomic non-ASCII letter.
            expected_output (str): Expected normalized string.
        """
        assert normalize_name(value) == expected_output

    @pytest.mark.parametrize(
        "value",
        [
            "Auvere EJ",
            "  Balti G09 ",
            "Ünïcodé Näme",
            "ENGURIUNIT_5",
            "KW Boxberg Block Q",
            "Skærbækværket",
        ],
    )
    def test_normalize_name_is_idempotent(self, value: str) -> None:
        """Regression pin: Normalizing an already-normalized name is a no-op.

        Callers routinely hand already-normalized names back in --
        NameTokenizer.weighted_tokenize passes its own `normalized` into tokenize(), and
        NameMatcher passes `candidate.norm_name` into weighted_tokenize(). All of that is
        only correct while this holds.

        Args:
            value (str): Raw name to normalize twice.
        """
        once = normalize_name(value)
        assert normalize_name(once) == once


class TestIsMissing:
    """Tests for is_missing helper function."""

    @pytest.mark.parametrize("value", [None, np.nan, pd.NA, pd.NaT, "", "   ", "\t\n"])
    def test_missing_values_return_true(self, value: object) -> None:
        """Happy path: every None/NA/blank sentinel are found as missing.

        Args:
            value (object): Missing values to provide as input.
        """
        assert is_missing(value) is True

    @pytest.mark.parametrize("value", ["MGRES", " Gas ", 0, 0.0, False, 5, "0"])
    def test_present_values_return_false(self, value: object) -> None:
        """Failure path: Present scalars are identified as not missing.

        Guards against a `not value` shortcut, which would wrongly discard 0/False.

        Args:
            value (object): Truthy values to provide as input.
        """
        assert is_missing(value) is False

    @pytest.mark.parametrize("value", [[], {}, ["a"], {"k": 1}, np.array([1, 2])])
    def test_containers_do_not_raise(self, value: object) -> None:
        """Failure path: containers are handled without raising.

        `pd.isna` returns an array for list/dict/ndarray input, which would raise
        "truth value is ambiguous" if it reached an `if`, so this is handled silently.

        Args:
            value (object): Container values (lists/dicts/arrays/...) to provide as input.
        """
        assert is_missing(value) is False


class TestStripStr:
    """Tests for strip_str helper function."""

    @pytest.mark.parametrize(
        "value, expected_output",
        [
            ("MGRES", "MGRES"),
            ("  MGRES  ", "MGRES"),
            ("", None),
            ("   ", None),
            (None, None),
            (float("nan"), None),
            (pd.NA, None),
            (pd.NaT, None),
        ],
    )
    def test_strip_str(self, value: object, expected_output: str | None) -> None:
        """Happy + failure paths: strings are stripped, missing values become None.

        Args:
            value (object): Value to provide as input.
            expected_output (str | None): Expected output to be returned by function.
        """
        assert strip_str(value) == expected_output


class TestStripLowerStr:
    """Tests for strip_lower_str."""

    @pytest.mark.parametrize(
        "value, expected_output",
        [
            ("MGRES", "mgres"),
            ("  Fossil Gas  ", "fossil gas"),
            ("", ""),
            ("   ", ""),
            (None, ""),
            (float("nan"), ""),
            (pd.NA, ""),
            (pd.NaT, ""),
        ],
    )
    def test_strip_lower_str(self, value: object, expected_output: str) -> None:
        """Happy + failure paths: strings are stripped/lowercased, missing become "".

        Args:
            value (object): Value to provide as input.
            expected_output (str): Expected output to be returned by function.
        """
        assert strip_lower_str(value) == expected_output
