# tests/coordinates/utils/test_values.py
"""Tests for the shared NaN-safe value-changing helpers."""

import numpy as np
import pandas as pd
import pytest

from rbc.coordinates.utils.values import is_missing, strip_lower_str, strip_str


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
