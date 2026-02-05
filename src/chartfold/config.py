"""Configuration management for chartfold.

Handles loading and generating TOML config files for personalized settings
like which lab tests get chart pages on the Hugo site.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from chartfold.db import ChartfoldDB

DEFAULT_CONFIG_PATH = "chartfold.toml"

# Default key tests when no config exists and no DB data to auto-generate from
FALLBACK_KEY_TESTS = [
    "CEA",
    "Hemoglobin",
    "Creatinine",
    "TSH",
    "WBC",
    "Platelets",
    "Glucose",
    "ALT",
    "AST",
]

DEFAULT_CONFIG_TEMPLATE = """\
# chartfold configuration
# Auto-generated from database contents. Edit freely.
#
# Each [[lab_tests]] entry defines one test to chart.
#   name  = Display name (chart title, URL slug)
#   match = Exact test names to match in the database (case-insensitive)

{lab_tests_stanzas}

[hugo]
# Number of recent lab results to show on the dashboard
dashboard_recent_labs = 10
"""


@dataclass
class LabTestConfig:
    """One chartable lab test with its matching rules."""

    name: str  # display name / chart title
    match: list[str] = field(default_factory=list)  # exact names to match (case-insensitive)


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load configuration from a TOML file.

    Returns a dict with at least:
    - lab_tests: list of LabTestConfig instances
    - hugo: dict with Hugo-specific settings

    Falls back to defaults if the config file doesn't exist.
    """
    path = Path(config_path)
    if not path.exists():
        print(
            f"Warning: Config file '{config_path}' not found, using defaults. "
            f"Run 'python -m chartfold init-config' to generate a personalized config.",
            file=sys.stderr,
        )
        return _default_config()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    config = _default_config()

    if "lab_tests" in raw:
        config["lab_tests"] = []
        for entry in raw["lab_tests"]:
            if "name" in entry and "match" in entry:
                config["lab_tests"].append(LabTestConfig(name=entry["name"], match=entry["match"]))
    elif "key_tests" in raw:
        # Legacy format: [key_tests] with tests = [...] and [key_tests.aliases]
        kt = raw["key_tests"]
        tests = kt.get("tests", [])
        aliases = kt.get("aliases", {})
        config["lab_tests"] = []
        for t in tests:
            match = [t]
            # Add aliases for this test from the config file
            if t in aliases:
                for alias in aliases[t]:
                    if alias not in match:
                        match.append(alias)
            # Also check KNOWN_ABBREVIATIONS
            if t in KNOWN_ABBREVIATIONS:
                for alias in KNOWN_ABBREVIATIONS[t]:
                    if alias not in match:
                        match.append(alias)
            config["lab_tests"].append(LabTestConfig(name=t, match=match))

    if "hugo" in raw:
        config["hugo"].update(raw["hugo"])

    return config


def get_lab_test_configs(config: dict) -> list[LabTestConfig]:
    """Return list of configured lab tests with match rules."""
    return config.get("lab_tests", [])


def _default_config() -> dict:
    """Return default configuration."""
    lab_tests = []
    for t in FALLBACK_KEY_TESTS:
        match = [t]
        if t in KNOWN_ABBREVIATIONS:
            for alias in KNOWN_ABBREVIATIONS[t]:
                if alias not in match:
                    match.append(alias)
        lab_tests.append(LabTestConfig(name=t, match=match))
    return {
        "lab_tests": lab_tests,
        "hugo": {
            "dashboard_recent_labs": 10,
        },
    }


# Well-known lab test abbreviation mappings for auto-detection.
# Used by generate_config() to detect cross-source name variants.
KNOWN_ABBREVIATIONS: dict[str, list[str]] = {
    # Tumor markers
    "CEA": ["Carcinoembryonic Antigen"],
    # CBC
    "Hgb": ["Hemoglobin", "HGB"],
    "WBC": ["White Blood Cell Count", "White Blood Cells"],
    "RBC": ["Red Blood Cell Count", "Red Blood Cells"],
    "PLT": ["Platelets", "Platelet Count"],
    "HCT": ["Hematocrit"],
    "MCV": ["Mean Corpuscular Volume"],
    "MCH": ["Mean Corpuscular Hemoglobin"],
    "MCHC": ["Mean Corpuscular Hemoglobin Concentration"],
    # Metabolic panel
    "BUN": ["Blood Urea Nitrogen"],
    "Glucose": ["Glucose Level", "Glucose, Serum"],
    "Creatinine": ["Serum Creatinine", "Creatinine, Serum"],
    "eGFR": ["Estimated Glomerular Filtration Rate", "Glomerular Filtration Rate"],
    "Potassium": ["K", "K+", "Potassium, Serum"],
    "Sodium": ["Na", "Na+", "Sodium, Serum"],
    "Calcium": ["Ca", "Calcium, Total", "Calcium, Serum"],
    "CO2": ["Bicarbonate", "Total CO2", "HCO3"],
    # Liver function
    "ALT": ["Alanine Aminotransferase", "SGPT"],
    "AST": ["Aspartate Aminotransferase", "SGOT"],
    "ALP": ["Alkaline Phosphatase", "Alk Phos"],
    "Albumin": ["Serum Albumin", "Albumin, Serum"],
    "Bilirubin": ["Total Bilirubin", "Bilirubin, Total"],
    # Thyroid
    "TSH": ["Thyroid Stimulating Hormone"],
    "Free T4": ["T4, Free", "FT4"],
    # Glycemic
    "HbA1c": ["Hemoglobin A1c", "Hemoglobin A1C", "Glycated Hemoglobin"],
    # Lipid panel
    "LDL": ["LDL Cholesterol", "LDL-C", "Low Density Lipoprotein"],
    "HDL": ["HDL Cholesterol", "HDL-C", "High Density Lipoprotein"],
    "Triglycerides": ["Triglyceride", "TG"],
    "Cholesterol": ["Total Cholesterol"],
    # Coagulation
    "PT": ["Prothrombin Time"],
    "INR": ["International Normalized Ratio"],
    "PTT": ["Partial Thromboplastin Time", "aPTT"],
}


