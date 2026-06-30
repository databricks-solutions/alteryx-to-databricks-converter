"""Smoke test infrastructure — auto-discovers YAML test configs and runs them as parametrized tests."""

from __future__ import annotations

from pathlib import Path

import yaml

SMOKE_DIR = Path(__file__).parent


def _discover_smoke_configs() -> list[dict]:
    """Discover all .yml/.yaml smoke test config files."""
    configs = []
    for path in sorted(SMOKE_DIR.glob("*.yml")) + sorted(SMOKE_DIR.glob("*.yaml")):
        if path.name.startswith("_") or path.name == "conftest.py":
            continue
        with open(path) as f:
            data = yaml.safe_load(f)
        if data:
            data["_config_file"] = str(path.name)
            configs.append(data)
    return configs


SMOKE_CONFIGS = _discover_smoke_configs()


def pytest_generate_tests(metafunc):
    """Parametrize tests that request the `smoke_config` fixture."""
    if "smoke_config" in metafunc.fixturenames:
        ids = [c.get("name", c["_config_file"]) for c in SMOKE_CONFIGS]
        metafunc.parametrize("smoke_config", SMOKE_CONFIGS, ids=ids)
