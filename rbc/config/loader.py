"""DATA SOURCE CONFIGURATION.

Loader for user-defined parameters (YAML config and CLI arguments)
"""

import argparse
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel

from rbc.config.schema import SCHEMA_REGISTRY

ROOT_DIR: Path = Path(__file__).resolve().parents[2]
CONFIGS_DIR: Path = Path(ROOT_DIR, "configs")


def load_config(
    source: str,
    configs_dir: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> BaseModel:
    """Load YAML config for a specific source.

    Args:
        source (str): Name of the data source, i.e. "entsoe".
        configs_dir (Path | None, optional): Path to the config directory.
            Defaults to rbc.config.loader.CONFIGS_DIR.
        overrides (dict | None, optional): Dict of overrides for config.

    Returns:
        BaseModel: Config data as a Pydantic object.

    Raises:
        ValueError: If no config YAML file exists for the given source.
    """
    configs_dir = configs_dir or CONFIGS_DIR
    try:
        cfg_path = next(Path(configs_dir).rglob(f"{source}.yaml"))
    except StopIteration:
        raise ValueError(f"Source '{source}' is missing a YAML config file!")

    logger.info(f"Loading '{source}' YAML config...")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg = {"source": source, **cfg}

    if overrides:
        logger.info(f"Overriding '{source}' YAML config values with:\n{overrides}")
        cfg = update_config(cfg, overrides)

    try:
        schema = SCHEMA_REGISTRY[source]
    except KeyError:
        raise ValueError(f"Unknown source: {source}")

    return schema.model_validate(cfg)


def update_config(base: dict, updates: dict) -> dict:
    """Update config dictionary with override values.

    Args:
        base (dict): Dict of YAML base config values
        updates (dict): Dict of override config values with which to update base

    Returns:
        dict: updated base dict
    """
    updated = base.copy()
    for k, v in updates.items():
        if isinstance(v, str) and v.lower() == "none":
            v = None
        if isinstance(v, dict) and isinstance(updated.get(k), dict):
            updated[k] = update_config(updated[k], v)
        else:
            updated[k] = v
    return updated


def parse_key_value_pairs(pairs: list[str]) -> dict[str, Any]:
    """Parse key-value pairs into nested dictionary.

    Args:
        pairs (list[str]): Key-value pairs, i.e. ['a.b=x', ...].

    Returns:
        dict[str, Any]: Nested dictionary of key-value pairs.

    Raises:
        ArgumentTypeError: If pairs are not provided in the correct format or if
        pairs were provided with keys that collide.
    """
    result: dict[str, Any] = {}
    if not pairs:
        return result

    for pair in pairs:
        if "=" not in pair:
            raise argparse.ArgumentTypeError(
                f"Invalid format '{pair}', expected key=value"
            )

        key_path, value = pair.split("=", 1)
        keys = key_path.split(".")
        current = result

        for i, k in enumerate(keys[:-1]):
            # Check for collisions: is the key already a non-dict value?
            if k in current and not isinstance(current[k], dict):
                raise argparse.ArgumentTypeError(
                    f"Conflict at '{'.'.join(keys[: i + 1])}': cannot overwrite key "
                    f"that is already a scalar with a dict."
                )

            current = current.setdefault(k, {})

        last_key = keys[-1]
        # Check for collisions: is the final key already a dictionary?
        if last_key in current and isinstance(current[last_key], dict):
            raise argparse.ArgumentTypeError(
                f"Conflict at '{key_path}': cannot overwrite a sub-dict with a scalar."
            )

        current[last_key] = value

    return result
