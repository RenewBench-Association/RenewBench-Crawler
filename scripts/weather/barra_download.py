#!/usr/bin/env python3
"""BARRA REANALYSIS DATA DOWNLOAD SCRIPT.

Download BARRA reanalysis data from NCI THREDDS server.
"""

import argparse
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.weather.barra import BarraDownloader


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="BARRA reanalysis data download")

    parser.add_argument(
        "--list-variables",
        action="store_true",
        help="List all available BARRA variables and exit.",
    )

    parser.add_argument(
        "-r",
        "--region",
        choices=["R2", "r2", "C2", "c2", "C2_20min", "c2_20min"],
        default="R2",
        metavar="REGION",
        help="BARRA region/model. "
        "R2: 11 km deterministic (1hr), C2: 4 km convective-scale (1hr), "
        "C2_20min: 4 km convective-scale (20min). "
        "Default: R2",
    )

    parser.add_argument(
        "--no-invariant",
        action="store_true",
        help="Do not download invariant variables.",
    )

    parser.add_argument(
        "-y",
        "--years",
        type=int,
        nargs="+",
        default=[2020, 2021, 2022, 2023, 2024, 2025],
        metavar="YEARS",
        help="Years to download. Example: -y 2020 2021 2022. "
        "Default: [2020, 2021, 2022, 2023, 2024, 2025]",
    )

    parser.add_argument(
        "-m",
        "--months",
        type=str,
        nargs="+",
        choices=[f"{i:02d}" for i in range(1, 13)],
        metavar="MONTHS",
        help="Months to download (01-12). Example: -m 01 02 03. Default: All months",
    )

    parser.add_argument(
        "-v",
        "--variables",
        type=str,
        nargs="+",
        default=None,
        metavar="VARIABLES",
        help="Variables to download. Examples: -v 1.5m_temperature, total_precipitation. "
        "Default: Common renewable energy variables",
    )

    parser.add_argument(
        "-p",
        "--pressure-levels",
        type=int,
        nargs="+",
        default=None,
        metavar="LEVELS",
        help="Pressure levels to download (in hPa) for 3D variables. "
        "Example: -p 500 700 850 1000. Default: model dependent, all available levels between 950 and 1000 hPa.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print download plan without downloading. Useful for debugging file selections.",
    )

    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume from checkpoint; start download from beginning.",
    )

    parser.add_argument(
        "-o",
        "--cfg-options",
        type=str,
        nargs="+",
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_raw=/your/path/",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinate BARRA data download."""
    args = parse_arguments()

    # Handle --list-variables flag
    if args.list_variables:
        BarraDownloader.print_available_variables(model=args.region)
        return

    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    config = load_config(source="barra", overrides=overrides)
    logger.info(f"Config loaded for BARRA:\n{config}")

    downloader = BarraDownloader(
        output_path=config.paths.dst_dir_raw,
        model=args.region,
        years=args.years,
        months=args.months,
        variables=args.variables,
        pressure_levels=args.pressure_levels,
        include_invariants=not args.no_invariant,
        dry_run=args.dry_run,
        resume=not args.no_resume,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
