"""Generate Hugo static site content from the chartfold SQLite database.

Writes markdown + JSON data files into the Hugo content/ and data/ directories.
Run Hugo after generation to build the static site.

Usage:
    python -m chartfold.hugo.generate --db chartfold.db --hugo-dir ./site
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from chartfold.analysis.lab_trends import (
    get_abnormal_labs,
    get_lab_series,
    get_latest_labs,
)
from chartfold.analysis.medications import get_active_medications
from chartfold.analysis.surgical_timeline import build_surgical_timeline
from chartfold.config import get_lab_test_configs, load_config
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


def _build_asset_lookup(db: ChartfoldDB) -> dict:
    """Query source_assets and build indexes for bidirectional linking.

    Returns dict with keys:
        - all: list of all asset rows
        - by_ref: {(ref_table, ref_id): [asset_rows]} for direct-linked assets
        - by_date_source: {(encounter_date, source): [asset_rows]} for date-matched
        - by_date: {encounter_date: [asset_rows]} for date-only grouping
    """
    assets = db.query(
        "SELECT id, source, asset_type, file_path, file_name, "
        "file_size_kb, title, encounter_date, encounter_id, "
        "ref_table, ref_id, metadata "
        "FROM source_assets ORDER BY source, encounter_date, file_name"
    )

    by_ref: dict[tuple, list] = {}
    by_date_source: dict[tuple, list] = {}
    by_date: dict[str, list] = {}

    for a in assets:
        # Index by direct reference
        if a.get("ref_table") and a.get("ref_id"):
            key = (a["ref_table"], a["ref_id"])
            by_ref.setdefault(key, []).append(a)

        # Index by (date, source)
        if a.get("encounter_date"):
            ds_key = (a["encounter_date"], a["source"])
            by_date_source.setdefault(ds_key, []).append(a)
            by_date.setdefault(a["encounter_date"], []).append(a)

    return {
        "all": assets,
        "by_ref": by_ref,
        "by_date_source": by_date_source,
        "by_date": by_date,
    }


def _render_source_docs_section(
    asset_lookup: dict,
    asset_url_map: dict[int, str],
    ref_table: str = "",
    ref_id: int | None = None,
    date: str = "",
    source: str = "",
) -> str:
    """Render a '### Source Documents' section for a clinical detail page.

    Images render as lightbox thumbnails (gallery grid if 3+).
    PDFs render as categorized download links.
    """
    from chartfold.core.utils import categorize_asset_title, is_image_asset

    matched: list[dict] = []
    seen_ids: set[int] = set()

    # Priority 1: direct ref match
    if ref_table and ref_id is not None:
        for a in asset_lookup.get("by_ref", {}).get((ref_table, ref_id), []):
            if a["id"] not in seen_ids:
                matched.append(a)
                seen_ids.add(a["id"])

    # Priority 2: date + source fallback
    if date and source:
        for a in asset_lookup.get("by_date_source", {}).get((date, source), []):
            if a["id"] not in seen_ids:
                matched.append(a)
                seen_ids.add(a["id"])

    if not matched:
        return ""

    # Separate images from other assets
    images = []
    other = []
    for a in matched:
        url = asset_url_map.get(a["id"])
        if not url:
            continue
        if is_image_asset(a["asset_type"]):
            images.append((a, url))
        else:
            other.append((a, url))

    if not images and not other:
        return ""

    lines = ["### Source Documents", ""]

    # Render images
    if images:
        if len(images) >= 3:
            lines.append('<div class="asset-gallery">')
        for a, url in images:
            alt = a.get("title") or a["file_name"]
            lines.append(f'{{{{< lightbox src="{url}" alt="{alt}" >}}}}')
        if len(images) >= 3:
            lines.append("</div>")
        lines.append("")

    # Render PDFs / other as categorized links
    for a, url in other:
        display = a.get("title") or a["file_name"]
        category = categorize_asset_title(a.get("title", ""))
        size = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
        cat_label = f"{category}, " if category != "General" else ""
        detail = f" ({cat_label}{a['asset_type']}" + (f", {size}" if size else "") + ")"
        lines.append(f"- [{display}]({url}){detail}")

    # If only headers were added, return empty
    content_lines = [l for l in lines if l.strip() and l != "### Source Documents"]
    if not content_lines:
        return ""

    return "\n".join(lines)


def generate_site(
    db_path: str, hugo_dir: str, config_path: str = "", linked_sources: bool = False
) -> None:
    """Generate the full Hugo site from a chartfold database.

    Args:
        db_path: Path to the chartfold SQLite database.
        hugo_dir: Output directory for the Hugo site.
        config_path: Path to chartfold.toml config file. Empty uses default.
        linked_sources: If True, copy source EHR assets into Hugo static folder.
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

        # Build asset data for linked sources (must happen before detail pages)
        if linked_sources:
            asset_lookup = _build_asset_lookup(db)
            asset_url_map = _generate_linked_sources(content, out / "static", db)
        else:
            asset_lookup = None
            asset_url_map = {}
            _write_page(
                content / "sources.md",
                "Source Documents",
                "*Source documents not included. "
                "Run with `--linked-sources` to copy EHR assets into the site.*",
            )

        # Encounters
        _generate_encounters(
            content, data, db, asset_lookup=asset_lookup, asset_url_map=asset_url_map
        )

        # Medications
        _generate_medications(content, data, db)

        # Conditions
        _generate_conditions(content, data, db)

        # Clinical Notes
        _generate_clinical_notes(
            content, data, db, asset_lookup=asset_lookup, asset_url_map=asset_url_map
        )

        # Pathology
        _generate_pathology(
            content, data, db, asset_lookup=asset_lookup, asset_url_map=asset_url_map
        )

        # Surgical Timeline
        _generate_surgical(
            content, data, db, asset_lookup=asset_lookup, asset_url_map=asset_url_map
        )

        # Imaging
        _generate_imaging(content, data, db, asset_lookup=asset_lookup, asset_url_map=asset_url_map)

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
    fm = f'---\ntitle: "{title}"\n{extra_frontmatter}---\n\n'
    filepath.write_text(fm + content)


