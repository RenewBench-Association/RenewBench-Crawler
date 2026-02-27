#!/usr/bin/env python3
"""BARRA REANALYSIS DATA DOWNLOAD SCRIPT.

Download BARRA reanalysis data from NCI THREDDS server.
"""

import argparse
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.weather.barra import BarraDownloader

SOURCE = "barra"


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
        "--model",
        choices=["R2", "RE2", "C2"],
        default="R2",
        metavar="MODEL",
        help="BARRA model/resolution. "
        "R2: 11 km deterministic, RE2: 22 km ensemble, C2: 4 km convective-scale. "
        "Default: R2",
    )

    parser.add_argument(
        "-y",
        "--years",
        type=int,
        nargs="+",
        default=[2020, 2021, 2022],
        metavar="YEARS",
        help="Years to download. Example: -y 2020 2021 2022. "
        "Default: [2020, 2021, 2022]",
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
        help="Variables to download. Examples: tas uas vas pr CAPE CIN. "
        "Default: Model-specific defaults (2m temp, wind, solar radiation, etc.)",
    )

    parser.add_argument(
        "-p",
        "--pressure-levels",
        type=int,
        nargs="+",
        default=None,
        metavar="LEVELS",
        help="Pressure levels to download (in hPa) for 3D variables. "
        "Example: -p 500 700 850 1000. Default: all standard levels",
    )

    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover available variables from THREDDS catalog (diagnostic).",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print download plan without downloading files.",
    )

    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Don't resume from checkpoint; start download from beginning.",
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
        BarraDownloader.print_available_variables(model=args.model)
        return

    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    logger.info(f"Config loaded for {SOURCE}:\n{cfg}")

    # Handle --discover flag
    if args.discover:
        downloader = BarraDownloader(
            output_path=cfg.paths.dst_dir_raw,
            model=args.model,
            years=[2020],
        )
        discovered = downloader.discover_variables()
        logger.info(f"Discovered {len(discovered)} variables from THREDDS catalog:")
        for var, info in sorted(discovered.items())[:10]:
            logger.info(f"  {var}: {info}")
        if len(discovered) > 10:
            logger.info(f"  ... and {len(discovered) - 10} more")
        return

    downloader = BarraDownloader(
        output_path=cfg.paths.dst_dir_raw,
        model=args.model,
        years=args.years,
        months=args.months,
        variables=args.variables,
        pressure_levels=args.pressure_levels,
        dry_run=args.dry_run,
        resume=not args.no_resume,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
