"""Generate Hugo static site content from the chartfold SQLite database.

Writes markdown + JSON data files into the Hugo content/ and data/ directories.
Run Hugo after generation to build the static site.

Usage:
    python -m chartfold.hugo.generate --db chartfold.db --hugo-dir ./site
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from chartfold.analysis.lab_trends import (
    get_abnormal_labs,
    get_lab_series,
    get_lab_trend,
    get_latest_labs,
)
from chartfold.analysis.medications import get_active_medications
from chartfold.analysis.surgical_timeline import build_surgical_timeline
from chartfold.config import load_config
from chartfold.db import ChartfoldDB

# Colors for different sources in charts
SOURCE_COLORS = [
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#10b981",  # green
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
]

HUGO_TEMPLATE_DIR = Path(__file__).parent


def generate_site(db_path: str, hugo_dir: str, config_path: str = "") -> None:
    """Generate the full Hugo site from a chartfold database.

    Args:
        db_path: Path to the chartfold SQLite database.
        hugo_dir: Output directory for the Hugo site.
        config_path: Path to chartfold.toml config file. Empty uses default.
    """
    out = Path(hugo_dir)
    content = out / "content"
    data = out / "data"

    # Load configuration
    config = load_config(config_path) if config_path else load_config()

    # Copy scaffolding
    _copy_scaffolding(out)

    # Ensure directories
    content.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    db = ChartfoldDB(db_path)
    db.init_schema()

    try:
        summary = db.summary()
        sources = db.sources()

        # Dashboard (index page)
        _generate_dashboard(content, data, db, summary, sources, config)

        # Timeline
        _generate_timeline(content, data, db)

        # Labs
        _generate_labs(content, data, db, config)

        # Encounters
        _generate_encounters(content, data, db)

        # Medications
        _generate_medications(content, data, db)

        # Conditions
        _generate_conditions(content, data, db)

        # Pathology
        _generate_pathology(content, data, db)

        # Surgical Timeline
        _generate_surgical(content, data, db)

        # Imaging
        _generate_imaging(content, data, db)

        print(f"\nHugo site generated at {hugo_dir}")
        print(f"Run: cd {hugo_dir} && hugo serve")

    finally:
        db.close()


def _copy_scaffolding(out: Path) -> None:
    """Copy Hugo config, layouts, and static files."""
    for subdir in ("layouts", "static"):
        src = HUGO_TEMPLATE_DIR / subdir
        dst = out / subdir
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    # Copy hugo.toml
    config_src = HUGO_TEMPLATE_DIR / "hugo.toml"
    if config_src.exists():
        shutil.copy2(config_src, out / "hugo.toml")


def _write_page(filepath: Path, title: str, content: str, extra_frontmatter: str = "") -> None:
    """Write a Hugo content page."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\ntitle: \"{title}\"\n{extra_frontmatter}---\n\n"
    filepath.write_text(fm + content)


def _write_json(filepath: Path, data) -> None:
    """Write a JSON data file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(data, indent=2, default=str))


def _generate_dashboard(content: Path, data: Path, db: ChartfoldDB,
                         summary: dict, sources: list, config: dict | None = None) -> None:
    """Generate the dashboard/index page."""
    hugo_config = (config or {}).get("hugo", {})
    recent_labs_count = hugo_config.get("dashboard_recent_labs", 10)

    cards = []
    for table, count in summary.items():
        if count > 0:
            cards.append(f'<div class="card"><h3>{table.replace("_", " ").title()}</h3>'
                         f'<div class="value">{count}</div></div>')

    source_list = ""
    for s in sources:
        source_list += f"- **{s['source']}** — loaded {s['loaded_at'][:19]}\n"

    # Recent abnormal labs
    abnormal = get_abnormal_labs(db)[:recent_labs_count]
    abnormal_table = _make_table(
        ["Test", "Value", "Unit", "Flag", "Date", "Source"],
        [[r["test_name"], r["value"], r["unit"], r["interpretation"],
          r["result_date"], r["source"]] for r in abnormal],
    )

    # Active medications
    active_meds = get_active_medications(db)
    meds_table = _make_table(
        ["Medication", "Sig", "Source"],
        [[m["name"], m.get("sig", ""), m["source"]] for m in active_meds],
    )

    # Recent encounters (last 5)
    recent_enc = db.query(
        "SELECT encounter_date, encounter_type, facility, provider, source "
        "FROM encounters ORDER BY encounter_date DESC LIMIT 5"
    )
    enc_table = _make_table(
        ["Date", "Type", "Facility", "Provider", "Source"],
        [[e["encounter_date"], e.get("encounter_type", ""), e.get("facility", ""),
          e.get("provider", ""), e["source"]] for e in recent_enc],
    )

    # Active conditions
    active_cond = db.query(
        "SELECT condition_name, icd10_code, onset_date, source "
        "FROM conditions WHERE LOWER(clinical_status) = 'active' "
        "ORDER BY condition_name"
    )
    cond_table = _make_table(
        ["Condition", "ICD-10", "Onset", "Source"],
        [[c["condition_name"], c.get("icd10_code", ""), c.get("onset_date", ""),
          c["source"]] for c in active_cond],
    )

    md = f"""
