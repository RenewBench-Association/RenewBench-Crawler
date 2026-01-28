# tests/config/test_loader.py
from pathlib import Path

import pytest

import rbc.config.loader as loader
from rbc.config.schema import SCHEMA_REGISTRY


@pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
def test_load_config(tmp_configs_dir: Path, source: str) -> None:
    """Happy path for "load_config" function.

    Check that "load_config" loads a YAML config for a source correctly.

    Args:
        tmp_configs_dir (Path): Path to the temporary config directory.
        source (str): Name of the data source (input to "load_config").
    """
    received_cfg_obj = loader.load_config(source=source, configs_dir=tmp_configs_dir)
    assert received_cfg_obj.source == source


@pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
def test_load_config_with_overrides(
    tmp_configs_dir: Path, source_configs: dict, source: str
) -> None:
    """Happy path for "load_config" function.

    Check that "load_config" loads a YAML config for a source correctly
    with overrides.

    Args:
        tmp_configs_dir (Path): Path to the temporary config directory.
        source_configs (dict): Dictionary of source configurations.
        source (str): Name of the data source (input to "load_config").
    """
    assert source in source_configs, f"Missing test cfg for source '{source}'"
    cfg_dict = source_configs[source]
    overrides = {
        k: ({sub_k: "override" for sub_k in v} if isinstance(v, dict) else "override")
        for k, v in cfg_dict.items()
    }

    received_cfg_obj = loader.load_config(
        source=source, configs_dir=tmp_configs_dir, overrides=overrides
    )
    received_cfg_dict = received_cfg_obj.model_dump(mode="json")

    for k, expected_v in overrides.items():
        if isinstance(expected_v, dict):
            for sub_k, sub_v in expected_v.items():
                assert received_cfg_dict[k][sub_k] == sub_v
        else:
            assert received_cfg_dict[k] == expected_v


def test_load_config_missing_file(tmp_configs_dir: Path) -> None:
    """Failure path for "load_config" function when YAML is missing.

    Args:
        tmp_configs_dir (Path): Path to the temporary config directory.
    """
    fake_cfg_path = Path(tmp_configs_dir, "fake.yaml")
    fake_cfg_path.unlink(missing_ok=True)

    with pytest.raises(ValueError, match="missing"):
        loader.load_config(source="fake", configs_dir=tmp_configs_dir)


def test_load_config_unknown_source(tmp_configs_dir: Path) -> None:
    """Failure path for "load_config" function when data source is not in registry.

    Args:
        tmp_configs_dir (Path): Path to the temporary config directory.
    """
    unknown_cfg_path = Path(tmp_configs_dir, "unknown.yaml")
    unknown_cfg_path.write_text("")

    with pytest.raises(ValueError, match="Unknown source"):
        loader.load_config(source="unknown", configs_dir=tmp_configs_dir)
