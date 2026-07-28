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
    gemloc: GEMLocator | None = None,
    ppmloc: PPMLocator | None = None,
    eicloc: EICCodeRegistry | None = None,
    osm_update: bool = False,
    osm_live: bool = False,
) -> BasePipeline:
    """Build the right pipeline instance (BasePipeline subclass) for `input_dir`.

    Looks up the operator embedded in `input_dir`'s path and, via
    OPERATOR_METADATA[operator]["pipeline"], resolves which concrete pipeline
    class to build. `eicloc` is only ever forwarded to EntsoePipeline --
    every other pipeline's constructor doesn't accept it at all.

    Args:
        input_dir (Path): Path to the raw energy generation file (assuming CSV here).
        output_dir (Path, optional): Path to the directory where any output files may be
            saved. Defaults to None.
        gemloc (GEMLocator, optional): Pre-built GEM locator to reuse. Defaults to
            None, in which case GEM is disabled.
        ppmloc (PPMLocator, optional): Pre-built PPM locator to reuse. Defaults to
            None, in which case the resolved pipeline builds its own default.
        eicloc (EICCodeRegistry, optional): Pre-built EIC directory locator
            to reuse. Only relevant for the entsoe pipeline; ignored otherwise.
        osm_update (bool): Re-fetch OSM data from Overpass and overwrite the local
            ``overpass_..._plants.parquet`` file even if it already exists.
            Corresponds to the ``--update`` / ``-u`` CLI flag.
        osm_live (bool): Query Overpass live on every run, ignoring and not writing
            any local file. Corresponds to the ``--live`` CLI flag.

    Returns:
        BasePipeline: The concrete pipeline instance for `input_dir`.
    """
    operator = [p for p in Path(input_dir).parts if p in OPERATOR_METADATA][0]
    pipeline_name = OPERATOR_METADATA[operator].get("pipeline", "default")

    if pipeline_name == "entsoe":
        return EntsoePipeline(
            input_dir=input_dir,
            output_dir=output_dir,
            gemloc=gemloc,
            ppmloc=ppmloc,
            eicloc=eicloc,
            osm_update=osm_update,
            osm_live=osm_live,
        )

    return DefaultPipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        gemloc=gemloc,
        ppmloc=ppmloc,
        osm_update=osm_update,
        osm_live=osm_live,
    )


@dataclass
class SharedLocators:
    """Expensive, run-scoped locators built once and reused across a run's directories."""

    gemloc: GEMLocator | None
    ppmloc: PPMLocator | None
    eicloc: EICCodeRegistry | None


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
        gem_dir (Path | None): Path to the manually downloaded GEM data. GEM stays
            disabled (None) if not provided.
        output_dir (Path | None): Output directory, used as the cache dir for
            locators that persist a local file (e.g. the EIC directory).

    Returns:
        SharedLocators: The locators to reuse across every directory processed
            in this run.
    """
    gemloc = GEMLocator(gem_dir=gem_dir, cache_dir=output_dir) if gem_dir else None
    pipeline_name = OPERATOR_METADATA[source].get("pipeline", "default")

    ppmloc: PPMLocator | None = None
    eicloc: EICCodeRegistry | None = None

    if pipeline_name == "entsoe":
        # Use European regional assets only if country matches
        ppmloc = PPMLocator()
        eicloc = EICCodeRegistry(cache_dir=output_dir)
    # else:     # assume the default
    #     ppmloc = OSMPPLocator()  # todo: comment in (& define handling!) when ready

    return SharedLocators(gemloc=gemloc, ppmloc=ppmloc, eicloc=eicloc)
