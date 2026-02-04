"""ENTSOE-E DATA DOWNLOADER.

Remote API access of ENTSO-E Platform using the entsoe-apy package.
"""

import pickle
from pathlib import Path

import pandas as pd
from entsoe.config import get_config, set_config
from entsoe.Generation import ActualGenerationPerGenerationUnit
from entsoe.query.decorators import ServiceUnavailableError
from entsoe.utils import add_timestamps, extract_records, mappings
from loguru import logger

from rbc.energy.utils import write_df_to_csv

PSRTYPE_MAPPINGS = {
    # 'A03': 'Mixed',
    # 'A04': 'Generation',
    # 'A05': 'Load',
    "B01": "Biomass",
    "B02": "Fossil Brown coal/Lignite",
    "B03": "Fossil Coal-derived gas",
    "B04": "Fossil Gas",
    "B05": "Fossil Hard coal",
    "B06": "Fossil Oil",
    "B07": "Fossil Oil shale",
    "B08": "Fossil Peat",
    "B09": "Geothermal",
    "B10": "Hydro Pumped Storage",
    "B11": "Hydro Run-of-river and poundage",
    "B12": "Hydro Water Reservoir",
    "B13": "Marine",
    "B14": "Nuclear",
    "B15": "Other renewable",
    "B16": "Solar",
    "B17": "Waste",
    "B18": "Wind Offshore",
    "B19": "Wind Onshore",
    "B20": "Other",
    "B21": "AC Link",
    "B22": "DC Link",
    "B23": "Substation",
    "B24": "Transformer",
    "B25": "Energy storage",
}

RELEVANT_RECORD_KEYS = {
    "time_series.mkt_psrtype.psr_type": "production_type",
    "time_series.mkt_psrtype.power_system_resources.name": "plant_name",
    "time_series.period.point.quantity": "quantity",
    "time_series.quantity_measure_unit_name": "unit",
    "timestamp": "timestamp",
}


class EntsoeDownloader:
    """Entsoe-E data downloader.

    Attributes:
        years (list[str]): List of years to get data for.
        bidding_zones (list[str]): List of bidding zones to get data for.
        output_path (Path): Path to the output directory.
        checkpoint_path (Path): Path to the checkpoint file for resuming.
        checkpoint (np.array): Array of 0 and 1 values for resuming.
    """

    def __init__(
        self,
        token: str,
        output_path: Path,
        years: list[int],
        bidding_zones: list[str] = mappings.keys(),
        resume: bool = True,
    ) -> None:
        """Initializes the instance.

        Attributes:
            token (str): The personal ENTSO-E RESTful API token.
            output_path (Path): Path to the output directory.
            years (list[int]): List of years to get data for.
            bidding_zones (list[str]): List of bidding zones to get data for.
            resume (bool, optional): Whether to resume from a previous
             download (True) or start from scratch (False). Defaults to True.

        Raises:
            ValueError: If bidding zone is unsupported or token is invalid.
        """
        self.years = years
        self.bidding_zones = list(bidding_zones)
        self.output_path = output_path
        self.checkpoint_path = Path(self.output_path, "status.pickle")

        for bz in self.bidding_zones:
            if bz not in list(mappings.keys()):
                raise ValueError(f"Bidding zone '{bz}' is not supported.")

        logger.info(
            f"Entsoe-E Downloader initialised for:"
            f"\n- years:\t\t{years}"
            f"\n- bidding zones:\t{bidding_zones}"
        )

        set_config(security_token=token)
        if get_config().security_token is None:
            raise ValueError(
                f"Entsoe-apy failed to successfully configure token '{token}'!"
            )

        if resume and self.checkpoint_path.is_file():
            with open(self.checkpoint_path, "rb") as f:
                self.checkpoint = pickle.load(f)
        else:
            self.checkpoint = {}

    def download_data(self) -> None:
        """Parse data for all given years and zones from ENTSO-E Platform and save to CSV."""
        for year in self.years:
            for zone in self.bidding_zones:
                task = (year, zone)

                # check if task was previously run and was unsuccessful before (= 0)
                if self.checkpoint.get(task) == 0:
                    success_code = self._download_year_zone_data(zone=zone, year=year)

                    self.checkpoint[task] = success_code
                    with open(self.checkpoint_path, "wb") as f:
                        pickle.dump(self.checkpoint, f)
                else:
                    logger.info(f"{zone} in {year}: Data previously downloaded.")

    def _download_year_zone_data(self, zone: str, year: int) -> int:
        """Parse data for specific zone and year from ENTSO-E and dump to CSV.

        Args:
            zone (str): Zone to download data for.
            year (int): Year to download data for.

        Returns:
            int: Status of the download (1 if successful, 0 if unsuccessful).

        Raises:
            ValueError: If Entso-E Transparency Platform is unavailable.
        """
        try:
            result = ActualGenerationPerGenerationUnit(
                period_start=int(f"{year}01010000"),  # start of Jan 1st
                period_end=int(f"{year}12312359"),  # end of Dec 31st
                in_domain=zone,
                psr_type=None,
                registered_resource=None,
            ).query_api()

        except ServiceUnavailableError:
            raise ValueError("Entso-E Transparency Platform is currently unavailable!")

        if type(result) is ActualGenerationPerGenerationUnit:
            logger.warning(f"{zone} in {year}: API call did not return requested data!")
            return 0

        if not result:
            logger.warning(
                f"{zone} in {year}: No data available!Setting download status to 1."
            )
            return 1

        records = extract_records(result)  # turns into list of dicts
        records = add_timestamps(records)  # adds key 'timestamp' to each dict
        df = pd.DataFrame(records)

        try:
            df = df.loc[:, list(RELEVANT_RECORD_KEYS.keys())].rename(
                columns=RELEVANT_RECORD_KEYS
            )

        except KeyError:
            logger.warning(f"{zone} in {year}: Relevant data missing!")
            return 0

        df["production_type"] = df["production_type"].map(PSRTYPE_MAPPINGS)
        df = df.dropna(subset=["production_type"])  # remove NaN rows

        write_df_to_csv(
            df=df, file_path=Path(self.output_path, zone, f"{year}.csv"), index=True
        )
        logger.info(f"{zone} in {year}: Data downloaded and saved.")
        return 1