def _write_json(filepath: Path, data) -> None:
    """Write a JSON data file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(data, indent=2, default=str))


def _generate_dashboard(
    content: Path,
    data: Path,
    db: ChartfoldDB,
    summary: dict,
    sources: list,
    config: dict | None = None,
) -> None:
    """Generate the dashboard/index page."""
    hugo_config = (config or {}).get("hugo", {})
    recent_labs_count = hugo_config.get("dashboard_recent_labs", 10)

    cards = []
    for table, count in summary.items():
        if count > 0:
            cards.append(
                f'<div class="card"><h3>{table.replace("_", " ").title()}</h3>'
                f'<div class="value">{count}</div></div>'
            )

    source_list = ""
    for s in sources:
        source_list += f"- **{s['source']}** — loaded {s['loaded_at'][:19]}\n"

    # Recent abnormal labs
    abnormal = get_abnormal_labs(db)[:recent_labs_count]
    abnormal_table = _make_table(
        ["Test", "Value", "Unit", "Flag", "Date", "Source"],
        [
            [
                r["test_name"],
                r["value"],
                r["unit"],
                r["interpretation"],
                r["result_date"],
                r["source"],
            ]
            for r in abnormal
        ],
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
        [
            [
                e["encounter_date"],
                e.get("encounter_type", ""),
                e.get("facility", ""),
                e.get("provider", ""),
                e["source"],
            ]
            for e in recent_enc
        ],
    )

    # Active conditions
    active_cond = db.query(
        "SELECT condition_name, icd10_code, onset_date, source "
        "FROM conditions WHERE LOWER(clinical_status) = 'active' "
        "ORDER BY condition_name"
    )
    cond_table = _make_table(
        ["Condition", "ICD-10", "Onset", "Source"],
        [
            [c["condition_name"], c.get("icd10_code", ""), c.get("onset_date", ""), c["source"]]
            for c in active_cond
        ],
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

    for enc in db.query(
        "SELECT id, encounter_date, encounter_type, facility, provider, source "
        "FROM encounters ORDER BY encounter_date DESC"
    ):
        events.append(
            {
                "date": enc["encounter_date"],
                "type": "Encounter",
                "detail": f"{enc.get('encounter_type', '')} at {enc.get('facility', '')}",
                "source": enc["source"],
                "link": f"/encounters/{enc['id']}/",
            }
        )

    for proc in db.query(
        "SELECT id, procedure_date, name, facility, source "
        "FROM procedures ORDER BY procedure_date DESC"
    ):
        events.append(
            {
                "date": proc["procedure_date"],
                "type": "Procedure",
                "detail": proc["name"],
                "source": proc["source"],
                "link": f"/surgical/{proc['id']}/",
            }
        )

    for img in db.query(
        "SELECT id, study_date, study_name, modality, source "
        "FROM imaging_reports ORDER BY study_date DESC"
    ):
        events.append(
            {
                "date": img["study_date"],
                "type": "Imaging",
                "detail": f"{img.get('modality', '')} — {img['study_name']}",
                "source": img["source"],
                "link": f"/imaging/{img['id']}/",
            }
        )

    # Add lab collection dates (grouped by date to avoid overwhelming the timeline)
    lab_dates = db.query(
        "SELECT result_date, COUNT(*) as count, GROUP_CONCAT(DISTINCT source) as sources "
        "FROM lab_results GROUP BY result_date ORDER BY result_date DESC"
    )
    for ld in lab_dates:
        events.append(
            {
                "date": ld["result_date"],
                "type": "Labs",
                "detail": f"{ld['count']} lab results",
                "source": ld["sources"],
                "link": "/labs/",
            }
        )

    # Add pathology reports
    for path in db.query(
        "SELECT id, report_date, specimen, diagnosis, source "
        "FROM pathology_reports ORDER BY report_date DESC"
    ):
        events.append(
            {
                "date": path["report_date"],
                "type": "Pathology",
                "detail": (path.get("diagnosis", "") or "")[:60],
                "source": path["source"],
                "link": f"/pathology/{path['id']}/",
            }
        )

    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    _write_json(data / "timeline.json", events)

    rows = []
    for e in events:
        rows.append(
            [
                e["date"],
                e["type"],
                (e["detail"][:80], e["link"]),
                e["source"],
            ]
        )
    table = _make_linked_table(
        ["Date", "Type", "Detail", "Source"],
        rows,
        link_col=2,
    )
    _write_page(content / "timeline.md", "Timeline", table)


def _generate_labs(content: Path, data: Path, db: ChartfoldDB, config: dict | None = None) -> None:
    """Generate lab pages with trend charts."""
    labs_dir = content / "labs"
    labs_dir.mkdir(parents=True, exist_ok=True)

    latest = get_latest_labs(db)
    table = _make_table(
        ["Test", "Value", "Unit", "Range", "Flag", "Date", "Source"],
        [
            [
                r["test_name"],
                r["value"],
                r["unit"],
                r["ref_range"],
                r["interpretation"] or "",
                r["result_date"],
                r["source"],
            ]
            for r in latest
        ],
    )

    # Individual trend pages for configured lab tests
    # Collect info so we can build links on the index page
    lab_tests = get_lab_test_configs(config or {})
    trend_pages = []  # (name, slug) pairs for index links
    for lt in lab_tests:
        series = get_lab_series(db, test_names=lt.match)
        if not series["results"]:
            continue

        trend = series["results"]

        # Build per-source datasets for Chart.js
        sources = series["sources"]
        datasets = []
        for i, src in enumerate(sources):
            # Filter to results with numeric values to keep labels/values aligned
            src_results = [
                r for r in trend if r["source"] == src and r["value_numeric"] is not None
            ]
            color = SOURCE_COLORS[i % len(SOURCE_COLORS)]
            datasets.append(
                {
                    "source": src,
                    "labels": [r["result_date"] for r in src_results],
                    "values": [r["value_numeric"] for r in src_results],
                    "color": color,
                }
            )

        chart_data = {
            "test_name": lt.name,
            "unit": trend[0]["unit"] if trend else "",
            "datasets": datasets,
            "ref_ranges": series["ref_ranges"],
            "ref_range_discrepancy": series["ref_range_discrepancy"],
        }
        slug_base = lt.name.lower().replace(" ", "_")
        _write_json(data / f"lab_{slug_base}.json", chart_data)

        # Ref range note
        ref_note = ""
        if series["ref_range_discrepancy"]:
            ranges_str = ", ".join(f"**{src}**: {rr}" for src, rr in series["ref_ranges"].items())
            ref_note = f"\n> **Note:** Reference ranges differ across sources: {ranges_str}\n"

        table = _make_table(
            ["Date", "Value", "Unit", "Range", "Flag", "Source"],
            [
                [
                    r["result_date"],
                    r["value"],
                    r["unit"],
                    r["ref_range"],
                    r["interpretation"] or "",
                    r["source"],
                ]
                for r in trend
            ],
        )

        # Build Chart.js with per-source datasets
        datasets_js = []
        for ds in datasets:
            src_label = ds["source"]
            data_points = json.dumps(list(zip(ds["labels"], ds["values"], strict=False)))
            datasets_js.append(
                f"{{ label: '{src_label}', "
                f"data: {data_points}.map(p => ({{x: p[0], y: p[1]}})), "
                f"borderColor: '{ds['color']}', backgroundColor: '{ds['color']}', "
                f"tension: 0.1, fill: false, pointRadius: 4 }}"
            )
        datasets_str = ",\n          ".join(datasets_js)

        chart_id = lt.name.lower().replace(" ", "-")
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
    plugins: {{ title: {{ display: true, text: '{lt.name} ({chart_data["unit"]})' }} }}
  }}
}});
</script>
"""
        slug = lt.name.lower().replace(" ", "-")
        trend_pages.append((lt.name, slug))
        _write_page(
            labs_dir / f"{slug}.md",
            f"{lt.name} Trend",
            f"{chart_html}\n{ref_note}\n## Values\n\n{table}",
        )

    # Build index page with trend chart links above the latest-results table
    trend_links = ""
    if trend_pages:
        links = " &nbsp;|&nbsp; ".join(f"[{name}](/labs/{slug}/)" for name, slug in trend_pages)
        trend_links = f"## Trend Charts\n\n{links}\n\n"

    _write_page(labs_dir / "_index.md", "Lab Results", f"{trend_links}## Latest Results\n\n{table}")


