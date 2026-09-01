# tests/config/conftest.py
from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def source_configs(tmp_path: Path) -> dict:
    """Create a dictionary with example dict configs for all sources.

    Args:
        tmp_path (Path): Path to the temporary directory.

    Returns:
        dict: Dictionary of example source config dicts.
    """
    return {
        "adme": {"paths": {"dst_dir_raw": str(Path(tmp_path, "adme"))}},
        "aemo": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "aemo"))},
            "access": {"api_key": "token"},
        },
        "aeso": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "aeso"))},
            "access": {"api_key": "token"},
        },
        "cen": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "cen"))},
            "access": {"api_key": "token"},
        },
        "eat": {"paths": {"dst_dir_raw": str(Path(tmp_path, "eat"))}},
        "eia": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "eia"))},
            "access": {"api_key": "token"},
        },
        "entsoe": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "entsoe"))},
            "access": {"api_key": "token"},
        },
        "epias": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "epias"))},
            "access": {"username": "name", "password": "pw"},
        },
        "ieso": {"paths": {"dst_dir_raw": str(Path(tmp_path, "ieso"))}},
        "ons": {"paths": {"dst_dir_raw": str(Path(tmp_path, "ons"))}},
        "rei": {"paths": {"dst_dir_raw": str(Path(tmp_path, "rei"))}},
        "barra2": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "barra2"))},
        },
        "era5": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "era5"))},
            "access": {"api_key": "token"},
        },
        "icon_dream_eu": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "icon_dream_eu"))},
        },
        "icon_dream_global": {
            "paths": {"dst_dir_raw": str(Path(tmp_path, "icon_dream_global"))},
        },
        "regrid_healpix": {
            "paths": {
                "raw_data_base_dir": str(Path(tmp_path, "raw_weather")),
                "weights_cache_dir": str(Path(tmp_path, "weights_cache")),
                "dst_data_base_dir": str(Path(tmp_path, "processed_weather")),
            },
            "healpix_min_level": 4,
            "healpix_max_level": {
                "era5": 7,
                "barra2_r2": 8,
                "barra2_c2": 10,
                "barra2_c2_20min": 10,
                "icon_dream_global": 9,
                "icon_dream_eu": 10,
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
