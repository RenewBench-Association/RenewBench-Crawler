# tests/coordinates/resources/test_ppm.py
"""Tests for the PPM locator: source resolution, country normalization and columns."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from rbc.coordinates.resources.ppm import (
    PPM_COLUMNS,
    PPM_CSV_FILE,
    PPM_CSV_URL,
    PPMLocator,
)

PPM_MODULE = "rbc.coordinates.resources.ppm"


# ----------------------------------
# Fixtures / test doubles
# ----------------------------------
def _ppm_df(countries: tuple[str, ...] = ("Germany",)) -> pd.DataFrame:
    """Build a minimal PPM frame holding every column the PPDB schema requires.

    Args:
        countries (tuple[str, ...]): One "Country" value per plant to build.

    Returns:
        pd.DataFrame: Frame with one plant per country and all of `PPM_COLUMNS`.
    """
    rows: list[dict[str, object]] = []
    for pos, country in enumerate(countries):
        row: dict[str, object] = dict.fromkeys(PPM_COLUMNS, 1.0)
        row.update({"Name": f"Plant {pos}", "id": f"ppm-{pos}", "Fueltype": "hydro"})
        row["Country"] = country
        rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------------
# Tests
# ----------------------------------
class TestPPMLocatorSource:
    """Tests for which source the locator reads PPM's CSV from."""

    def test_no_cache_dir_reads_the_url(self) -> None:
        """Happy path: without a cache_dir the CSV is read straight from its URL.

        Nothing is downloaded to disk, since there is nowhere to put it.
        """
        with (
            patch(f"{PPM_MODULE}.load_df_from_file", return_value=_ppm_df()) as load,
            patch(f"{PPM_MODULE}.fetch_resource") as fetch,
        ):
            PPMLocator()

        load.assert_called_once_with(PPM_CSV_URL)
        fetch.assert_not_called()

    def test_cache_dir_is_fetched_into_and_read_from(self, tmp_path: Path) -> None:
        """Happy path: a cache_dir gets the CSV fetched into it and read from there.

        Args:
            tmp_path (Path): Pytest-provided temporary directory (the cache dir).
        """
        cached = Path(tmp_path, PPM_CSV_FILE)
        with (
            patch(f"{PPM_MODULE}.load_df_from_file", return_value=_ppm_df()) as load,
            patch(f"{PPM_MODULE}.fetch_resource", return_value=cached) as fetch,
        ):
            PPMLocator(cache_dir=tmp_path)

        fetch.assert_called_once_with(PPM_CSV_URL, cached, False)
        load.assert_called_once_with(cached)

    def test_update_reaches_the_fetcher(self, tmp_path: Path) -> None:
        """Happy path: `-u` has to reach `fetch_resource`, or a stale copy is kept forever.

        Args:
            tmp_path (Path): Pytest-provided temporary directory (the cache dir).
        """
        cached = Path(tmp_path, PPM_CSV_FILE)
        with (
            patch(f"{PPM_MODULE}.load_df_from_file", return_value=_ppm_df()),
            patch(f"{PPM_MODULE}.fetch_resource", return_value=cached) as fetch,
        ):
            PPMLocator(cache_dir=tmp_path, update=True)

        fetch.assert_called_once_with(PPM_CSV_URL, cached, True)

    def test_failed_fetch_falls_back_to_the_url(self, tmp_path: Path) -> None:
        """Failure path: no local copy and a failed download still reads from the URL.

        `fetch_resource` returns None when it has neither, which must not disable PPM.

        Args:
            tmp_path (Path): Pytest-provided temporary directory (the cache dir).
        """
        with (
            patch(f"{PPM_MODULE}.load_df_from_file", return_value=_ppm_df()) as load,
            patch(f"{PPM_MODULE}.fetch_resource", return_value=None),
        ):
            PPMLocator(cache_dir=tmp_path)

        load.assert_called_once_with(PPM_CSV_URL)


class TestPPMLocatorDataframe:
    """Tests for the loaded dataframe's normalization and required columns."""

    def test_countries_are_normalized(self) -> None:
        """Happy path: country values are normalized, so they can match an operator's."""
        df = _ppm_df(("USA", "DEU"))
        with patch(f"{PPM_MODULE}.load_df_from_file", return_value=df):
            locator = PPMLocator()

        assert list(locator.df["Country"]) == ["United States", "Germany"]

    @pytest.mark.parametrize("missing", ["Name", "Fueltype", "lat", "lon"])
    def test_missing_required_column_raises(self, missing: str) -> None:
        """Failure path: a frame without a schema column is rejected at init.

        `MatchCandidate.from_row` reads these by subscript, so a missing one would
        otherwise surface as a KeyError per row, deep inside matching.

        Args:
            missing (str): Name of the required column to drop.
        """
        df = _ppm_df().drop(columns=[missing])
        with (
            patch(f"{PPM_MODULE}.load_df_from_file", return_value=df),
            pytest.raises(ValueError, match="does not contain required columns"),
        ):
            PPMLocator()

    def test_all_schema_columns_present_is_accepted(self) -> None:
        """Happy path: a frame with exactly the required columns passes the check."""
        with patch(f"{PPM_MODULE}.load_df_from_file", return_value=_ppm_df()):
            locator = PPMLocator()

        assert set(PPM_COLUMNS).issubset(locator.df.columns)
        assert len(locator.df) == 1
