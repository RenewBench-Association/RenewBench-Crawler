#!/usr/bin/env python
"""TAIPOWER DATA DOWNLOAD SCRIPT.

Live production data download
"""

import argparse
from pathlib import Path

from rbc.energy.taipower.downloader import download_realtime_data


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = argparse.ArgumentParser(prog="Taipower live data download")
    parser.add_argument(
        "dst_dir", type=str, help="Destination directory for downloaded data."
    )
    return parser.parse_args()


def main() -> None:
    """Coordinating Taipower data download."""
    args = parse_arguments()
    dst_dir = Path(args.dst_dir)

    download_realtime_data(dst_dir)


if __name__ == "__main__":
    main()
