#!/usr/bin/env python
"""ERA5 REANALYSIS DATA DOWNLOAD SCRIPT.

Download ERA5 reanalysis data from Copernicus Climate Data Store.
"""

import argparse
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.weather.era5 import Era5Downloader

SOURCE = "era5"


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="ERA5 reanalysis data download")

    parser.add_argument(
        "--list-variables",
        action="store_true",
        help="List all available ERA5 variables and exit.",
    )

    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        default=list(range(2020, 2026)),
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {list(range(2020, 2026))}",
    )
    parser.add_argument(
        "-m",
        "--months",
        nargs="+",
        type=str,
        choices=[f"{i:02d}" for i in range(1, 13)],
        default=[f"{i:02d}" for i in range(1, 13)],
        metavar="MONTHS",
        help="Months to download (01-12). Example: -m 01 02 03. Default: All months",
    )
    parser.add_argument(
        "-v",
        "--variables",
        nargs="+",
        type=str,
        default=None,
        metavar="VARIABLES",
        help="ERA5 variables to download. Example: -v 10m_u_component_of_wind 10m_v_component_of_wind. "
        "Default: Common renewable energy variables",
    )
    parser.add_argument(
        "-a",
        "--area",
        nargs=4,
        type=float,
        default=None,
        metavar=("NORTH", "WEST", "SOUTH", "EAST"),
        help="Bounding box in degrees [North, West, South, East]. Default: World (all)",
    )
    parser.add_argument(
        "-pl",
        "--pressure_levels",
        nargs="*",
        type=str,
        default=None,
        metavar="PRESSURE_LEVELS",
        help="Pressure levels in hPa. Example: -pl 1000 975 950. "
        "Use -pl alone for default levels. "
        "Default: Pressure levels (1000, 975, 950 hPa) unless -ml is specified",
    )
    parser.add_argument(
        "-ml",
        "--model_levels",
        nargs="*",
        type=str,
        default=None,
        metavar="MODEL_LEVELS",
        help="Model levels (1-137). Example: -ml 135 136 137. "
        "Use -ml alone for default levels. "
        "Can be combined with -pl for both types in one request.",
    )
    parser.add_argument(
        "-f",
        "--file_format",
        type=str,
        choices=["grib", "netcdf"],
        default="grib",
        help="Output file format. Choices: grib, netcdf. "
        "Default: grib (more space-efficient)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print MARS requests without submitting them to CDS API. "
        "Useful for debugging request parameters.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume download from a previous checkpoint. "
        "Skips already downloaded year/month/level_type combinations.",
    )
    parser.add_argument(
        "-o",
        "--cfg_options",
        action="append",
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_raw=/your/path/ -o "
        "access.api_key=YOUR-CDS-KEY",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinate ERA5 data download."""
    args = parse_arguments()

    # Handle --list-variables flag
    if args.list_variables:
        Era5Downloader.print_available_variables()
        return

    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    logger.info(f"Config loaded for {SOURCE}:\n{cfg}")

    # Handle pressure and model levels
    # nargs="*" returns empty list [] if flag is used without arguments
    pressure_levels = args.pressure_levels if args.pressure_levels is not None else None
    model_levels = args.model_levels if args.model_levels is not None else None

    downloader = Era5Downloader(
        api_key=cfg.access.api_key,
        output_path=cfg.paths.dst_dir_raw,
        years=args.years,
        months=args.months,
        variables=args.variables,
        area=args.area,
        pressure_levels=pressure_levels,
        model_levels=model_levels,
        file_format=args.file_format,
        resume=args.resume,
        dry_run=args.dry_run,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
