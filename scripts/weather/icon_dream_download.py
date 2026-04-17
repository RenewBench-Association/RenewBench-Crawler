#!/usr/bin/env python3
"""ICON-DREAM weather data downloader CLI.

Command-line interface for downloading ICON-DREAM reanalysis data
from DWD open data portal.
"""

import argparse
import sys
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.utils import setup_logging
from rbc.weather.icon_dream import IconDreamDownloader


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="ICON DREAM reanalysis data download")

    parser.add_argument(
        "--list-variables",
        action="store_true",
        help="List all available ICON-DREAM variables and exit.",
    )

    parser.add_argument(
        "-M",
        "--model",
        choices=["global", "eu", "europe", "all"],
        default="all",
        metavar="MODEL",
        help="Model to download. 'global': 13 km resolution, global coverage. "
        "'eu'/'europe': 6.5 km resolution, Europe only. 'all': both models. "
        "Default: all",
    )

    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Skip downloading grid metadata files. Default: metadata files are downloaded.",
    )

    parser.add_argument(
        "-y",
        "--years",
        type=int,
        nargs="+",
        default=[2020, 2021, 2022, 2023, 2024, 2025],
        metavar="YEARS",
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {[2020, 2021, 2022, 2023, 2024, 2025]}",
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
        help="ICON-DREAM variables to download. Example: -v 2m_temperature total_precipitation. "
        "Default: Common renewable energy variables",
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
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_raw=/your/path/",
    )
    return parser.parse_args()


def get_downloader(
    model_name: str,
    args: argparse.Namespace,
    overrides: dict | None,
    downloaders: dict[str, IconDreamDownloader],
) -> IconDreamDownloader:
    """Get or create an IconDreamDownloader for the specified model.

    Returns a cached downloader if available, otherwise creates a new one.
    Loads configuration from YAML config files based on model.

    Args:
        model_name (str): Model identifier ("global" or "eu").
        args (argparse.Namespace): Parsed command line arguments.
        overrides (dict | None): Configuration overrides from command line.
        downloaders (dict[str, IconDreamDownloader]): Cache of downloaders by model.

    Returns:
        IconDreamDownloader: Initialized downloader for the specified model.
    """
    if model_name in downloaders:
        return downloaders[model_name]

    source = "icon_dream_global" if model_name == "global" else "icon_dream_eu"
    logger.info(f"Loading '{source}' YAML config...")
    cfg = load_config(source, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_raw)
    logger.info(f"Flags for the '{source}' download:\n{args}")
    logger.info(f"Config for the '{source}' download:\n{cfg}")

    downloader = IconDreamDownloader(
        output_path=cfg.paths.dst_dir_raw,
        years=args.years,
        months=args.months or None,
        variables=args.variables,
        model=model_name,
        dry_run=args.dry_run,
        resume=args.resume,
    )

    logger.info(f"Config loaded for {source}: {cfg}")
    downloaders[model_name] = downloader
    return downloader


def main() -> None:
    """Coordinate ICON-DREAM data download."""
    args = parse_arguments()
    model = args.model

    if args.list_variables:
        IconDreamDownloader.print_available_variables(model=model)
        return

    # Load configuration
    models = ["global", "eu"] if model == "all" else [model]
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None
    downloaders: dict[str, IconDreamDownloader] = {}

    # Check if only metadata download is requested
    explicit_data_flags = {"-y", "--years", "-m", "--months", "-v", "--variables"}
    has_explicit_data_args = any(arg in explicit_data_flags for arg in sys.argv[1:])

    for model_name in models:
        model_downloader = get_downloader(model_name, args, overrides, downloaders)

        # Download metadata (unless explicitly disabled)
        if not args.no_metadata:
            model_downloader.download_metadata(dry_run=args.dry_run)

        # Download data (with default arguments if none specified)
        if has_explicit_data_args:
            model_downloader.download_data()


if __name__ == "__main__":
    main()
