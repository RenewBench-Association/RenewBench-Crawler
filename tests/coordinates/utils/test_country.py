# tests/coordinates/utils/test_country.py
"""Tests for the country-name normalization shared by every locator."""

import pandas as pd
import pytest

from rbc.coordinates.utils.country import normalize_locator_countries


class TestNormalizeLocatorCountries:
    """Tests for normalize_locator_countries."""

    def test_several_countries_are_converted(self) -> None:
        """Happy path: each distinct value becomes its country-converter short name."""
        df = pd.DataFrame({"Country": ["USA", "DEU", "USA"]})

        result = normalize_locator_countries(df)

        assert list(result["Country"]) == ["United States", "Germany", "United States"]

    @pytest.mark.parametrize("rows", [1, 3])
    def test_a_single_country_is_converted_whole(self, rows: int) -> None:
        """Failure path: one distinct value converts to the name, not to its first letter.

        ``coco.convert`` returns a bare string for a single name and a list for several,
        so zipping the result against the values used to iterate that string character by
        character: a frame holding only "USA" came back as "U". Real locator data spans
        hundreds of countries, which is why this stayed hidden - but a locator sliced to
        one country would hit it.

        Args:
            rows (int): How many rows to build, all with the same country.
        """
        df = pd.DataFrame({"Country": ["USA"] * rows})

        result = normalize_locator_countries(df)

        assert list(result["Country"]) == ["United States"] * rows

    def test_unknown_country_is_kept_as_is(self) -> None:
        """Failure path: a value the converter can't interpret survives unchanged.

        Dropping it would silently remove every EGE in that country from matching.
        """
        df = pd.DataFrame({"Country": ["Neverland", "DEU"]})

        result = normalize_locator_countries(df)

        assert list(result["Country"]) == ["Neverland", "Germany"]

    def test_missing_country_column_is_a_no_op(self) -> None:
        """Failure path: no country column leaves the frame untouched (e.g. OSM data)."""
        df = pd.DataFrame({"Name": ["Plant A"], "lat": [1.0]})

        result = normalize_locator_countries(df)

        assert result.equals(df)

    def test_input_frame_is_not_mutated(self) -> None:
        """Happy path: the caller's frame is left alone, a copy is returned."""
        df = pd.DataFrame({"Country": ["USA", "DEU"]})

        normalize_locator_countries(df)

        assert list(df["Country"]) == ["USA", "DEU"]

    def test_custom_country_column(self) -> None:
        """Happy path: a locator naming the column differently is still normalized."""
        df = pd.DataFrame({"country_area": ["USA", "DEU"]})

        result = normalize_locator_countries(df, country_col="country_area")

        assert list(result["country_area"]) == ["United States", "Germany"]