def _generate_encounters(
    content: Path,
    data: Path,
    db: ChartfoldDB,
    asset_lookup: dict | None = None,
    asset_url_map: dict[int, str] | None = None,
) -> None:
    encounters = db.query(
        "SELECT id, encounter_date, encounter_type, facility, provider, "
        "reason, discharge_disposition, source "
        "FROM encounters ORDER BY encounter_date DESC"
    )

    enc_dir = content / "encounters"
    enc_dir.mkdir(parents=True, exist_ok=True)

    # Detail pages
    for e in encounters:
        eid = e["id"]
        etype = e.get("encounter_type", "") or "Encounter"
        date = e.get("encounter_date", "") or ""
        title = f"{etype} — {date}" if date else etype

        meta_parts = []
        if date:
            meta_parts.append(f"**Date:** {date}")
        if e.get("encounter_type"):
            meta_parts.append(f"**Type:** {e['encounter_type']}")
        if e.get("facility"):
            meta_parts.append(f"**Facility:** {e['facility']}")
        if e.get("provider"):
            meta_parts.append(f"**Provider:** {e['provider']}")
        if e.get("reason"):
            meta_parts.append(f"**Reason:** {e['reason']}")
        if e.get("discharge_disposition"):
            meta_parts.append(f"**Discharge Disposition:** {e['discharge_disposition']}")
        if e.get("source"):
            meta_parts.append(f"**Source:** {e['source']}")

        body = "\n\n".join(meta_parts)

        # Enrich with related records from the same date
        if date:
            related_sections = []

            # Clinical notes from the same date
            related_notes = db.query(
                "SELECT id, note_type, author, content FROM clinical_notes "
                "WHERE note_date = ? ORDER BY note_type",
                (date,),
            )
            if related_notes:
                note_rows = []
                for n in related_notes:
                    nid = n["id"]
                    snippet = (n.get("content", "") or "")[:80].replace("\n", " ")
                    note_rows.append(
                        [
                            (n.get("note_type", "") or "Note", f"/notes/{nid}/"),
                            n.get("author", "") or "",
                            snippet,
                        ]
                    )
                note_table = _make_linked_table(
                    ["Type", "Author", "Content"],
                    note_rows,
                    link_col=0,
                )
                related_sections.append(f"### Clinical Notes\n\n{note_table}")

            # Lab results from the same date
            lab_count_row = db.query(
                "SELECT COUNT(*) as cnt FROM lab_results WHERE result_date = ?",
                (date,),
            )
            lab_count = lab_count_row[0]["cnt"] if lab_count_row else 0
            if lab_count > 0:
                related_sections.append(
                    f"### Lab Results\n\n"
                    f"{lab_count} lab results on this date. "
                    f"[View all labs →](/labs/)"
                )

            # Procedures from the same date
            related_procs = db.query(
                "SELECT id, name, provider FROM procedures WHERE procedure_date = ? ORDER BY name",
                (date,),
            )
            if related_procs:
                proc_rows = []
                for p in related_procs:
                    pid = p["id"]
                    proc_rows.append(
                        [
                            (p.get("name", ""), f"/surgical/{pid}/"),
                            p.get("provider", "") or "",
                        ]
                    )
                proc_table = _make_linked_table(
                    ["Procedure", "Provider"],
                    proc_rows,
                    link_col=0,
                )
                related_sections.append(f"### Procedures\n\n{proc_table}")

            if related_sections:
                body += "\n\n---\n\n## Related Records\n\n" + "\n\n".join(related_sections)

        if asset_lookup and asset_url_map:
            source_docs = _render_source_docs_section(
                asset_lookup,
                asset_url_map,
                ref_table="encounters",
                ref_id=eid,
                date=date,
                source=e.get("source", ""),
            )
            if source_docs:
                body += "\n\n---\n\n" + source_docs

        _write_page(enc_dir / f"{eid}.md", title, body)

    # Index page with linked table
    rows = []
    for e in encounters:
        eid = e["id"]
        date = e.get("encounter_date", "") or ""
        rows.append(
            [
                (date, f"/encounters/{eid}/"),
                e.get("encounter_type", "") or "",
                e.get("facility", "") or "",
                e.get("provider", "") or "",
                (e.get("reason", "") or "")[:60],
                e.get("source", ""),
            ]
        )
    table = _make_linked_table(
        ["Date", "Type", "Facility", "Provider", "Reason", "Source"],
        rows,
        link_col=0,
    )
    _write_page(enc_dir / "_index.md", "Encounters", table)


