#!/usr/bin/env python3
"""BARRA2 REANALYSIS DATA DOWNLOAD SCRIPT.

Download BARRA2 reanalysis data from NCI THREDDS server.
"""

from argparse import ArgumentParser, Namespace

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.utils import setup_logging
from rbc.weather.barra import Barra2Downloader

SOURCE = "barra2"


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="BARRA2 reanalysis data download")

    parser.add_argument(
        "--list-variables",
        action="store_true",
        help="List all available BARRA2 variables and exit.",
    )

    parser.add_argument(
        "-r",
        "--region",
        choices=["R2", "r2", "C2", "c2", "C2_20min", "c2_20min", "all"],
        default=None,
        metavar="REGION",
        help="BARRA2 region/model. "
        "R2: 11 km deterministic (1hr), C2: 4 km convective-scale (1hr), "
        "C2_20min: 4 km convective-scale (20min). "
        "For --list-variables, default is all models. For download, default is R2.",
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
        dest="resume",
        action="store_false",
        help="Do not resume download from a previous checkpoint.",
    )
    parser.set_defaults(resume=True)

    parser.add_argument(
        "-o",
        "--cfg-options",
        action="append",
        nargs="+",
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_raw=/your/path/",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinate BARRA2 data download."""
    args = parse_arguments()

    # Handle --list-variables flag
    if args.list_variables:
        Barra2Downloader.print_available_variables(model=args.region or "all")
        return

    selected_region = args.region or "R2"
    if selected_region.lower() == "all":
        raise ValueError(
            "'all' is only valid with --list-variables, not for downloads."
        )
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None
    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_raw)
    logger.info(f"Flags for the '{SOURCE}' download:\n{args}")
    logger.info(f"Config for the '{SOURCE}' download:\n{cfg}")

    downloader = Barra2Downloader(
        output_path=cfg.paths.dst_dir_raw,
        model=selected_region,
        years=args.years,
        months=args.months,
        variables=args.variables,
        pressure_levels=args.pressure_levels,
        include_invariants=not args.no_invariant,
        dry_run=args.dry_run,
        resume=args.resume,
    )

    logger.info(f"Config loaded for BARRA2:\n{cfg}")

    downloader.download_data()


if __name__ == "__main__":
    main()
