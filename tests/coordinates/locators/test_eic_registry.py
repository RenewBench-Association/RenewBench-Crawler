# tests/coordinates/locators/test_eic_registry.py
"""Tests for the EIC code registry locator (loading, indexing, parent matching)."""

from pathlib import Path
from typing import Callable

import pandas as pd
import pytest

from rbc.coordinates.locators.eic_registry import (
    CODE_COL,
    DISPLAYNAME_COL,
    LONGNAME_COL,
    PARENT_COL,
    PARTY_COL,
    STATUS_COL,
    TYPE_COL,
    EICCodeRegistry,
    extract_prefix,
)

MOCK_ROWS = [
    {
        CODE_COL: "11W-PU",
        DISPLAYNAME_COL: "MGRES_PU",
        LONGNAME_COL: "Mingechevir GRES",
        PARENT_COL: "",
        PARTY_COL: "AZ",
        STATUS_COL: "Active",
        TYPE_COL: "Production Unit",
    },
    {
        CODE_COL: "11W-G4",
        DISPLAYNAME_COL: "MGRES_G4",
        LONGNAME_COL: "Mingechevir G4",
        PARENT_COL: "11W-PU",
        PARTY_COL: "AZ",
        STATUS_COL: "Active",
        TYPE_COL: "Generation Unit",
    },
    # blank code: must never be indexed or matched
    {
        CODE_COL: "   ",
        DISPLAYNAME_COL: "BLANK_PU",
        LONGNAME_COL: "Blank row",
        PARENT_COL: "",
        PARTY_COL: "XX",
        STATUS_COL: "Active",
        TYPE_COL: "Production Unit",
    },
]


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def get_mock_registry(tmp_path: Path) -> Callable[..., EICCodeRegistry]:
    """Factory building a real registry from a synthetic cached CSV (no network).

    Args:
        tmp_path (Path): Pytest-provided temporary directory, used as `cache_dir`.

    Returns:
        Callable[..., EICCodeRegistry]: Factory taking optional `rows` / `rename` overrides.
    """

    def _factory(
        rows: list[dict] | None = None, rename: dict | None = None
    ) -> EICCodeRegistry:
        """Factory building a real registry from a synthetic cached CSV.

        Args:
            rows (list[dict] | None): A list of dictionaries containing rows of data.
            rename (dict): A dictionary that maps column names.

        Returns:
            EICCodeRegistry: A built EICCodeRegistry class instance.
        """
        df = pd.DataFrame(rows if rows is not None else MOCK_ROWS)
        if rename:
            df = df.rename(columns=rename)
        df.to_csv(Path(tmp_path, "eic_directory.csv"), sep=";", index=False)
        return EICCodeRegistry(cache_dir=tmp_path)

    return _factory


# ----------------------------------
# Tests - EICCodeRegistry class
# ----------------------------------
class TestEICCodeRegistrySetup:
    """Tests for loading, column normalization and indexing."""

    def test_init(self, get_mock_registry: Callable) -> None:
        """Happy path: a CSV is correctly loaded and every non-blank code is indexed.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
        """
        reg = get_mock_registry()
        assert len(reg.df_eic) == 3
        assert set(reg._eic_index) >= {"11W-PU", "11W-G4"}

    def test_check_columns(self, get_mock_registry: Callable) -> None:
        """Happy path: header variants are found and renamed to the default names.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
        """
        reg = get_mock_registry(
            rename={CODE_COL: "eic", DISPLAYNAME_COL: "displayname"}
        )
        assert CODE_COL in reg.df_eic.columns
        assert reg.lookup_full_row("11W-PU")[LONGNAME_COL] == "Mingechevir GRES"

    def test_check_columns_no_findable_col(self, get_mock_registry: Callable) -> None:
        """Failure path: a CSV with no findable EIC code column produces an empty register.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
        """
        reg = get_mock_registry(rename={CODE_COL: "unknown_val"})
        assert reg.df_eic.empty
        assert reg.lookup_full_row("11W-PU") == {}

    def test_init_unknown_data(self, get_mock_registry: Callable) -> None:
        """Failure path: a CSV with no valid data produces an empty registry.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
        """
        reg = get_mock_registry(rows=[{"unknown_col": "unknown_val"}])
        assert reg.df_eic.empty
        assert reg.lookup_full_row("11W-PU") == {}


class TestEICCodeRegistryPublicAPI:
    """Tests for public API methods (lookup_full_row and find_parent_production_unit)."""

    def test_lookup(self, get_mock_registry: Callable) -> None:
        """Happy path: a known code resolves to exactly the WCODE_FIELDS keys.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
        """
        result = get_mock_registry().lookup_full_row("11W-G4")
        assert set(result) == set(EICCodeRegistry.WCODE_FIELDS)
        assert result[LONGNAME_COL] == "Mingechevir G4"

    @pytest.mark.parametrize("code", ["", "  ", "NOT-A-CODE"])
    def test_lookup_empty_for_unknown_code(
        self, get_mock_registry: Callable, code: str
    ) -> None:
        """Failure path: blank or unknown codes return an empty dict.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
            code (str): Parametrized EIC code that should not resolve.
        """
        assert get_mock_registry().lookup_full_row(code) == {}

    @pytest.mark.parametrize(
        "kwargs, expected_method",
        [
            ({"parent": "11W-PU"}, "direct_parent"),
            (
                {"display_name": "MGRES_G4", "long_name": "Mingechevir G4"},
                "display_prefix",
            ),
            ({"long_name": "Mingechevir GRES"}, "fuzzy"),
        ],
    )
    def test_find_parent(
        self, get_mock_registry: Callable, kwargs: dict[str, str], expected_method: str
    ) -> None:
        """Happy path: each strategy finds the production unit and reports its own method.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
            kwargs (dict): Keyword arguments passed to find_parent_production_unit
                to overwrite the defaults defined in the test.
            expected_method (str): Expected strategy method.
        """
        defaults = {
            "parent": None,
            "display_name": None,
            "long_name": None,
            "responsible_party": None,
        }
        result = get_mock_registry().find_parent_production_unit(
            **{**defaults, **kwargs}
        )

        assert result is not None
        assert result["match_method"] == expected_method
        assert result[CODE_COL] == "11W-PU"
        assert set(result) == set(EICCodeRegistry.MATCH_FIELDS)  # uniform contract

    def test_find_parent_no_parent_returns_none(
        self, get_mock_registry: Callable
    ) -> None:
        """Failure path: a missing EicParent does (and should) not match the blank-code row.

        Args:
            get_mock_registry (Callable): Function returning a mock EICCodeRegistry instance.
        """
        assert (
            get_mock_registry().find_parent_production_unit(None, None, None, None)
            is None
        )


# ----------------------------------
# Tests - Helper functions
# ----------------------------------
class TestHelperFunctions:
    """Tests for helper functions (extract_prefix)."""

    @pytest.mark.parametrize(
        "name, expected_output",
        [
            ("MGRES_G4", "MGRES"),
            ("Mingechevir GRES", "MINGECHEVIR"),
            ("   ", ""),
            (None, ""),
        ],
    )
    def test_extract_prefix(self, name: str, expected_output: str) -> None:
        """Happy + failure paths: Returns prefix when extractable, otherwise empty string.

        Args:
            name (str): Name to provide as input.
            expected_output (str): Expected output to be returned by function.
        """
        assert extract_prefix(name) == expected_output