<div class="cards">
{"".join(cards)}
</div>

## Data Sources

{source_list}

## Active Medications

{meds_table}

## Active Conditions

{cond_table}

## Recent Encounters

{enc_table}

## Recent Abnormal Labs

{abnormal_table}
"""
    _write_page(content / "_index.md", "Dashboard", md)


def _generate_timeline(content: Path, data: Path, db: ChartfoldDB) -> None:
    """Generate the unified timeline page with all event types."""
    events = []

    for enc in db.query("SELECT encounter_date, encounter_type, facility, provider, source FROM encounters ORDER BY encounter_date DESC"):
        events.append({"date": enc["encounter_date"], "type": "Encounter",
                        "detail": f"{enc.get('encounter_type', '')} at {enc.get('facility', '')}",
                        "source": enc["source"]})

    for proc in db.query("SELECT procedure_date, name, facility, source FROM procedures ORDER BY procedure_date DESC"):
        events.append({"date": proc["procedure_date"], "type": "Procedure",
                        "detail": proc["name"], "source": proc["source"]})

    for img in db.query("SELECT study_date, study_name, modality, source FROM imaging_reports ORDER BY study_date DESC"):
        events.append({"date": img["study_date"], "type": "Imaging",
                        "detail": f"{img.get('modality', '')} — {img['study_name']}",
                        "source": img["source"]})

    # Add lab collection dates (grouped by date to avoid overwhelming the timeline)
    lab_dates = db.query(
        "SELECT result_date, COUNT(*) as count, GROUP_CONCAT(DISTINCT source) as sources "
        "FROM lab_results GROUP BY result_date ORDER BY result_date DESC"
    )
    for ld in lab_dates:
        events.append({"date": ld["result_date"], "type": "Labs",
                        "detail": f"{ld['count']} lab results",
                        "source": ld["sources"]})

    # Add pathology reports
    for path in db.query("SELECT report_date, specimen, diagnosis, source FROM pathology_reports ORDER BY report_date DESC"):
        events.append({"date": path["report_date"], "type": "Pathology",
                        "detail": (path.get("diagnosis", "") or "")[:60],
                        "source": path["source"]})

    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    _write_json(data / "timeline.json", events)

    table = _make_table(
        ["Date", "Type", "Detail", "Source"],
        [[e["date"], e["type"], e["detail"][:80], e["source"]] for e in events],
    )
    _write_page(content / "timeline.md", "Timeline", table)


def _generate_labs(content: Path, data: Path, db: ChartfoldDB,
                    config: dict | None = None) -> None:
    """Generate lab pages with trend charts."""
    labs_dir = content / "labs"
    labs_dir.mkdir(parents=True, exist_ok=True)

    latest = get_latest_labs(db)
    table = _make_table(
        ["Test", "Value", "Unit", "Range", "Flag", "Date", "Source"],
        [[r["test_name"], r["value"], r["unit"], r["ref_range"],
          r["interpretation"] or "", r["result_date"], r["source"]]
         for r in latest],
    )
    _write_page(labs_dir / "_index.md", "Lab Results", f"## Latest Results\n\n{table}")

    # Individual trend pages for key tests (from config or defaults)
    key_tests = (config or {}).get("key_tests", [
        "CEA", "Hemoglobin", "Creatinine", "TSH", "WBC", "Platelets",
    ])
    for test_name in key_tests:
        series = get_lab_series(db, test_name=test_name)
        if not series["results"]:
            continue

        trend = series["results"]

        # Build per-source datasets for Chart.js
        sources = series["sources"]
        datasets = []
        for i, src in enumerate(sources):
            src_results = [r for r in trend if r["source"] == src]
            color = SOURCE_COLORS[i % len(SOURCE_COLORS)]
            datasets.append({
                "source": src,
                "labels": [r["result_date"] for r in src_results],
                "values": [r["value_numeric"] for r in src_results
                           if r["value_numeric"] is not None],
                "color": color,
            })

        chart_data = {
            "test_name": series["test_name"],
            "unit": trend[0]["unit"] if trend else "",
            "datasets": datasets,
            "ref_ranges": series["ref_ranges"],
            "ref_range_discrepancy": series["ref_range_discrepancy"],
        }
        slug_base = test_name.lower().replace(" ", "_")
        _write_json(data / f"lab_{slug_base}.json", chart_data)

        # Ref range note
        ref_note = ""
        if series["ref_range_discrepancy"]:
            ranges_str = ", ".join(f"**{src}**: {rr}" for src, rr in series["ref_ranges"].items())
            ref_note = (f"\n> **Note:** Reference ranges differ across sources: "
                        f"{ranges_str}\n")

        table = _make_table(
            ["Date", "Value", "Unit", "Range", "Flag", "Source"],
            [[r["result_date"], r["value"], r["unit"], r["ref_range"],
              r["interpretation"] or "", r["source"]] for r in trend],
        )

        # Build Chart.js with per-source datasets
        datasets_js = []
        for ds in datasets:
            src_label = ds["source"]
            datasets_js.append(
                f"{{ label: '{src_label}', "
                f"data: {json.dumps(list(zip(ds['labels'], ds['values'])))}.map(p => ({{x: p[0], y: p[1]}})), "
                f"borderColor: '{ds['color']}', backgroundColor: '{ds['color']}', "
                f"tension: 0.1, fill: false, pointRadius: 4 }}"
            )
        datasets_str = ",\n          ".join(datasets_js)

        chart_id = test_name.lower().replace(" ", "-")
        chart_html = f"""
