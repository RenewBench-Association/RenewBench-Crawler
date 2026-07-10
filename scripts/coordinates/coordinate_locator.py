#!/usr/bin/env python
"""COORDINATE FINDING SCRIPT."""

from argparse import ArgumentParser, Namespace
from pathlib import Path

from loguru import logger

from rbc.config.loader import CONFIGS_DIR, load_config
from rbc.coordinates.orchestrator import perform_coordinate_finding
from rbc.utils import setup_logging

SOURCES = [p.stem for p in sorted(Path(CONFIGS_DIR, "energy").glob("*.yaml"))]


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace with parsed command line arguments.
    """
    parser = ArgumentParser(
        description="Find coordinates for power plants and render an interactive map."
    )
    parser.add_argument(
        "--source",
        "-s",
        type=str,
        choices=SOURCES,
        help="Energy source to find locations for. Only one source can be analysed at a "
        "time.",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        nargs="+",  # accept one or more arguments and group them into a list
        help="Directory where raw files from the source (inputs for coordinate finding) are "
        "located. This can be the general source folder (e.g. with all temporal "
        "resolutions), a single folder containing CSV files, or an explicit list of "
        "zone folders. If None is provided, the YAML config's dst_dir_raw will be used.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Directory where the outputs (overpass parquet file and, for entsoe, "
        "enriched plant details CSV files are written. If None is provided, "
        "a 'coordinates' folder in the YAML config's dst_dir_raw will be created "
        "and used.",
    )
    parser.add_argument(
        "--gem-dir",
        type=Path,
        help=(
            "Directory containing manually downloaded Global Energy Monitor (GEM) "
            "tracker xlsx files (https://globalenergymonitor.org/download-data). "
            "When given, GEM is used as an additional coordinate source. If None is "
            "provided, GEM matching is disabled."
        ),
    )
    parser.add_argument(
        "--update",
        "-u",
        action="store_true",
        help=(
            "Re-fetch OSM power plant data from Overpass API and overwrite the local "
            "overpass_..._plants.parquet file, even if it already exists."
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


def main():
    """Coordinating coordinate finding."""
    args = parse_arguments()
    cfg = load_config(source=args.source)

    output_dir = (
        args.output if args.output else Path(cfg.paths.dst_dir_raw, "coordinates")
    )
    setup_logging(output_dir=output_dir)

    gem_dir = args.gem_dir if args.gem_dir and args.gem_dir.is_dir() else None
    if gem_dir is None:
        logger.warning(
            f"--gem-dir '{args.gem_dir}' is not a directory — GEM matching disabled."
        )

    input_paths: list[Path] = (
        args.input if args.input else [Path(cfg.paths.dst_dir_raw)]
    )

    perform_coordinate_finding(
        source=args.source,
        input_paths=input_paths,
        output_dir=output_dir,
        gem_dir=gem_dir,
        update=args.update,
        live=args.live,
    )


if __name__ == "__main__":
    main()