def _generate_medications(content: Path, data: Path, db: ChartfoldDB) -> None:
    active = get_active_medications(db)
    all_meds = db.query(
        "SELECT name, status, sig, start_date, stop_date, source "
        "FROM medications ORDER BY status, name"
    )

    active_table = _make_table(
        ["Name", "Sig", "Route", "Start Date", "Source"],
        [
            [m["name"], m.get("sig", ""), m.get("route", ""), m.get("start_date", ""), m["source"]]
            for m in active
        ],
    )
    all_table = _make_table(
        ["Name", "Status", "Sig", "Start", "Stop", "Source"],
        [
            [
                m["name"],
                m["status"],
                m.get("sig", "")[:40],
                m.get("start_date", ""),
                m.get("stop_date", ""),
                m["source"],
            ]
            for m in all_meds
        ],
    )
    _write_page(
        content / "medications.md",
        "Medications",
        f"## Active Medications\n\n{active_table}\n\n## All Medications\n\n{all_table}",
    )


def _generate_conditions(content: Path, data: Path, db: ChartfoldDB) -> None:
    conditions = db.query(
        "SELECT condition_name, icd10_code, snomed_code, clinical_status, onset_date, source "
        "FROM conditions ORDER BY clinical_status, condition_name"
    )
    table = _make_table(
        ["Condition", "ICD-10", "Status", "Onset", "Source"],
        [
            [
                c["condition_name"],
                c.get("icd10_code", ""),
                c.get("clinical_status", ""),
                c.get("onset_date", ""),
                c["source"],
            ]
            for c in conditions
        ],
    )
    _write_page(content / "conditions.md", "Conditions", table)


