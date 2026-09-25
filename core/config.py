"""Load/save named test configurations as YAML.

Configs are plain dicts (the same shape a TestType.default_config() returns),
so they round-trip cleanly and stay compatible with the original config.yaml
format. Named configs live in the app's `configs/` folder by default.
"""
import os

import yaml

from .paths import app_base, resource_base

# Writable configs the user saves/loads live next to the app; the shipped
# default configs may live in the (read-only) bundle in a packaged build.
CONFIG_DIR = os.path.join(app_base(), "configs")
_RESOURCE_CONFIG_DIR = os.path.join(resource_base(), "configs")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def save_config(config: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
    return path


def list_configs(config_dir: str = CONFIG_DIR) -> list:
    """Return (name, path) for every *.yaml in the configs folder."""
    if not os.path.isdir(config_dir):
        return []
    out = []
    for fn in sorted(os.listdir(config_dir)):
        if fn.lower().endswith((".yaml", ".yml")):
            out.append((os.path.splitext(fn)[0], os.path.join(config_dir, fn)))
    return out


def default_config_path(test_id: str) -> str:
    """Path to a test's default config: a user copy next to the app if present,
    otherwise the shipped default (which may be inside the bundle when frozen)."""
    user = os.path.join(CONFIG_DIR, f"default_{test_id}.yaml")
    if os.path.exists(user):
        return user
    return os.path.join(_RESOURCE_CONFIG_DIR, f"default_{test_id}.yaml")
