"""Local storage of the resource files that coordinate finding downloads.

Every remote resource (e.g. PPM's and osm-powerplants' CSVs, Natural Earth's zip, GEM's
fallback trackers) is kept in its own subfolder of the run's ``resources_dir``. Repeated
runs then reuse one pinned copy instead of re-downloading, which keeps results comparable
and lets a run work without a network connection.
"""

from pathlib import Path

import requests
from loguru import logger

DOWNLOAD_TIMEOUT = 300
CHUNK_SIZE = 1024 * 1024  # download in 1 MB chunks
HEADER = {
    "User-Agent": (
        "RenewBench-Crawler/1.0 "
        "(+https://github.com/RenewBench-Association/RenewBench-Crawler)"
    )
}


def fetch_resource(url: str, file_path: Path, update: bool = False) -> Path | None:
    """Get a local copy of a remote resource file, downloading it only when needed.

    An existing file is used as is, unless `update` asks for a fresh copy. Download to a
    temporary file that is renamed afterward, so an interrupted download cannot leave a
    half-written file behind. If a download fails but an older copy exists, that copy is
    used (with a warning), like the Overpass locator's stale-cache fallback.

    Args:
        url (str): URL of the remote resource file.
        file_path (Path): Path of the local copy.
        update (bool, optional): Download a fresh copy even if the file already exists.
            Defaults to False.

    Returns:
        Path | None: Path of the local copy, or None if there is none and the download
            failed.
    """
    if file_path.is_file() and not update:
        logger.info(f"Using local resource file '{file_path}'.")
        return file_path

    tmp_path = file_path.with_name(f"{file_path.name}.part")
    try:
        logger.info(f"Downloading '{url}' (this may take a while)...")
        with requests.get(
            url, headers=HEADER, stream=True, timeout=DOWNLOAD_TIMEOUT
        ) as response:
            response.raise_for_status()

            file_path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    f.write(chunk)

        tmp_path.replace(file_path)
        size_mb = file_path.stat().st_size / 1024**2
        logger.info(f"Resource file stored → '{file_path}' ({size_mb:.1f} MB)")
        return file_path

    except (requests.RequestException, OSError) as e:
        tmp_path.unlink(missing_ok=True)

        if file_path.is_file():
            logger.warning(
                f"Could not download '{url}' ({e}). Using local '{file_path}' instead."
            )
            return file_path

        logger.error(f"Could not download '{url}' ({e}) and no local copy exists.")
        return None