def _generate_clinical_notes(
    content: Path,
    data: Path,
    db: ChartfoldDB,
    asset_lookup: dict | None = None,
    asset_url_map: dict[int, str] | None = None,
) -> None:
    """Generate clinical notes index and detail pages."""
    notes = db.query(
        "SELECT id, note_type, author, note_date, content, content_format, source "
        "FROM clinical_notes ORDER BY note_date DESC"
    )

    notes_dir = content / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # Detail pages
    for n in notes:
        nid = n["id"]
        ntype = n.get("note_type", "") or "Note"
        date = n.get("note_date", "") or ""
        title = f"{ntype} — {date}" if date else ntype

        meta_parts = []
        if date:
            meta_parts.append(f"**Date:** {date}")
        if n.get("note_type"):
            meta_parts.append(f"**Type:** {n['note_type']}")
        if n.get("author"):
            meta_parts.append(f"**Author:** {n['author']}")
        if n.get("source"):
            meta_parts.append(f"**Source:** {n['source']}")
        meta = "\n\n".join(meta_parts)

        note_content = n.get("content", "") or ""
        fmt = n.get("content_format", "text") or "text"
        if fmt == "html":
            body_section = f"\n\n{note_content}"
        else:
            note_content = _format_report_text(note_content)
            body_section = f'\n\n<div class="report-body">\n\n{note_content}\n\n</div>'

        body = meta + body_section

        if asset_lookup and asset_url_map:
            source_docs = _render_source_docs_section(
                asset_lookup,
                asset_url_map,
                ref_table="clinical_notes",
                ref_id=nid,
                date=date,
                source=n.get("source", ""),
            )
            if source_docs:
                body += "\n\n---\n\n" + source_docs

        _write_page(notes_dir / f"{nid}.md", title, body)

    # Index page with linked table
    rows = []
    for n in notes:
        nid = n["id"]
        date = n.get("note_date", "") or ""
        snippet = (n.get("content", "") or "")[:80].replace("\n", " ")
        rows.append(
            [
                (date, f"/notes/{nid}/"),
                n.get("note_type", "") or "",
                n.get("author", "") or "",
                snippet,
                n.get("source", ""),
            ]
        )
    table = _make_linked_table(
        ["Date", "Type", "Author", "Content", "Source"],
        rows,
        link_col=0,
    )
    _write_page(notes_dir / "_index.md", "Clinical Notes", table)


def _generate_pathology(
    content: Path,
    data: Path,
    db: ChartfoldDB,
    asset_lookup: dict | None = None,
    asset_url_map: dict[int, str] | None = None,
) -> None:
    reports = db.query(
        "SELECT p.id, p.report_date, p.specimen, p.diagnosis, p.staging, "
        "p.margins, p.lymph_nodes, p.gross_description, "
        "p.microscopic_description, p.full_text, p.source, p.procedure_id, "
        "pr.name as procedure_name, pr.procedure_date "
        "FROM pathology_reports p "
        "LEFT JOIN procedures pr ON p.procedure_id = pr.id "
        "ORDER BY p.report_date"
    )

    path_dir = content / "pathology"
    path_dir.mkdir(parents=True, exist_ok=True)

    # Detail pages
    for r in reports:
        rid = r["id"]
        specimen = r.get("specimen", "") or "Specimen"
        date = r.get("report_date", "") or ""
        title = f"{specimen} — {date}" if date else specimen

        # Build structured metadata section
        meta_parts = []
        if r.get("procedure_name"):
            proc_date = r.get("procedure_date", "") or ""
            meta_parts.append(
                f"**Procedure:** {r['procedure_name']}" + (f" ({proc_date})" if proc_date else "")
            )
        if date:
            meta_parts.append(f"**Report Date:** {date}")
        if r.get("source"):
            meta_parts.append(f"**Source:** {r['source']}")
        meta = "\n\n".join(meta_parts)

        # Structured fields
        sections = []
        for label, key in [
            ("Diagnosis", "diagnosis"),
            ("Staging", "staging"),
            ("Margins", "margins"),
            ("Lymph Nodes", "lymph_nodes"),
        ]:
            val = r.get(key, "") or ""
            if val:
                sections.append(
                    f'<div class="report-section">\n\n'
                    f"### {label}\n\n"
                    f'<div class="report-body">\n\n{val}\n\n</div>\n</div>'
                )

        for label, key in [
            ("Gross Description", "gross_description"),
            ("Microscopic Description", "microscopic_description"),
        ]:
            val = r.get(key, "") or ""
            if val:
                val = _format_report_text(val)
                sections.append(
                    f'<div class="report-section">\n\n'
                    f"### {label}\n\n"
                    f'<div class="report-body">\n\n{val}\n\n</div>\n</div>'
                )

        full = r.get("full_text", "") or ""
        if full:
            full = _format_report_text(full)
            sections.append(
                f"\n<details>\n<summary>Full Report Text</summary>\n\n"
                f'<div class="report-body">\n\n{full}\n\n</div>\n\n</details>'
            )

        body = f"{meta}\n\n" + "\n\n".join(sections) if sections else meta

        if asset_lookup and asset_url_map:
            source_docs = _render_source_docs_section(
                asset_lookup,
                asset_url_map,
                ref_table="pathology_reports",
                ref_id=rid,
                date=date,
                source=r.get("source", ""),
            )
            if source_docs:
                body += "\n\n---\n\n" + source_docs

        _write_page(path_dir / f"{rid}.md", title, body)

    # Index page with linked table
    rows = []
    for r in reports:
        rid = r["id"]
        date = r.get("report_date", "") or ""
        rows.append(
            [
                (date, f"/pathology/{rid}/"),
                r.get("procedure_name", "") or "",
                r.get("specimen", "") or "",
                (r.get("diagnosis", "") or "")[:80],
                r.get("staging", "") or "",
                r.get("margins", "") or "",
                r.get("source", ""),
            ]
        )
    table = _make_linked_table(
        ["Date", "Procedure", "Specimen", "Diagnosis", "Staging", "Margins", "Source"],
        rows,
        link_col=0,
    )
    _write_page(path_dir / "_index.md", "Pathology Reports", table)


