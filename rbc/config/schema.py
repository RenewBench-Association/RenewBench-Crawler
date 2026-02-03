"""DATA SOURCE CONFIGURATION.

Schema definitions for different data sources.
"""

from pathlib import Path
from typing import Literal, Type

from pydantic import BaseModel, field_validator


# ----------------------------------
# General schemas
# ----------------------------------
class Paths(BaseModel):
    """Filesystem paths used by a data source.

    Attributes:
        dst_dir_raw (Path): Destination directory for raw data output.
    """

    dst_dir_raw: Path


class AccessAPI(BaseModel):
    """Access settings for a data source requiring API key / security token.

    Attributes:
        api_key (str): API key.
    """

    api_key: str


class AccessValidation:
    """Validator for "access" fields to ensure strings contain non-placeholder content."""

    @field_validator("access", mode="after")
    @classmethod
    def check_access_values(cls, access: BaseModel) -> BaseModel | None:
        """Validate that access credentials contain real values.

        Args:
            access (BaseModel): Parsed access configuration.

        Returns:
            BaseModel | None: The validated access object.

        Raises:
            ValueError: If an access field is empty or contains a placeholder.
        """
        if access is None:
            return access

        for field, value in access.model_dump().items():
            if not isinstance(value, str):
                continue
            if not value.strip():
                raise ValueError(f"Access field '{field}' is empty")
            if any(marker in value for marker in ("YOUR-SECRET", "COMMIT")):
                raise ValueError(
                    f"Access field '{field}' still contains the placeholder '{value}'!"
                )
        return access


# ----------------------------------
# Per-source schemas
# ----------------------------------
class EntsoeConfig(AccessValidation, BaseModel):
    """Configuration schema for the ENTSO-E data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["entsoe"] = "entsoe"
    paths: Paths
    access: AccessAPI


class Era5Config(AccessValidation, BaseModel):
    """Configuration schema for the ERA5 reanalysis data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["era5"] = "era5"
    paths: Paths
    access: AccessAPI


# ----------------------------------
# Schema registry
# ----------------------------------
SCHEMA_REGISTRY: dict[str, Type[BaseModel]] = {
    "entsoe": EntsoeConfig,
    "era5": Era5Config,
}
