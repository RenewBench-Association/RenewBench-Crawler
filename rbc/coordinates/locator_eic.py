"""EIC code-based coordinate and name locators.

Two strategies for enriching poorly-named ENTSO-E generation units:

1. EICDirectoryLocator
   Downloads ENTSO-E's public EIC code registry (no API key required) and provides
   official display-name lookup by EIC code.  The result is used to replace generic
   unit names such as "Unit 10" with their official plant name before downstream
   fuzzy matching against OSM/OpenInfra.

2. lookup_eic_in_wikidata
   Queries the WikiData SPARQL endpoint using property P3179 (EIC code) and P625
   (coordinate location).  When coordinates are found they are returned directly,
   bypassing name matching entirely.  When only a label is found it is used as an
   enriched name for downstream matching.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

EIC_DIRECTORY_URL = (
    "https://eepublicdownloads.blob.core.windows.net/cio-lio/csv/W_eicCodes.csv"
)
# Column names in the W-type EIC CSV (semicolon-delimited, stable as of 2026)
_EIC_COL = "EicCode"
_DISPLAY_NAME_COL = "EicDisplayName"
_LONG_NAME_COL = "EicLongName"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
_HEADER = {
    "User-Agent": (
        "RenewBench Association "
        "(+https://github.com/RenewBench-Association/RenewBench-Crawler)"
    )
}


class EICDirectoryLocator:
    """Name-enrichment locator backed by ENTSO-E's public EIC code registry.

    Downloads the official EIC code publication on first use and optionally caches
    it locally.  Provides EIC code → official display name lookups so that generic
    ENTSO-E unit names (e.g. "Unit 10") can be replaced with their registered plant
    name before fuzzy-matching against OSM.

    Attributes:
        cache_dir (Path | None): Directory used for caching the downloaded registry.
        df_eic (pd.DataFrame): Parsed EIC code registry.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize EICDirectoryLocator.

        Args:
            cache_dir (Path, optional): Directory for caching the downloaded registry.
                Defaults to None (no caching).
        """
        self.cache_dir = cache_dir
        self.df_eic: pd.DataFrame = pd.DataFrame()
        self._eic_col: str | None = None
        self._display_name_col: str | None = None
        self._long_name_col: str | None = None
        self._load()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Download and parse the ENTSO-E W-type EIC code CSV."""
        cache_path = (
            Path(self.cache_dir, "eic_directory.csv") if self.cache_dir else None
        )

        if cache_path and cache_path.exists():
            logger.info(f"EICDirectoryLocator: loading from cache '{cache_path}'")
            self.df_eic = pd.read_csv(cache_path, sep=";", dtype=str)
            self._detect_columns()
            return

        try:
            logger.info("EICDirectoryLocator: downloading ENTSO-E W-type EIC codes...")
            resp = requests.get(EIC_DIRECTORY_URL, timeout=60, headers=_HEADER)
            resp.raise_for_status()

            self.df_eic = pd.read_csv(io.StringIO(resp.text), sep=";", dtype=str)
            self._detect_columns()

            if cache_path and not self.df_eic.empty:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.df_eic.to_csv(cache_path, sep=";", index=False)
                logger.info(f"EICDirectoryLocator: cached to '{cache_path}'")

        except requests.RequestException as e:
            logger.warning(
                f"EICDirectoryLocator: download failed ({e}). "
                "Name enrichment via EIC directory will be unavailable."
            )

    def _detect_columns(self) -> None:
        """Detect which columns hold EIC codes and display/long names."""
        # Prefer known stable column names from the W-type CSV format.
        if _EIC_COL in self.df_eic.columns:
            self._eic_col = _EIC_COL
            if _DISPLAY_NAME_COL in self.df_eic.columns:
                self._display_name_col = _DISPLAY_NAME_COL
            if _LONG_NAME_COL in self.df_eic.columns:
                self._long_name_col = _LONG_NAME_COL
            logger.info(f"EICDirectoryLocator initialized: {len(self.df_eic)} entries")
            return

        # Fallback: case-insensitive detection for cached files with different format.
        cols_lower = {c.strip().lower(): c for c in self.df_eic.columns}
        for candidate in ("eiccode", "eic_code", "eic code", "eic", "code"):
            if candidate in cols_lower:
                self._eic_col = cols_lower[candidate]
                break
        for candidate in ("eicdisplayname", "display_name", "displayname", "name"):
            if candidate in cols_lower:
                self._display_name_col = cols_lower[candidate]
                break

        for candidate in ("eiclongname", "long_name", "longname"):
            if candidate in cols_lower:
                self._long_name_col = cols_lower[candidate]
                break

        if self._eic_col and (self._display_name_col or self._long_name_col):
            logger.info(
                f"EICDirectoryLocator initialized: {len(self.df_eic)} entries | "
                f"EIC col='{self._eic_col}' | "
                f"long='{self._long_name_col}' | display='{self._display_name_col}'"
            )
        else:
            logger.warning(
                "EICDirectoryLocator: could not identify required columns. "
                f"Available: {list(self.df_eic.columns)}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup_names(self, eic_code: str) -> list[str]:
        """Return ordered official names for an EIC code.

        The order is chosen for downstream matching quality:
        1. EicLongName
        2. EicDisplayName

        Args:
            eic_code (str): ENTSO-E EIC code to look up.

        Returns:
            list[str]: Ordered unique non-empty name candidates.
        """
        if self.df_eic.empty or not self._eic_col or not eic_code:
            return []

        mask = self.df_eic[self._eic_col].str.strip() == str(eic_code).strip()
        hits = self.df_eic[mask]
        if hits.empty:
            return []

        row = hits.iloc[0]
        names: list[str] = []
        for col in (self._long_name_col, self._display_name_col):
            if col and col in row.index:
                val = row[col]
                if pd.notna(val):
                    name = str(val).strip()
                    if name and name not in names:
                        names.append(name)
        return names

    def lookup_name(self, eic_code: str) -> str | None:
        """Return the best official name for an EIC code, or None if not found.

        Args:
            eic_code (str): ENTSO-E EIC code to look up.

        Returns:
            str | None: Best official name (LongName preferred), or None if not found.
        """
        names = self.lookup_names(eic_code)
        return names[0] if names else None


def lookup_eic_in_wikidata(
    eic_code: str,
    delay_s: float = 0.5,
) -> dict[str, str | float | None] | None:
    """Query WikiData SPARQL for a power plant identified by EIC code (P3179).

    Tries to retrieve:
    - Coordinates directly via property P625 (best case: no further matching needed).
    - English label as fallback for downstream name-based matching.

    Args:
        eic_code (str): The EIC code to look up (e.g. "49W0000000000415").
        delay_s (float): Courtesy pause before the HTTP request to avoid WikiData
            rate limits.  Defaults to 0.5 s.

    Returns:
        dict with keys 'name', 'lat', 'lon', 'wikidata_url', or None if not found.
    """
    if not eic_code or pd.isna(eic_code):
        return None

    time.sleep(delay_s)

    query = f"""
    SELECT ?item ?name ?lat ?lon WHERE {{
      ?item wdt:P3179 "{str(eic_code).strip()}" .
      OPTIONAL {{ ?item rdfs:label ?name . FILTER(LANG(?name) = "en") }}
      OPTIONAL {{
        ?item wdt:P625 ?coord .
        BIND(geof:latitude(?coord)  AS ?lat)
        BIND(geof:longitude(?coord) AS ?lon)
      }}
    }} LIMIT 1
    """

    try:
        resp = requests.get(
            WIKIDATA_SPARQL_URL,
            params={"query": query, "format": "json"},
            headers=_HEADER,
            timeout=30,
        )
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])

        if not bindings:
            return None

        r = bindings[0]
        return {
            "name": r.get("name", {}).get("value"),
            "lat": float(r["lat"]["value"]) if "lat" in r else None,
            "lon": float(r["lon"]["value"]) if "lon" in r else None,
            "wikidata_url": r.get("item", {}).get("value"),
        }

    except Exception as e:
        logger.debug(f"WikiData lookup failed for EIC '{eic_code}': {e}")
        return None
