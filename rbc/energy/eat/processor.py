import requests
from bs4 import BeautifulSoup
from loguru import logger

from rbc.energy.utils import load_df_from_file

URL_GEN = "https://www.ea.govt.nz/data-and-insights/datasets/wholesale/generation/generation-fleet/existing/"


class EatProcessor:
    """EAT raw data processor."""

    def __init__(self):
        """EAT processor init (empty for now)."""
        pass

    def get_generator_df(self):
        """Get dataframe of EAT generator information."""
        file_url = self.get_latest_generators_url()
        if file_url is not None:
            gen_df = load_df_from_file(file_url)  # info on decommissioning state
            print(gen_df)

    @staticmethod
    def get_latest_generators_url() -> str | None:
        """Get the latest URL for the CSV file containing EAT generator information.

        Returns:
            str | None: The latest URL for the EAT generators CSV, if it was found.
        """
        try:
            response = requests.get(URL_GEN)
            response.raise_for_status()
        except Exception as e:
            logger.error("Connectivity check to EAT's generators site failed!")
            raise ConnectionError(f"EAT generators endpoint is unreachable: {e}")

        soup = BeautifulSoup(response.text, "html.parser")

        for link in soup.find_all("a", href=True):  # find 'a' (anchor) tags
            href = link["href"]

            # find the target filename pattern
            if "DispatchedGenerationPlant.csv" in href:
                return href

        return None