def _generate_surgical(
    content: Path,
    data: Path,
    db: ChartfoldDB,
    asset_lookup: dict | None = None,
    asset_url_map: dict[int, str] | None = None,
) -> None:
    timeline = build_surgical_timeline(db)
    _write_json(data / "surgical_timeline.json", timeline)

    surg_dir = content / "surgical"
    surg_dir.mkdir(parents=True, exist_ok=True)

    # Detail pages for each procedure
    for entry in timeline:
        proc = entry["procedure"]
        proc_id = proc["id"]
        proc_name = proc.get("name", "") or "Procedure"
        proc_date = proc.get("date", "") or ""
        title = f"{proc_name} — {proc_date}" if proc_date else proc_name

        # Procedure metadata
        meta_parts = []
        if proc_date:
            meta_parts.append(f"**Date:** {proc_date}")
        if proc.get("name"):
            meta_parts.append(f"**Procedure:** {proc['name']}")
        if proc.get("provider"):
            meta_parts.append(f"**Provider:** {proc['provider']}")
        if proc.get("facility"):
            meta_parts.append(f"**Facility:** {proc['facility']}")
        if proc.get("source"):
            meta_parts.append(f"**Source:** {proc['source']}")
        meta = "\n\n".join(meta_parts)

        sections = []

        # Operative note
        op_note = proc.get("operative_note", "") or ""
        if not op_note:
            # Try to get from DB directly
            proc_row = db.query("SELECT operative_note FROM procedures WHERE id = ?", (proc_id,))
            if proc_row:
                op_note = proc_row[0].get("operative_note", "") or ""
        if op_note:
            op_note = _format_report_text(op_note)
            sections.append(
                f'<div class="report-section">\n\n'
                f"### Operative Note\n\n"
                f'<div class="report-body">\n\n{op_note}\n\n</div>\n</div>'
            )

        # Linked pathology
        path = entry.get("pathology") or {}
        if path:
            path_parts = []
            path_id = path.get("id")
            if path.get("diagnosis"):
                path_parts.append(f"**Diagnosis:** {path['diagnosis']}")
            if path.get("staging"):
                path_parts.append(f"**Staging:** {path['staging']}")
            if path.get("margins"):
                path_parts.append(f"**Margins:** {path['margins']}")
            if path.get("lymph_nodes"):
                path_parts.append(f"**Lymph Nodes:** {path['lymph_nodes']}")
            if path_id:
                path_parts.append(f"\n[View full pathology report →](/pathology/{path_id}/)")
            sections.append("### Pathology\n\n" + "\n\n".join(path_parts))

        # Related imaging
        related_img = entry.get("related_imaging", [])
        if related_img:
            img_rows = []
            for img in related_img:
                img_id = img.get("id")
                img_date = img.get("date", "")
                if img_id:
                    img_rows.append(
                        [
                            (img_date, f"/imaging/{img_id}/"),
                            img.get("modality", ""),
                            img.get("study", ""),
                            img.get("timing", ""),
                            (img.get("impression", "") or "")[:60],
                        ]
                    )
                else:
                    img_rows.append(
                        [
                            img_date,
                            img.get("modality", ""),
                            img.get("study", ""),
                            img.get("timing", ""),
                            (img.get("impression", "") or "")[:60],
                        ]
                    )
            img_table = _make_linked_table(
                ["Date", "Modality", "Study", "Timing", "Impression"],
                img_rows,
                link_col=0,
            )
            sections.append(f"### Related Imaging\n\n{img_table}")

        # Related medications
        related_meds = entry.get("related_medications", [])
        if related_meds:
            med_list = "\n".join(f"- {m['name']} ({m.get('source', '')})" for m in related_meds)
            sections.append(f"### Related Medications\n\n{med_list}")

        body = meta + ("\n\n" + "\n\n".join(sections) if sections else "")

        if asset_lookup and asset_url_map:
            source_docs = _render_source_docs_section(
                asset_lookup,
                asset_url_map,
                ref_table="procedures",
                ref_id=proc_id,
                date=proc_date,
                source=proc.get("source", ""),
            )
            if source_docs:
                body += "\n\n---\n\n" + source_docs

        _write_page(surg_dir / f"{proc_id}.md", title, body)

    # Index page with linked table
    rows = []
    for entry in timeline:
        proc = entry["procedure"]
        proc_id = proc["id"]
        path = entry.get("pathology") or {}
        rows.append(
            [
                (proc["date"], f"/surgical/{proc_id}/"),
                proc["name"],
                (path.get("diagnosis", "") or "")[:60],
                path.get("staging", ""),
                path.get("margins", ""),
                proc["source"],
            ]
        )

    table = _make_linked_table(
        ["Date", "Procedure", "Pathology", "Stage", "Margins", "Source"],
        rows,
        link_col=0,
    )
    _write_page(surg_dir / "_index.md", "Surgical Timeline", table)