<div class="chart-container">
<canvas id="{chart_id}-chart"></canvas>
</div>
<script>
new Chart(document.getElementById('{chart_id}-chart'), {{
  type: 'line',
  data: {{
    datasets: [
      {datasets_str}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ type: 'time', time: {{ unit: 'month' }}, title: {{ display: true, text: 'Date' }} }},
      y: {{ beginAtZero: false, title: {{ display: true, text: '{chart_data["unit"]}' }} }}
    }},
    plugins: {{ title: {{ display: true, text: '{series["test_name"]} ({chart_data["unit"]})' }} }}
  }}
}});
</script>
"""
        slug = test_name.lower().replace(" ", "-")
        _write_page(
            labs_dir / f"{slug}.md",
            f"{test_name} Trend",
            f"{chart_html}\n{ref_note}\n## Values\n\n{table}",
        )


def _generate_encounters(content: Path, data: Path, db: ChartfoldDB) -> None:
    encounters = db.query(
        "SELECT encounter_date, encounter_type, facility, provider, reason, source "
        "FROM encounters ORDER BY encounter_date DESC"
    )
    table = _make_table(
        ["Date", "Type", "Facility", "Provider", "Reason", "Source"],
        [[e["encounter_date"], e.get("encounter_type", ""), e.get("facility", ""),
          e.get("provider", ""), (e.get("reason", "") or "")[:60], e["source"]]
         for e in encounters],
    )
    _write_page(content / "encounters.md", "Encounters", table)


def _generate_medications(content: Path, data: Path, db: ChartfoldDB) -> None:
    active = get_active_medications(db)
    all_meds = db.query("SELECT name, status, sig, start_date, stop_date, source FROM medications ORDER BY status, name")

    active_table = _make_table(
        ["Name", "Sig", "Route", "Start Date", "Source"],
        [[m["name"], m.get("sig", ""), m.get("route", ""), m.get("start_date", ""), m["source"]]
         for m in active],
    )
    all_table = _make_table(
        ["Name", "Status", "Sig", "Start", "Stop", "Source"],
        [[m["name"], m["status"], m.get("sig", "")[:40], m.get("start_date", ""),
          m.get("stop_date", ""), m["source"]] for m in all_meds],
    )
    _write_page(content / "medications.md", "Medications",
                 f"## Active Medications\n\n{active_table}\n\n## All Medications\n\n{all_table}")


def _generate_conditions(content: Path, data: Path, db: ChartfoldDB) -> None:
    conditions = db.query(
        "SELECT condition_name, icd10_code, snomed_code, clinical_status, onset_date, source "
        "FROM conditions ORDER BY clinical_status, condition_name"
    )
    table = _make_table(
        ["Condition", "ICD-10", "Status", "Onset", "Source"],
        [[c["condition_name"], c.get("icd10_code", ""), c.get("clinical_status", ""),
          c.get("onset_date", ""), c["source"]] for c in conditions],
    )
    _write_page(content / "conditions.md", "Conditions", table)


def _generate_pathology(content: Path, data: Path, db: ChartfoldDB) -> None:
    reports = db.query(
        "SELECT p.report_date, p.specimen, p.diagnosis, p.staging, p.margins, "
        "p.lymph_nodes, p.source, pr.name as procedure_name "
        "FROM pathology_reports p "
        "LEFT JOIN procedures pr ON p.procedure_id = pr.id "
        "ORDER BY p.report_date"
    )
    table = _make_table(
        ["Date", "Procedure", "Specimen", "Diagnosis", "Staging", "Margins", "Source"],
        [[r["report_date"], r.get("procedure_name", ""), r.get("specimen", ""),
          (r.get("diagnosis", "") or "")[:80], r.get("staging", ""),
          r.get("margins", ""), r["source"]] for r in reports],
    )
    _write_page(content / "pathology.md", "Pathology Reports", table)


def _generate_surgical(content: Path, data: Path, db: ChartfoldDB) -> None:
    timeline = build_surgical_timeline(db)
    _write_json(data / "surgical_timeline.json", timeline)

    rows = []
    for entry in timeline:
        proc = entry["procedure"]
        path = entry.get("pathology") or {}
        rows.append([
            proc["date"],
            proc["name"],
            (path.get("diagnosis", "") or "")[:60],
            path.get("staging", ""),
            path.get("margins", ""),
            proc["source"],
        ])

    table = _make_table(
        ["Date", "Procedure", "Pathology", "Stage", "Margins", "Source"],
        rows,
    )
    _write_page(content / "surgical.md", "Surgical Timeline", table)


def _generate_imaging(content: Path, data: Path, db: ChartfoldDB) -> None:
    reports = db.query(
        "SELECT study_name, modality, study_date, impression, source "
        "FROM imaging_reports ORDER BY study_date DESC"
    )
    table = _make_table(
        ["Date", "Modality", "Study", "Impression", "Source"],
        [[r["study_date"], r.get("modality", ""), r["study_name"],
          (r.get("impression", "") or "")[:80], r["source"]] for r in reports],
    )
    _write_page(content / "imaging.md", "Imaging Reports", table)


def _make_table(headers: list[str], rows: list[list]) -> str:
    """Generate a markdown table."""
    if not rows:
        return "*No data available.*"
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join(
        "| " + " | ".join(str(c).replace("|", "\\|") if c else "" for c in row) + " |"
        for row in rows
    )
    return f"{header}\n{sep}\n{body}"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate Hugo site from chartfold DB")
    parser.add_argument("--db", default="chartfold.db", help="Database path")
    parser.add_argument("--hugo-dir", default="./site", help="Hugo output directory")
    args = parser.parse_args()
    generate_site(args.db, args.hugo_dir)


if __name__ == "__main__":
    main()
