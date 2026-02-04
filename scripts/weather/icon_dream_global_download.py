#!/usr/bin/env python3
"""ICON-DREAM Global weather data downloader CLI.

Command-line interface for downloading ICON-DREAM Global reanalysis data
from DWD open data portal.
"""

import argparse

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.weather.icon_dream_global import IconDreamGlobalDownloader


def main() -> None:
    """Main entry point for ICON-DREAM Global downloader."""
    parser = argparse.ArgumentParser(
        description="Download ICON-DREAM Global reanalysis data from DWD"
    )

    parser.add_argument(
        "--list-variables",
        action="store_true",
        help="List available variables and exit",
    )

    parser.add_argument(
        "--download-metadata",
        action="store_true",
        help="Download grid metadata files and exit",
    )

    parser.add_argument(
        "-y",
        "--years",
        type=int,
        nargs="+",
        default=[2020, 2021, 2022, 2023, 2024, 2025],
        help="Years to download (default: 2020-2025)",
    )

    parser.add_argument(
        "-m",
        "--months",
        type=str,
        nargs="+",
        choices=[f"{i:02d}" for i in range(1, 13)],
        help="Months to download (01-12, default: all months)",
    )

    parser.add_argument(
        "-v",
        "--variables",
        type=str,
        nargs="+",
        default=["temperature"],
        help="Variables to download (default: temperature)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print download plan without downloading",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint",
    )

    parser.add_argument(
        "-o",
        "--cfg-options",
        type=str,
        nargs="+",
        help="Override config values (e.g., paths.dst_dir_raw=/custom/path)",
    )

    args = parser.parse_args()

    # Handle --list-variables
    if args.list_variables:
        IconDreamGlobalDownloader.print_available_variables()
        return

    # Load configuration
    logger.info("Loading 'icon_dream_global' YAML config...")
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None
    config = load_config("icon_dream_global", overrides=overrides)

    # Initialize downloader
    downloader = IconDreamGlobalDownloader(
        output_path=config.paths.dst_dir_raw,
        years=args.years,
        months=args.months or None,
        variables=args.variables,
        dry_run=args.dry_run,
        resume=args.resume,
    )

    # Handle --download-metadata
    if args.download_metadata:
        logger.info(f"Config loaded for icon_dream_global: {config}")
        downloader.download_metadata(dry_run=args.dry_run)
        return

    # Start download
    logger.info(f"Config loaded for icon_dream_global: {config}")
    downloader.download_data()


if __name__ == "__main__":
    main()