def _generate_imaging(
    content: Path,
    data: Path,
    db: ChartfoldDB,
    asset_lookup: dict | None = None,
    asset_url_map: dict[int, str] | None = None,
) -> None:
    reports = db.query(
        "SELECT id, study_name, modality, study_date, ordering_provider, "
        "findings, impression, full_text, source "
        "FROM imaging_reports ORDER BY study_date DESC"
    )

    img_dir = content / "imaging"
    img_dir.mkdir(parents=True, exist_ok=True)

    # Detail pages
    for r in reports:
        rid = r["id"]
        study = r.get("study_name", "") or "Study"
        date = r.get("study_date", "") or ""
        title = f"{study} — {date}" if date else study

        meta_parts = []
        if r.get("modality"):
            meta_parts.append(f"**Modality:** {r['modality']}")
        if date:
            meta_parts.append(f"**Date:** {date}")
        if r.get("ordering_provider"):
            meta_parts.append(f"**Ordering Provider:** {r['ordering_provider']}")
        if r.get("source"):
            meta_parts.append(f"**Source:** {r['source']}")
        meta = "\n\n".join(meta_parts)

        sections = []
        findings = r.get("findings", "") or ""
        if findings:
            sections.append(
                f'<div class="report-section">\n\n'
                f"### Findings\n\n"
                f'<div class="report-body">\n\n{findings}\n\n</div>\n</div>'
            )

        impression = r.get("impression", "") or ""
        if impression:
            sections.append(
                f'<div class="report-section">\n\n'
                f"### Impression\n\n"
                f'<div class="report-body">\n\n{impression}\n\n</div>\n</div>'
            )

        full = r.get("full_text", "") or ""
        if full and full not in (findings, impression):
            sections.append(
                f"\n<details>\n<summary>Full Report Text</summary>\n\n"
                f'<div class="report-body">\n\n{full}\n\n</div>\n\n</details>'
            )

        body = f"{meta}\n\n" + "\n\n".join(sections) if sections else meta

        if asset_lookup and asset_url_map:
            source_docs = _render_source_docs_section(
                asset_lookup,
                asset_url_map,
                ref_table="imaging_reports",
                ref_id=rid,
                date=date,
                source=r.get("source", ""),
            )
            if source_docs:
                body += "\n\n---\n\n" + source_docs

        _write_page(img_dir / f"{rid}.md", title, body)

    # Index page with linked table
    rows = []
    for r in reports:
        rid = r["id"]
        date = r.get("study_date", "") or ""
        rows.append(
            [
                (date, f"/imaging/{rid}/"),
                r.get("modality", "") or "",
                r.get("study_name", "") or "",
                (r.get("impression", "") or "")[:80],
                r.get("source", ""),
            ]
        )
    table = _make_linked_table(
        ["Date", "Modality", "Study", "Impression", "Source"],
        rows,
        link_col=0,
    )
    _write_page(img_dir / "_index.md", "Imaging Reports", table)


def _generate_linked_sources(content: Path, static: Path, db: ChartfoldDB) -> dict[int, str]:
    """Copy source assets into static/sources/ and generate grouped sources index.

    Returns:
        asset_url_map: {asset_id: relative_url} for use by detail page generators.
    """
    assets = db.query(
        "SELECT id, source, asset_type, file_path, file_name, "
        "file_size_kb, title, encounter_date, encounter_id, ref_table, ref_id "
        "FROM source_assets ORDER BY source, encounter_date, encounter_id, file_name"
    )
    if not assets:
        _write_page(content / "sources.md", "Source Documents", "*No source assets available.*")
        return {}

    sources_dir = static / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    # Copy files
    asset_url_map: dict[int, str] = {}
    for a in assets:
        src_path = Path(a["file_path"])
        if not src_path.exists():
            continue
        dest_name = f"{a['id']}_{a['file_name']}"
        dest_subdir = sources_dir / a["source"]
        dest_subdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_subdir / dest_name)
        asset_url_map[a["id"]] = f"/sources/{a['source']}/{dest_name}"

    # Query related clinical records for back-links
    encounters_by_date: dict[str, list[dict]] = {}
    for e in db.query("SELECT id, encounter_date, encounter_type, facility FROM encounters"):
        d = e.get("encounter_date", "")
        if d:
            encounters_by_date.setdefault(d, []).append(e)

    procedures_by_date: dict[str, list[dict]] = {}
    for p in db.query("SELECT id, procedure_date, name FROM procedures"):
        d = p.get("procedure_date", "")
        if d:
            procedures_by_date.setdefault(d, []).append(p)

    notes_by_date: dict[str, list[dict]] = {}
    for n in db.query("SELECT id, note_date, note_type FROM clinical_notes"):
        d = n.get("note_date", "")
        if d:
            notes_by_date.setdefault(d, []).append(n)

    # Group assets by date, then by encounter_id, then other
    dated: dict[str, list] = {}
    by_encounter_id: dict[str, list] = {}
    other: list = []
    for a in assets:
        if a["id"] not in asset_url_map:
            continue
        if a.get("encounter_date"):
            dated.setdefault(a["encounter_date"], []).append(a)
        elif a.get("encounter_id"):
            by_encounter_id.setdefault(a["encounter_id"], []).append(a)
        else:
            other.append(a)

    # Build page content
    md_parts = []

    # Dated groups (newest first)
    for date in sorted(dated.keys(), reverse=True):
        group = dated[date]
        md_parts.append(f"## {date}")

        # Back-links to clinical records on this date
        backlinks = []
        for e in encounters_by_date.get(date, []):
            etype = e.get("encounter_type", "") or "Encounter"
            backlinks.append(f"[{etype}](/encounters/{e['id']}/)")
        for p in procedures_by_date.get(date, []):
            backlinks.append(f"[{p['name']}](/surgical/{p['id']}/)")
        for n in notes_by_date.get(date, []):
            ntype = n.get("note_type", "") or "Note"
            backlinks.append(f"[{ntype}](/notes/{n['id']}/)")

        if backlinks:
            md_parts.append("**Related:** " + " &bull; ".join(backlinks))
            md_parts.append("")

        # Sub-group by category within each date
        from chartfold.core.utils import categorize_asset_title

        by_cat: dict[str, list] = {}
        for a in group:
            cat = categorize_asset_title(a.get("title", ""))
            by_cat.setdefault(cat, []).append(a)

        for cat in sorted(by_cat.keys()):
            cat_assets = by_cat[cat]
            md_parts.append(f"### {cat}")
            md_parts.append("")
            rows = []
            for a in cat_assets:
                url = asset_url_map[a["id"]]
                display = a.get("title") or a["file_name"]
                size_str = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
                rows.append(
                    [
                        (display, url),
                        a["asset_type"],
                        size_str,
                        a["source"],
                    ]
                )
            table = _make_linked_table(["Document", "Type", "Size", "Source"], rows, link_col=0)
            md_parts.append(table)
            md_parts.append("")

    # Encounter-ID groups (for assets with encounter_id but no date)
    for enc_id in sorted(by_encounter_id.keys()):
        group = by_encounter_id[enc_id]
        md_parts.append(f"## Encounter {enc_id}")

        # Back-links: try to find matching encounters by source_doc_id
        backlinks = []
        enc_matches = db.query(
            "SELECT id, encounter_date, encounter_type FROM encounters "
            "WHERE source_doc_id = ? OR source_doc_id LIKE ?",
            (enc_id, f"%{enc_id}%"),
        )
        for e in enc_matches:
            etype = e.get("encounter_type", "") or "Encounter"
            date_str = f" ({e['encounter_date']})" if e.get("encounter_date") else ""
            backlinks.append(f"[{etype}{date_str}](/encounters/{e['id']}/)")

        if backlinks:
            md_parts.append("**Related:** " + " &bull; ".join(backlinks))
            md_parts.append("")

        rows = []
        for a in group:
            url = asset_url_map[a["id"]]
            display = a.get("title") or a["file_name"]
            size_str = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
            rows.append(
                [
                    (display, url),
                    a["asset_type"],
                    size_str,
                    a["source"],
                ]
            )
        table = _make_linked_table(["Document", "Type", "Size", "Source"], rows, link_col=0)
        md_parts.append(table)
        md_parts.append("")

    # Other (no date, no encounter_id)
    if other:
        md_parts.append("## Other")
        rows = []
        for a in other:
            url = asset_url_map[a["id"]]
            display = a.get("title") or a["file_name"]
            size_str = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
            rows.append(
                [
                    (display, url),
                    a["asset_type"],
                    size_str,
                    a["source"],
                ]
            )
        table = _make_linked_table(["Document", "Type", "Size", "Source"], rows, link_col=0)
        md_parts.append(table)

    _write_page(content / "sources.md", "Source Documents", "\n".join(md_parts))
    return asset_url_map


