"""Public surface of the coordinate-finding pipelines subpackage.

Exposes the pipeline classes (BasePipeline and its concrete subclasses),
`make_locator` to build the right pipeline instance for a given directory,
and `build_shared_locators` to build the expensive, run-scoped locators
that get reused across every directory in one `perform_coordinate_finding`
run.
"""

from dataclasses import dataclass
from pathlib import Path

from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.mappings import OPERATOR_METADATA
from rbc.coordinates.pipelines._base import BasePipeline
from rbc.coordinates.pipelines.default import DefaultPipeline
from rbc.coordinates.pipelines.entsoe import EntsoePipeline

__all__ = [
    "BasePipeline",
    "DefaultPipeline",
    "EntsoePipeline",
    "SharedLocators",
    "build_shared_locators",
    "make_pipeline",
]


def make_pipeline(
    input_dir: Path,
    output_dir: Path | None = None,
    gem_loc: GEMLocator | None = None,
    ppdb_loc: PPMLocator | OSMPPLocator | None = None,
    eic_reg: EICCodeRegistry | None = None,
    osm_update: bool = False,
    osm_live: bool = False,
) -> BasePipeline:
    """Build the right pipeline instance (BasePipeline subclass) for `input_dir`.

    Looks up the operator embedded in `input_dir`'s path and, via
    OPERATOR_METADATA[operator]["pipeline"], resolves which concrete pipeline
    class to build. `eic_reg` is only ever forwarded to EntsoePipeline --
    every other pipeline's constructor doesn't accept it at all.

    Args:
        input_dir (Path): Path to the raw energy generation file (assuming CSV here).
        output_dir (Path, optional): Path to the directory where any output files may be
            saved. Defaults to None.
        gem_loc (GEMLocator, optional): Pre-built GEM locator to reuse. Defaults to
            None, in which case GEM is disabled.
        ppdb_loc (PPMLocator, optional): Pre-built PPM locator to reuse. Defaults to
            None, in which case the resolved pipeline builds its own default.
        eic_reg (EICCodeRegistry, optional): Pre-built EIC directory locator
            to reuse. Only relevant for the entsoe pipeline; ignored otherwise.
        osm_update (bool): Re-fetch OSM data from Overpass and overwrite the local
            ``overpass_..._plants.parquet`` file even if it already exists.
            Corresponds to the ``--update`` / ``-u`` CLI flag.
        osm_live (bool): Query Overpass live on every run, ignoring and not writing
            any local file. Corresponds to the ``--live`` CLI flag.

    Returns:
        BasePipeline: The concrete pipeline instance for `input_dir`.

    Raises:
        TypeError: If `ppdb_loc` is an instance of the wrong locator class for the
            resolved pipeline (e.g. an `OSMPPLocator` passed in for an entsoe zone).
    """
    operator = [p for p in Path(input_dir).parts if p in OPERATOR_METADATA][0]
    pipeline_name = OPERATOR_METADATA[operator].get("pipeline", "default")

    if pipeline_name == "entsoe":
        if ppdb_loc is not None and not isinstance(ppdb_loc, PPMLocator):
            raise TypeError(
                f"'{operator}' uses the entsoe pipeline, which requires a PPMLocator "
                f"for ppdb_loc, got {type(ppdb_loc).__name__}."
            )
        return EntsoePipeline(
            input_dir=input_dir,
            output_dir=output_dir,
            gem_loc=gem_loc,
            ppm_loc=ppdb_loc,
            eic_reg=eic_reg,
            osm_update=osm_update,
            osm_live=osm_live,
        )

    if ppdb_loc is not None and not isinstance(ppdb_loc, OSMPPLocator):
        raise TypeError(
            f"'{operator}' uses the default pipeline, which requires an OSMPPLocator "
            f"for ppdb_loc, got {type(ppdb_loc).__name__}."
        )
    return DefaultPipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        gem_loc=gem_loc,
        osmpp_loc=ppdb_loc,
        osm_update=osm_update,
        osm_live=osm_live,
    )


@dataclass
class SharedLocators:
    """Expensive, run-scoped locators built once and reused across a run's directories."""

    gem_loc: GEMLocator | None
    ppdb_loc: PPMLocator | OSMPPLocator | None
    eic_reg: EICCodeRegistry | None


def build_shared_locators(
    source: str, gem_dir: Path | None, output_dir: Path | None
) -> SharedLocators:
    """Build the expensive (network/CSV/parquet-backed) locators shared across one run.

    Callers processing multiple directories for the same source in one run (e.g.
    multiple ENTSO-E bidding zones) should build these once and pass them into
    `make_locator` for every directory, rather than paying the construction cost
    (network/CSV/parquet reads) per directory.

    Args:
        source (str): Name of the energy source, e.g. "entsoe". Used to resolve
            which pipeline's locators are actually needed.
        gem_dir (Path | None): Path to the manually downloaded GEM data or, if None,
            to use the fallback GEM files from the PyPSA team's cloud storage.
        output_dir (Path | None): Output directory, used as the cache dir for
            locators that persist a local file (e.g. the EIC directory).

    Returns:
        SharedLocators: The locators to reuse across every directory processed
            in this run.
    """
    gem_loc: GEMLocator = GEMLocator(
        gem_dir=gem_dir, cache_dir=output_dir if gem_dir is None else None
    )
    ppdb_loc: PPMLocator | OSMPPLocator
    eic_reg: EICCodeRegistry | None

    pipeline_name = OPERATOR_METADATA[source].get("pipeline", "default")
    if pipeline_name == "entsoe":  # use regional European assets
        ppdb_loc = PPMLocator()
        eic_reg = EICCodeRegistry(cache_dir=output_dir)
    else:  # assume the default
        ppdb_loc = OSMPPLocator()
        eic_reg = None

    return SharedLocators(gem_loc=gem_loc, ppdb_loc=ppdb_loc, eic_reg=eic_reg)
