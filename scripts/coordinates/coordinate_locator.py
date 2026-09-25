#!/usr/bin/env python
"""COORDINATE FINDING SCRIPT."""

from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import cast

from rbc.config.loader import CONFIGS_DIR, load_config
from rbc.config.schema import CoordinatesConfig
from rbc.coordinates.orchestrator import perform_coordinate_finding
from rbc.utils import setup_logging

SOURCES = [p.stem for p in sorted(Path(CONFIGS_DIR, "energy").glob("*.yaml"))]


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace with parsed command line arguments.
    """
    parser = ArgumentParser(
        description=(
            "Find coordinates for power plants and render an interactive map. "
            "Resources shared by all sources are kept in the resources_dir of the "
            "'coordinates' YAML config, e.g. OSM files, or manually downloaded GEM "
            "tracker xlsx files (in its 'gem' subfolder)."
        )
    )
    parser.add_argument(
        "--source",
        "-s",
        type=str,
        choices=SOURCES,
        help="Energy source to find locations for. Only one source can be analysed at a time.",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        nargs="+",  # accept one or more arguments and group them into a list
        help=(
            "Directory where raw files from the source (inputs for coordinate finding) are "
            "located. This can be the general source folder (e.g. with all temporal "
            "resolutions), a single folder containing CSV files, or an explicit list of "
            "zone folders. If None is provided, the YAML config's dst_dir_raw will be used."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help=(
            "Directory where the outputs (coordinates and fuzzy matching CSV files, "
            "map and logs) are written. If None is provided, a 'coordinates' folder in "
            "the YAML config's dst_dir_raw will be created and used."
        ),
    )
    parser.add_argument(
        "--update",
        "-u",
        action="store_true",
        help=(
            "Download fresh copies of every resource in the resources_dir (PPM's and "
            "osm-powerplants' CSVs, the EIC directory, Natural Earth, GEM's fallback "
            "trackers) and re-query the Overpass API once per country, overwriting the "
            "local files."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Query the Overpass API on every run. The local OSM parquet file is neither "
            "read nor written."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Coordinating coordinate finding."""
    args = parse_arguments()
    cfg = load_config(source=args.source)
    coordinates_cfg = cast(CoordinatesConfig, load_config(source="coordinates"))

    output_dir = (
        args.output if args.output else Path(cfg.paths.dst_dir_raw, "coordinates")
    )
    setup_logging(output_dir=output_dir)

    input_paths: list[Path | str] = (
        args.input if args.input else [Path(cfg.paths.dst_dir_raw)]
    )

    perform_coordinate_finding(
        source=args.source,
        input_dirs=input_paths,
        output_dir=output_dir,
        resources_dir=coordinates_cfg.paths.resources_dir,
        update=args.update,
        live=args.live,
    )


if __name__ == "__main__":
    main()
