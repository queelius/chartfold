"""Configuration management for chartfold.

Handles loading and generating TOML config files for personalized settings
like which lab tests get chart pages on the Hugo site.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from chartfold.db import ChartfoldDB

DEFAULT_CONFIG_PATH = "chartfold.toml"

# Default key tests when no config exists and no DB data to auto-generate from
FALLBACK_KEY_TESTS = [
    "CEA", "Hemoglobin", "Creatinine", "TSH", "WBC", "Platelets",
    "Glucose", "ALT", "AST",
]

DEFAULT_CONFIG_TEMPLATE = """\
# chartfold configuration
# Edit this file to customize your chartfold experience.

[key_tests]
# Lab tests that get individual chart pages on the Hugo site
# and are prioritized in MCP queries.
# Auto-generated from your most frequent lab tests.
tests = {tests}

[hugo]
# Number of recent lab results to show on the dashboard
dashboard_recent_labs = 10
"""


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load configuration from a TOML file.

    Returns a dict with at least:
    - key_tests: list of test names to chart
    - hugo: dict with Hugo-specific settings

    Falls back to defaults if the config file doesn't exist.
    """
    path = Path(config_path)
    if not path.exists():
        return _default_config()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    config = _default_config()
    if "key_tests" in raw:
        kt = raw["key_tests"]
        if "tests" in kt and isinstance(kt["tests"], list):
            config["key_tests"] = kt["tests"]
    if "hugo" in raw:
        config["hugo"].update(raw["hugo"])

    return config


def _default_config() -> dict:
    """Return default configuration."""
    return {
        "key_tests": list(FALLBACK_KEY_TESTS),
        "hugo": {
            "dashboard_recent_labs": 10,
        },
    }


def generate_config(db: ChartfoldDB, config_path: str = DEFAULT_CONFIG_PATH,
                     top_n: int = 15) -> str:
    """Auto-generate a config file from the database contents.

    Picks the top N most frequent lab tests as key tests.

    Args:
        db: Database connection.
        config_path: Where to write the config file.
        top_n: How many top tests to include.

    Returns the path of the written config file.
    """
    from chartfold.analysis.lab_trends import get_available_tests

    available = get_available_tests(db)
    if available:
        tests = [t["test_name"] for t in available[:top_n]]
    else:
        tests = list(FALLBACK_KEY_TESTS)

    # Format as TOML list
    tests_str = "[\n" + "".join(f'    "{t}",\n' for t in tests) + "]"
    content = DEFAULT_CONFIG_TEMPLATE.format(tests=tests_str)

    Path(config_path).write_text(content)
    return config_path
