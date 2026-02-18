#!/usr/bin/env python3
"""BARRA reanalysis data downloader CLI.

Command-line interface for downloading BARRA reanalysis data from NCI THREDDS server.

BARRA offers three models:
- R2: 11 km deterministic reanalysis, Australia + surrounding
- RE2: 22 km ensemble reanalysis, Australia + surrounding
- C2: 4 km convective-scale reanalysis, Australia only

All data is downloaded at 1-hour temporal frequency.

Example usage:
    # Download default variables for R2 model, 2020-2021
    python barra_download.py --model R2 --years 2020 2021

    # Download specific variables for C2
    python barra_download.py -m C2 -y 2022 2023 -v tas uas vas CAPE CIN

    # List available variables
    python barra_download.py --list-variables --model C2

    # Dry run to see what would be downloaded
    python barra_download.py -m R2 -y 2020 -m 01 02 --dry-run
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

from rbc.weather.barra import BarraDownloader


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = "DEBUG" if verbose else "INFO"
    logger.enable("rbc")
    logger.remove()
    logger.add(sys.stderr, level=level, format="<level>{level: <8}</level> | {message}")


def main() -> None:
    """Main entry point for BARRA downloader."""
    parser = argparse.ArgumentParser(
        prog="barra_download",
        description="Download BARRA reanalysis data from NCI THREDDS server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
BARRA models:
  R2   - Moderate-scale deterministic (11 km), Australia + surrounding
  RE2  - Moderate-scale ensemble (22 km), Australia + surrounding
  C2   - Convective-scale (4 km), Australia only

All data is downloaded at 1-hourly frequency.

Examples:
  # Download R2 data for 2020-2021
  %(prog)s --model R2 --years 2020 2021

  # Download C2 with convective diagnostics
  %(prog)s -m C2 -y 2022 2023 -v tas uas vas CAPE CIN

  # List available variables for each model
  %(prog)s --list-variables --model R2
  %(prog)s --list-variables --model C2
        """,
    )

    parser.add_argument(
        "--list-variables",
        action="store_true",
        help="List all available variables for the resolution and exit.",
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
        metavar="YEAR",
        help="Years to download. Example: -y 2020 2021 2022. Default: [2020, 2021, 2022]",
    )

    parser.add_argument(
        "-m",
        "--months",
        type=str,
        nargs="+",
        choices=[f"{i:02d}" for i in range(1, 13)],
        metavar="MONTH",
        help="Months to download (01-12). Example: -m 01 02 03. Default: all months",
    )

    parser.add_argument(
        "-v",
        "--variables",
        type=str,
        nargs="+",
        metavar="VAR",
        help="Variables to download. Examples: tas uas vas pr CAPE CIN. "
        "Default: resolution-specific defaults (2m temp, wind, solar radiation, etc.)",
    )

    parser.add_argument(
        "-p",
        "--pressure-levels",
        type=int,
        nargs="+",
        metavar="LEVEL",
        help="Pressure levels to download (in hPa) for 3D variables. "
        "Example: -p 500 700 850 1000. "
        "Default: [10, 20, 30, 50, 70, 100, 150, 200, 250, 300, 400, 500, 600, 700, 750, 800, 850, 900, 925, 950, 975, 1000]",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("./barra_data"),
        metavar="PATH",
        help="Output directory for downloaded files. Default: ./barra_data",
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
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        # Handle --list-variables
        if args.list_variables:
            downloader = BarraDownloader(
                output_path=args.output,
                model=args.model,
                years=[2020],  # Dummy year for variable discovery
            )
            variables = downloader.list_variables()
            logger.info(
                f"Available variables for BARRA-{args.model} ({len(variables)} total):"
            )
            for i, var in enumerate(variables, 1):
                print(f"  {i:3d}. {var}")
            return

        # Handle --discover
        if args.discover:
            downloader = BarraDownloader(
                output_path=args.output,
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

        # Create downloader
        downloader = BarraDownloader(
            output_path=args.output,
            model=args.model,
            years=args.years,
            months=args.months,
            variables=args.variables,
            pressure_levels=args.pressure_levels,
            dry_run=args.dry_run,
            resume=not args.no_resume,
        )

        # Log configuration
        completed, total = downloader.get_file_status()
        logger.info(
            f"Configuration: {args.model} model, "
            f"1-hourly frequency, "
            f"years={args.years}, "
            f"variables={len(downloader.variables)}"
        )
        logger.info(f"Download progress: {completed}/{total} month(s) complete")

        # Start download
        downloader.download()

    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
