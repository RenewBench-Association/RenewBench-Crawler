"""Public surface of the coordinate-finding pipelines subpackage.

Exposes the pipeline classes (BasePipeline and its concrete subclasses),
`make_pipeline` to build the right pipeline instance for a given directory,
and `build_shared_resources` to build the expensive, run-scoped resources
(locators and registries) that get reused across every directory in one
`perform_coordinate_finding` run.
"""

from dataclasses import dataclass
from pathlib import Path

from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.natural_earth import RegionRegistry
from rbc.coordinates.locators.osm_api import OverpassLocator
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
    "SharedResources",
    "build_shared_resources",
    "make_pipeline",
]


def make_pipeline(
    input_dir: Path,
    output_dir: Path | None = None,
    gem_loc: GEMLocator | None = None,
    ppdb_loc: PPMLocator | OSMPPLocator | None = None,
    osm_loc: OverpassLocator | None = None,
    region_reg: RegionRegistry | None = None,
    eic_reg: EICCodeRegistry | None = None,
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
        osm_loc (OverpassLocator, optional): Pre-built OSM Overpass locator to reuse.
            Defaults to None, in which case the resolved pipeline builds its own default.
        region_reg (RegionRegistry, optional): Pre-built region registry to reuse.
            Defaults to None, in which case the resolved pipeline builds its own.
        eic_reg (EICCodeRegistry, optional): Pre-built EIC directory locator
            to reuse. Only relevant for the entsoe pipeline; ignored otherwise.

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
            osm_loc=osm_loc,
            region_reg=region_reg,
            eic_reg=eic_reg,
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
        osm_loc=osm_loc,
        region_reg=region_reg,
    )


@dataclass
class SharedResources:
    """Expensive resources built once per run and reused across all its directories.

    Attributes:
        gem_loc (GEMLocator | None): GEM locator (local or fallback tracker files).
        ppdb_loc (PPMLocator | OSMPPLocator | None): Power plant database locator.
        osm_loc (OverpassLocator | None): OSM Overpass API locator.
        region_reg (RegionRegistry | None): Natural Earth admin-1 region lookup.
        eic_reg (EICCodeRegistry | None): ENTSO-E EIC directory (entsoe pipeline only).
    """

    gem_loc: GEMLocator | None
    ppdb_loc: PPMLocator | OSMPPLocator | None
    osm_loc: OverpassLocator | None
    region_reg: RegionRegistry | None
    eic_reg: EICCodeRegistry | None


def build_shared_resources(
    source: str,
    resources_dir: Path | None,
    update: bool = False,
    osm_live: bool = False,
) -> SharedResources:
    """Build the expensive (network/CSV/parquet-backed) resources shared by one run.

    Callers processing multiple directories for the same source in one run (e.g.
    multiple ENTSO-E bidding zones) should build these once and pass them into
    `make_pipeline` for every directory, rather than paying the construction cost
    (network/CSV/parquet reads) per directory. Each resource keeps its local files in
    its own subfolder of `resources_dir` (`gem/`, `ppm/`, `osmpp/`, `eic/`, `overpass/`,
    `natural_earth/`) so they are reused across runs.

    Args:
        source (str): Name of the energy source, e.g. "entsoe". Used to resolve
            which pipeline's resources are actually needed.
        resources_dir (Path | None): Directory of the resources shared by all energy
            sources. Manually downloaded GEM tracker xlsx files are expected in its
            `gem/` subfolder (trackers missing there fall back to the files in PPM's
            cloud storage). If None, no local files are read or written.
        update (bool, optional): Download fresh copies of every resource (and re-query
            Overpass once per country), overwriting the local files. Corresponds to the
            ``--update`` / ``-u`` CLI flag. Defaults to False.
        osm_live (bool, optional): Query Overpass without reading or writing any local
            file. Corresponds to the ``--live`` CLI flag. Defaults to False.

    Returns:
        SharedResources: The resources to reuse across every directory processed
            in this run.
    """

    def subdir(name: str) -> Path | None:
        """Resolve one resource's subfolder of `resources_dir`, if there is one.

        Args:
            name (str): Name of the resource's subfolder, e.g. "gem".

        Returns:
            Path | None: The subfolder, or None if no `resources_dir` was given.
        """
        return Path(resources_dir, name) if resources_dir else None

    gem_loc: GEMLocator = GEMLocator(gem_dir=subdir("gem"), update=update)
    ppdb_loc: PPMLocator | OSMPPLocator
    eic_reg: EICCodeRegistry | None

    # locators defined by the pipeline
    pipeline_name = OPERATOR_METADATA[source].get("pipeline", "default")
    if pipeline_name == "entsoe":
        ppdb_loc = PPMLocator(cache_dir=subdir("ppm"), update=update)
        eic_reg = EICCodeRegistry(cache_dir=subdir("eic"), update=update)
    else:
        ppdb_loc = OSMPPLocator(cache_dir=subdir("osmpp"), update=update)
        eic_reg = None

    osm_loc = OverpassLocator(
        cache_dir=subdir("overpass"), update=update, live=osm_live
    )
    region_reg = RegionRegistry(cache_dir=subdir("natural_earth"), update=update)

    return SharedResources(
        gem_loc=gem_loc,
        ppdb_loc=ppdb_loc,
        osm_loc=osm_loc,
        region_reg=region_reg,
        eic_reg=eic_reg,
    )
