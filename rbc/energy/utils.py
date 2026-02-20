"""UTILS.

Shared helper functions for data downloaders
"""

from pathlib import Path

import pandas as pd
from loguru import logger

WORKERS = 4
MAX_RETRIES = 3
RETRY_DELAY = 5


class DataStructureError(Exception):
    """Raised when a data source changes its structure significantly."""

    pass


def write_df_to_csv(df: pd.DataFrame, file_path: Path, index: bool = False) -> None:
    """Write dataframe to csv file.

    Args:
        df (pd.DataFrame): Pandas dataframe to be stored in csv file.
        file_path (Path): Path to the csv file.
        index (bool, optional): Whether to include the df index in the
            csv (True) or not (False). Defaults to False.
    """
    if file_path.suffix != ".csv":
        file_path = file_path.with_suffix(".csv")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(file_path, index=index)
    logger.info(f"Successfully wrote dataframe to '{file_path}'")
