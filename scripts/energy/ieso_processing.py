#!/usr/bin/env python
"""IESO DATA PROCESSING SCRIPT.

Process raw data previously downloaded from IESO website for Ontario, Canada.
"""

from argparse import ArgumentParser, Namespace

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.ieso.processor import IesoProcessor
from rbc.utils import setup_logging

SOURCE = "ieso"


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="IESO data processing")
    parser.add_argument(
        "-o",
        "--cfg_options",
        action="append",
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_proc=/your/path/",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinating IESO data processing."""
    args = parse_arguments()
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_proc)
    logger.info(f"Flags for the '{SOURCE}' processing:\n{args}")
    logger.info(f"Config for the '{SOURCE}' processing:\n{cfg}")

    downloader = IesoProcessor(
        input_path=cfg.paths.dst_dir_raw,
        output_path=cfg.paths.dst_dir_proc,
    )
    for input_file_path in downloader.input_path.glob("*.csv"):
        downloader.process(input_file_path=input_file_path)


if __name__ == "__main__":
    main()