def _group_test_names(db: ChartfoldDB, key_tests: list[str]) -> list[tuple[str, list[str]]]:
    """Group test names by identity, returning (canonical_name, all_match_names).

    Strategy:
    1. Group by valid LOINC code: if two sources have different test_name for the
       same LOINC, they're the same test.
    2. For tests without matching LOINC data, check KNOWN_ABBREVIATIONS against
       actual test names in the DB.

    Returns a list of (canonical_name, match_names) tuples — one per key test.
    Tests that exist under only one name get a single-element match list.
    """
    # Get all distinct test names in the DB (lowered for matching)
    all_tests = db.query("SELECT DISTINCT test_name FROM lab_results")
    db_test_names = {r["test_name"] for r in all_tests}
    db_names_lower = {n.lower(): n for n in db_test_names}

    # Build per-test match sets
    match_sets: dict[str, set[str]] = {kt: {kt} for kt in key_tests}

    # Strategy 1: LOINC-based grouping
    # Filter to real LOINC codes (NNNNN-N pattern) — internal codes like
    # IMO0002 get reused across unrelated tests and produce false aliases.
    loinc_groups = db.query(
        "SELECT test_loinc, GROUP_CONCAT(DISTINCT test_name) as names "
        "FROM lab_results "
        "WHERE test_loinc IS NOT NULL AND test_loinc != '' "
        "AND test_loinc GLOB '[0-9]*-[0-9]' "
        "GROUP BY test_loinc "
        "HAVING COUNT(DISTINCT test_name) > 1"
    )
    for group in loinc_groups:
        names = group["names"].split(",")
        for kt in key_tests:
            if kt in names:
                match_sets[kt].update(names)

    # Strategy 2: KNOWN_ABBREVIATIONS lookup
    for abbrev, known_aliases in KNOWN_ABBREVIATIONS.items():
        if abbrev in match_sets:
            for alias in known_aliases:
                if alias.lower() in db_names_lower:
                    match_sets[abbrev].add(db_names_lower[alias.lower()])
        for alias in known_aliases:
            if alias in match_sets and abbrev.lower() in db_names_lower:
                match_sets[alias].add(db_names_lower[abbrev.lower()])

    return [(kt, sorted(match_sets[kt])) for kt in key_tests]


def _format_lab_test_stanza(name: str, match: list[str]) -> str:
    """Format a single [[lab_tests]] TOML stanza."""
    match_str = ", ".join(f'"{m}"' for m in match)
    return f'[[lab_tests]]\nname = "{name}"\nmatch = [{match_str}]'


def generate_config(
    db: ChartfoldDB, config_path: str = DEFAULT_CONFIG_PATH, top_n: int = 25
) -> str:
    """Auto-generate a config file from the database contents.

    Picks the top N most frequent lab tests as key tests and auto-detects
    cross-source name variants, emitting one [[lab_tests]] stanza per test.

    Cross-source name variants (e.g. "BUN" and "Blood Urea Nitrogen") are
    merged before counting so they don't consume separate slots.  Clinically
    important tests from FALLBACK_KEY_TESTS are always included even if they
    fall outside the frequency top-N.

    Args:
        db: Database connection.
        config_path: Where to write the config file.
        top_n: How many top tests to include.

    Returns the path of the written config file.
    """
    from chartfold.analysis.lab_trends import get_available_tests

    available = get_available_tests(db)
    if available:
        # Build reverse alias map: name_lower -> canonical
        canonical_map: dict[str, str] = {}
        for abbrev, aliases in KNOWN_ABBREVIATIONS.items():
            canonical_map[abbrev.lower()] = abbrev
            for alias in aliases:
                canonical_map[alias.lower()] = abbrev

        # Merge counts under canonical names
        merged: dict[str, int] = {}
        for t in available:
            name = t["test_name"]
            canonical = canonical_map.get(name.lower(), name)
            merged[canonical] = merged.get(canonical, 0) + t["count"]

        # Pick top-N unique canonicals by merged count
        top = sorted(merged.items(), key=lambda x: -x[1])[:top_n]
        tests = [name for name, _ in top]

        # Ensure clinically important fallback tests are always included
        existing_lower = {t.lower() for t in tests}
        for ft in FALLBACK_KEY_TESTS:
            canonical = canonical_map.get(ft.lower(), ft)
            # Only include if not already present AND exists in DB
            if canonical.lower() not in existing_lower and canonical in merged:
                tests.append(canonical)
                existing_lower.add(canonical.lower())
    else:
        tests = list(FALLBACK_KEY_TESTS)

    # Group test names by identity
    groups = _group_test_names(db, tests)

    # Format as [[lab_tests]] stanzas
    stanzas = [_format_lab_test_stanza(name, match) for name, match in groups]
    lab_tests_stanzas = "\n\n".join(stanzas)

    content = DEFAULT_CONFIG_TEMPLATE.format(lab_tests_stanzas=lab_tests_stanzas)

    Path(config_path).write_text(content)
    return config_path
