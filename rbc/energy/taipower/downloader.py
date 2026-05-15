"""TAIPOWER DATA DOWNLOADER.

Remote access of Taipower website to fetch current live data with.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests.exceptions
from requests import Session
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Taipei")
URL = "http://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json"

COLUMNS = [
    "fueltype",
    "fueltype_subcategory",
    "name",
    "capacity",
    "output",
    "percentage",
    "remark_xi",
    "additional_3",
]


def download_realtime_data(dst_dir: Path) -> None:
    """Download realtime production data from TaiPower website.

    This function does not use standard logging or raises errors. Instead,
    print statements and sys.exit are implemented for automatic handling via bash.

    Args:
        dst_dir (Path): Path to directory to save data.
    """
    if not dst_dir.is_dir():
        print("Destination directory does not exist!")
        sys.exit(1)

    session = Session()

    # Spoof a standard web browser to bypass the 403 Forbidden error.
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    response = session.get(URL)

    if not response.status_code == 200:
        print(
            f"Request query failed with status code "
            f"{response.status_code} and {response.content!r}"
        )
        sys.exit(1)

    try:
        data = response.json()
        dt = data[""]
        dt = (
            datetime.strptime(dt, "%Y-%m-%d %H:%M").replace(tzinfo=TIMEZONE).isoformat()
        )
        dt_str = dt.replace(":", "-")  # Windows-safe string
        df = pd.DataFrame(data["dataset"])

    except (requests.exceptions.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"Failed parsing of JSON from {URL} with a {type(e).__name__}!")
        sys.exit(1)

    csv_path = Path(dst_dir, dt_str + ".csv")

    # check correct number of columns
    if len(df.iloc[0]) != len(COLUMNS):
        print(
            f"Number of data columns has changed from {len(COLUMNS)} to "
            f"{len(df.columns)}! Will save data but without any processing!"
        )
        save_df_to_csv(df=df, csv_path=csv_path)

    # check numerical data in correct columns
    df[[3, 4]] = df[[3, 4]].astype(object)
    df[[3, 4]] = df[[3, 4]].apply(pd.to_numeric, errors="coerce")

    if df[4].isna().all():
        print(
            "Production data is entirely NaN - column order may have changed! "
            "Will save data but without any processing!"
        )
        save_df_to_csv(df=df, csv_path=csv_path)

    # process generation data
    df.columns = COLUMNS
    df.insert(0, "datetime", dt)
    df["fueltype"] = df.fueltype.str.split("<b>").str[1]
    df["fueltype"] = df.fueltype.str.split("</b>").str[0]
    df = df[df.name != "Subtotal"]

    save_df_to_csv(df=df, csv_path=csv_path)


def save_df_to_csv(df: pd.DataFrame, csv_path: Path) -> None:
    """Saves dataframe to a csv file.

    Args:
        df (pd.DataFrame): Dataframe to save.
        csv_path (Path): Path to csv file.
    """
    df.to_csv(csv_path, index=False)
    if csv_path.is_file():
        print(f"Successfully saved to: {csv_path}")
        sys.exit(0)
    else:
        print(f"Failed to save to: {csv_path}!")
        sys.exit(1)
