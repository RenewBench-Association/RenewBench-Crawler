#!/usr/bin/env python
"""AESO DATA DOWNLOAD SCRIPT.

Download data from AESO box cloud storage site for Alberta, Canada.
"""

from argparse import ArgumentParser, Namespace
from datetime import datetime
from pprint import pformat

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.aeso import AesoDownloader
from rbc.energy.aeso.downloader import MIN_YEAR
from rbc.utils import setup_logging

SOURCE = "aeso"


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="AESO data download")
    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        default=list(range(MIN_YEAR, datetime.now().year + 1)),  # 5min: 2015-2023
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {list(range(MIN_YEAR, datetime.now().year + 1))}",
    )
    parser.add_argument(
        "-tr",
        "--temporal_resolutions",
        nargs="+",
        type=str,
        default=["1h", "5min"],  # these are the available resolutions
        help=f"Temporal resolutions to download. Example: --temporal_resolutions 1h 5min. "
        f"Default: {['1h', '5min']}",
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
        "--cfg_options",
        action="append",
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_raw=/your/path/ -o access.api_key=YOUR-SECRET-KEY",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinating AESO data download."""
    args = parse_arguments()
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_raw)
    logger.info(f"Flags for download:\n{pformat(vars(args), sort_dicts=False)}")
    logger.info(f"Config schema download:\n{pformat(dict(cfg), sort_dicts=False)}")

    downloader = AesoDownloader(
        token=cfg.access.api_key,
        output_path=cfg.paths.dst_dir_raw,
        years=args.years,
        temporal_resolutions=args.temporal_resolutions,
        resume=args.resume,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
