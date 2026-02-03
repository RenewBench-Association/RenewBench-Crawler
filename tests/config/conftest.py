# tests/conftest.py
from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def source_configs() -> dict:
    """Create a dictionary with example dict configs for all sources.

    Returns:
        dict: Dictionary of example source config dicts.
    """
    return {
        "entsoe": {
            "paths": {"dst_dir_raw": "/path/raw/entsoe"},
            "access": {"api_key": "token"},
        },
        "era5": {
            "paths": {"dst_dir_raw": "/path/raw/weather/era5"},
            "access": {
                "api_key": "token",
            },
        },
    }


@pytest.fixture()
def tmp_configs_dir(tmp_path: Path, source_configs: dict) -> Path:
    """Create a temporary configs/ folder with all source configs inside them.

    Args:
        tmp_path: Path to the temporary root folder.
        source_configs: Dictionary of exemplary source configs.

    Returns:
        Path: Path to the temporary config directory.
    """
    cfg_dir = Path(tmp_path, "configs")
    cfg_dir.mkdir()

    for source, cfg in source_configs.items():
        cfg_path = Path(cfg_dir, f"{source}.yaml")
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))

    return cfg_dir