_SECTION_MARKERS = re.compile(
    r"(?<!\n\n)"  # not already preceded by a blank line
    r"(?=(?:"
    r"Diagnosis:|Gross Description:|Microscopic Description:|"
    r"Specimen:|History:|Narrative:|Clinical History:|"
    r"Final Diagnosis:|Addendum:|Comment:|"
    r"IMPRESSION:|FINDINGS:|TECHNIQUE:|COMPARISON:|"
    r"CLINICAL INDICATION:|PROCEDURE:|"
    r"Assessment:|Plan:|Subjective:|Objective:"
    r"))",
    re.MULTILINE,
)


def _format_report_text(text: str) -> str:
    """Format clinical report text for better readability.

    - Inserts paragraph breaks before known section markers
    - Normalizes multiple consecutive spaces within lines
    - Strips leading/trailing whitespace per line
    - Preserves intentional structure (indented lists starting with - or *)
    """
    if not text:
        return text

    # Insert paragraph breaks before section markers
    text = _SECTION_MARKERS.sub("\n\n", text)

    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        # Preserve intentional indentation for list items
        if stripped.startswith(("-", "*", "•")):
            result.append("  " + stripped)
        else:
            # Normalize multiple spaces to single within the line
            result.append(re.sub(r"  +", " ", stripped))
    return "\n".join(result)


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


def _make_linked_table(headers: list[str], rows: list[list], link_col: int = 0) -> str:
    """Generate a markdown table where one column is a link.

    Each row's ``link_col`` element should be a tuple ``(text, url)``.
    All other elements are plain strings.  The link cell is rendered as
    ``[text](url)`` markdown which Hugo turns into a clickable ``<a>`` tag.
    """
    if not rows:
        return "*No data available.*"
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    lines = []
    for row in rows:
        cells = []
        for i, c in enumerate(row):
            if i == link_col and isinstance(c, tuple):
                text, url = c
                text = str(text).replace("|", "\\|") if text else ""
                cells.append(f"[{text}]({url})")
            else:
                cells.append(str(c).replace("|", "\\|") if c else "")
        lines.append("| " + " | ".join(cells) + " |")
    return f"{header}\n{sep}\n" + "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate Hugo site from chartfold DB")
    parser.add_argument("--db", default="chartfold.db", help="Database path")
    parser.add_argument("--hugo-dir", default="./site", help="Hugo output directory")
    args = parser.parse_args()
    generate_site(args.db, args.hugo_dir)


if __name__ == "__main__":
    main()
