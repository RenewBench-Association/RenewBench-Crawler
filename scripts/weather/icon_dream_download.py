#!/usr/bin/env python3
"""ICON-DREAM weather data downloader CLI.

Command-line interface for downloading ICON-DREAM reanalysis data
from DWD open data portal.
"""

import argparse
import sys

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.weather.icon_dream import IconDreamDownloader


def main() -> None:
    """Main entry point for ICON-DREAM downloader."""
    parser = argparse.ArgumentParser(
        description="Download ICON-DREAM reanalysis data from DWD"
    )

    parser.add_argument(
        "--list-variables",
        action="store_true",
        help="List all available ICON-DREAM variables and exit.",
    )

    parser.add_argument(
        "--region",
        choices=["global", "eu", "europe", "all"],
        default=None,
        metavar="REGION",
        help="Region to download. 'global': 13 km resolution, global coverage. "
        "'eu'/'europe': 6.5 km resolution, Europe only. 'all': both regions. "
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
        "--resume",
        action="store_true",
        help="Resume download from a previous checkpoint. "
        "Skips already downloaded year/month/variable combinations.",
    )

    parser.add_argument(
        "-o",
        "--cfg-options",
        type=str,
        nargs="+",
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_raw=/your/path/",
    )

    args = parser.parse_args()

    # Handle --list-variables
    region = args.region or "all"
    if region == "europe":
        region = "eu"

    if args.list_variables:
        IconDreamDownloader.print_available_variables(region=region)
        return

    # Load configuration
    regions = ["global", "eu"] if region == "all" else [region]
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None
    downloaders: dict[str, IconDreamDownloader] = {}

    def get_downloader(region_name: str) -> IconDreamDownloader:
        if region_name in downloaders:
            return downloaders[region_name]

        source = "icon_dream_global" if region_name == "global" else "icon_dream_eu"
        logger.info(f"Loading '{source}' YAML config...")
        config = load_config(source, overrides=overrides)

        downloader = IconDreamDownloader(
            output_path=config.paths.dst_dir_raw,
            years=args.years,
            months=args.months or None,
            variables=args.variables,
            region=region_name,
            dry_run=args.dry_run,
            resume=args.resume,
        )

        logger.info(f"Config loaded for {source}: {config}")
        downloaders[region_name] = downloader
        return downloader

    # Check if only metadata download is requested
    explicit_data_flags = {"-y", "--years", "-m", "--months", "-v", "--variables"}
    has_explicit_data_args = any(arg in explicit_data_flags for arg in sys.argv[1:])

    # Download metadata (unless explicitly disabled)
    if not args.no_metadata:
        for region_name in regions:
            get_downloader(region_name).download_metadata(dry_run=args.dry_run)

        # If no metadata skip AND no explicit data args, stop here (metadata only)
        if not has_explicit_data_args:
            return

    # Download data (with default arguments if none specified)
    for region_name in regions:
        get_downloader(region_name).download_data()


if __name__ == "__main__":
    main()
