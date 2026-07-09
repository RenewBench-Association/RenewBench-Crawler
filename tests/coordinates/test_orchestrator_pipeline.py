# tests/coordinates/test_orchestrator_pipeline.py
"""Tests for CoordinateLocator's declarative per-operator pipeline steps."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pandas as pd
import pytest

from rbc.coordinates.locator_gem import GEMLocator
from rbc.coordinates.locator_ppm import PPMLocator
from rbc.coordinates.mappings import OPERATOR_METADATA
from rbc.coordinates.orchestrator import CoordinateLocator


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def eia_input_dir(tmp_path: Path) -> Path:
    """Writes a small synthetic eia-shaped CSV to a real "eia" operator directory.

    Columns match eia's real OPERATOR_METADATA values (respondent-name,
    respondent, fueltype) so CoordinateLocator's operator resolution and
    the standard pipeline's load_and_dedupe/map_fuel_type steps see real data.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The "eia/US48" zone directory containing the CSV.
    """
    zone_dir = tmp_path / "eia" / "US48"
    zone_dir.mkdir(parents=True)
    df = pd.DataFrame(
        [
            {
                "respondent-name": "Riverside Plant Unit 1",
                "respondent": "R1",
                "fueltype": "NG",
            },
            {
                "respondent-name": "Riverside Plant Unit 2",
                "respondent": "R2",
                "fueltype": "NG",
            },
        ]
    )
    df.to_csv(zone_dir / "data.csv", index=False)
    return zone_dir


@pytest.fixture
def eia_locator(eia_input_dir: Path, tmp_path: Path) -> CoordinateLocator:
    """Returns a real CoordinateLocator for "eia", backed entirely by fake locators.

    ppmloc is always constructed unconditionally in __init__ (even for the
    standard pipeline, which never reads it) -- the fake is required here
    purely to avoid the real network fetch its real constructor would
    otherwise perform. gemloc/df_openinfra are populated with small
    synthetic data so run_pipeline() exercises real matching.

    Args:
        eia_input_dir (Path): Synthetic "eia/US48" zone directory.
        tmp_path (Path): Pytest-provided temporary directory, used for output_dir.

    Returns:
        CoordinateLocator: Constructed for the "eia" operator (standard pipeline).
    """
    locator = CoordinateLocator(
        input_dir=eia_input_dir,
        output_dir=tmp_path / "out",
        ppmloc=cast(PPMLocator, SimpleNamespace(df_europe=pd.DataFrame())),
        gemloc=cast(
            GEMLocator,
            SimpleNamespace(
                df_gem=pd.DataFrame(
                    [
                        {
                            "plant_name": "Riverside Plant",
                            "other_names": "",
                            "Country": "United States",
                            "Fueltype": "Natural Gas",
                            "lat": 40.0,
                            "lon": -90.0,
                            "gem_unit_id": "gem-us-1",
                        }
                    ]
                )
            ),
        ),
    )
    # Pre-populate df_openinfra (non-empty) so _ensure_osm_loaded's
    # `len(self.df_openinfra) == 0` check is False and it skips the real
    # Overpass network call entirely.
    locator.df_openinfra = pd.DataFrame(
        [
            {
                "Name": "Unrelated OSM Plant",
                "Fueltype": "Coal",
                "lat": 10.0,
                "lon": 10.0,
                "OSM_ID": "osm-x",
                "OSM_Type": "way",
                "OSM_URL": "",
                "OSM_Geometry": "",
            }
        ]
    )
    return locator


# ----------------------------------
# Tests
# ----------------------------------
def test_operator_metadata_pipeline_dispatch():
    """Happy path: only entsoe deviates from the "standard" pipeline default."""
    assert OPERATOR_METADATA["entsoe"].get("pipeline", "standard") == "entsoe"
    assert OPERATOR_METADATA["eia"].get("pipeline", "standard") == "standard"
    assert OPERATOR_METADATA["adme"].get("pipeline", "standard") == "standard"


def test_run_pipeline_rejects_unknown_pipeline_name(eia_locator: CoordinateLocator):
    """Failure path: an unrecognized pipeline name raises rather than silently no-op-ing.

    Args:
        eia_locator (CoordinateLocator): Constructed for "eia", from the
            `eia_locator` fixture.
    """
    eia_locator._pipeline_name = "nonexistent"
    with pytest.raises(ValueError, match="Unknown pipeline"):
        eia_locator.run_pipeline()


def test_step_load_and_dedupe_uses_code_col_when_present(
    eia_locator: CoordinateLocator,
):
    """Happy path: dedupe uses code_col when the operator has one (e.g. eia).

    Args:
        eia_locator (CoordinateLocator): Constructed for "eia", from the
            `eia_locator` fixture.
    """
    df = eia_locator._step_load_and_dedupe(pd.DataFrame())
    assert len(df) == 2  # both rows have distinct respondent codes
    assert list(df.columns) == ["respondent-name", "respondent", "fueltype"]


def test_step_load_and_dedupe_falls_back_to_name_col_without_code_col(
    eia_locator: CoordinateLocator,
):
    """Failure path: with no code_col, dedupe falls back to name_col.

    Mirrors the fallback the old legacy Path B already had (dedupe on
    name_col), now merged into the one shared step so it also applies to
    the 10 placeholder operators once their metadata gets real values.

    Args:
        eia_locator (CoordinateLocator): Constructed for "eia", from the
            `eia_locator` fixture; code_col is overridden to None here.
    """
    eia_locator.code_col = None
    df = eia_locator._step_load_and_dedupe(pd.DataFrame())
    assert len(df) == 2  # both rows have distinct respondent-name values too
    assert set(df["respondent-name"]) == {
        "Riverside Plant Unit 1",
        "Riverside Plant Unit 2",
    }


def test_derive_plant_group_key_name_groups_sibling_units(
    eia_locator: CoordinateLocator,
):
    """Happy path: units sharing a base name get the same group key, others don't.

    Args:
        eia_locator (CoordinateLocator): Constructed for "eia", from the
            `eia_locator` fixture.
    """
    df = pd.DataFrame(
        {
            "pp.respondent-name": [
                "Riverside Plant Unit 1",
                "Riverside Plant Unit 2",
                "Downtown Station",
            ]
        }
    )
    keys = eia_locator._derive_plant_group_key_name(df)
    assert keys.iloc[0] == keys.iloc[1]  # same base name -> same key
    assert keys.iloc[2] != keys.iloc[0]  # unrelated plant -> different key
    assert keys.iloc[0] is not None and str(keys.iloc[0]).startswith("name_base:")


def test_sibling_fallback_core_inherits_coords_from_matched_sibling(
    eia_locator: CoordinateLocator,
):
    """Happy path for the shared sibling-fallback machinery, independent of key strategy.

    Args:
        eia_locator (CoordinateLocator): Constructed for "eia", from the
            `eia_locator` fixture.
    """
    df = pd.DataFrame(
        {
            "pp.respondent-name": ["Matched Unit", "Needs Sibling Unit"],
            "ppm.lat": [40.0, None],
            "ppm.lon": [-90.0, None],
            "gem.lat": [None, None],
            "gem.lon": [None, None],
            "osm.lat": [None, None],
            "osm.lon": [None, None],
        }
    )
    plant_group_key = pd.Series(["group:x", "group:x"])
    result = eia_locator._sibling_fallback_core(df, plant_group_key)
    assert result.loc[1, "sibling.lat"] == 40.0
    assert result.loc[1, "sibling.lon"] == -90.0
    assert pd.isna(result.loc[0, "sibling.lat"])  # already matched, no fallback needed


def test_run_pipeline_standard_end_to_end_smoke(eia_locator: CoordinateLocator):
    """Smoke test: the full standard pipeline runs end-to-end without error.

    No real eia test data is available locally to verify actual match
    quality (see plan doc) -- this proves the wiring holds together
    (load&dedupe -> fuzzy match against GEM+OSM -> fuel validation ->
    sibling fallback -> finalize) using synthetic data, entirely offline.

    Args:
        eia_locator (CoordinateLocator): Constructed for "eia", from the
            `eia_locator` fixture.
    """
    df = eia_locator.run_pipeline()
    assert len(df) == 2
    for col in ("lat", "lon", "match_source"):
        assert col in df.columns
    # Standard pipeline never wires ppm_locator -- no row should ever be
    # attributed to a ppm.* source.
    assert not df["match_source"].astype(str).str.startswith("ppm").any()
