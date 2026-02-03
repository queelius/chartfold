"""Export chartfold data as structured markdown or PDF.

Generates a clean, printable document with key clinical data — labs, meds,
conditions, encounters — suitable for bringing to a doctor's appointment.
"""

from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path

from chartfold.analysis.lab_trends import get_abnormal_labs, get_latest_labs
from chartfold.analysis.medications import get_active_medications, reconcile_medications
from chartfold.analysis.visit_prep import generate_visit_prep
from chartfold.db import ChartfoldDB
from chartfold.formatters.markdown import MarkdownWriter


def export_markdown(
    db: ChartfoldDB,
    output_path: str = "chartfold_export.md",
    lookback_months: int = 6,
) -> str:
    """Export key clinical data as structured markdown.

    Args:
        db: Database connection.
        output_path: Where to write the markdown file.
        lookback_months: How many months of recent data to include.

    Returns the output file path.
    """
    md = MarkdownWriter()
    today = date.today().isoformat()
    lookback = (date.today() - timedelta(days=lookback_months * 30)).isoformat()

    # Header
    md.heading("Clinical Records Summary", level=1)
    md.w(f"*Generated: {today}*")
    md.w(f"*Data from: {', '.join(_get_sources(db))}*")
    md.w()

    # Summary stats
    summary = db.summary()
    md.heading("Data Overview", level=2)
    for table, count in summary.items():
        if count > 0:
            md.w(f"- **{table.replace('_', ' ').title()}**: {count}")
    md.w()

    # Active conditions
    conditions = db.query(
        "SELECT condition_name, icd10_code, clinical_status, onset_date, source "
        "FROM conditions WHERE LOWER(clinical_status) = 'active' "
        "ORDER BY condition_name"
    )
    if conditions:
        md.separator()
        md.heading("Active Conditions", level=2)
        md.table(
            ["Condition", "ICD-10", "Onset", "Source"],
            [[c["condition_name"], c.get("icd10_code", ""),
              c.get("onset_date", ""), c["source"]] for c in conditions],
        )

    # Active medications
    active_meds = get_active_medications(db)
    if active_meds:
        md.separator()
        md.heading("Active Medications", level=2)
        md.table(
            ["Medication", "Sig", "Route", "Start Date", "Prescriber", "Source"],
            [[m["name"], m.get("sig", ""), m.get("route", ""),
              m.get("start_date", ""), m.get("prescriber", ""), m["source"]]
             for m in active_meds],
        )

    # Medication reconciliation
    recon = reconcile_medications(db)
    if recon["discrepancies"]:
        md.heading("Medication Discrepancies", level=3)
        md.w("*The following medications have conflicting status across sources:*")
        md.w()
        for disc in recon["discrepancies"]:
            statuses = ", ".join(f"{e['source']}: {e['status']}" for e in disc["entries"])
            md.w(f"- **{disc['name']}** — {statuses}")
        md.w()

    # Recent labs
    recent_labs = db.query(
        "SELECT test_name, value, value_numeric, unit, ref_range, "
        "interpretation, result_date, source "
        "FROM lab_results WHERE result_date >= ? "
        "ORDER BY result_date DESC",
        (lookback,),
    )
    if recent_labs:
        md.separator()
        md.heading(f"Lab Results (since {lookback})", level=2)
        md.table(
            ["Test", "Value", "Unit", "Range", "Flag", "Date", "Source"],
            [[r["test_name"], r["value"], r.get("unit", ""), r.get("ref_range", ""),
              r.get("interpretation", "") or "", r["result_date"], r["source"]]
             for r in recent_labs],
        )

    # Abnormal labs (all time)
    abnormal = get_abnormal_labs(db)
    if abnormal:
        md.separator()
        md.heading("Abnormal Lab Results (All Time)", level=2)
        md.table(
            ["Test", "Value", "Unit", "Range", "Flag", "Date", "Source"],
            [[r["test_name"], r["value"], r.get("unit", ""), r.get("ref_range", ""),
              r.get("interpretation", ""), r["result_date"], r["source"]]
             for r in abnormal[:50]],
        )

    # Recent encounters
    encounters = db.query(
        "SELECT encounter_date, encounter_type, facility, provider, reason, source "
        "FROM encounters WHERE encounter_date >= ? "
        "ORDER BY encounter_date DESC",
        (lookback,),
    )
    if encounters:
        md.separator()
        md.heading(f"Recent Encounters (since {lookback})", level=2)
        md.table(
            ["Date", "Type", "Facility", "Provider", "Reason", "Source"],
            [[e["encounter_date"], e.get("encounter_type", ""), e.get("facility", ""),
              e.get("provider", ""), (e.get("reason", "") or "")[:60], e["source"]]
             for e in encounters],
        )

    # Recent imaging
    imaging = db.query(
        "SELECT study_name, modality, study_date, impression, source "
        "FROM imaging_reports WHERE study_date >= ? "
        "ORDER BY study_date DESC",
        (lookback,),
    )
    if imaging:
        md.separator()
        md.heading(f"Imaging Reports (since {lookback})", level=2)
        for img in imaging:
            md.heading(f"{img['study_name']} — {img['study_date']}", level=3)
            md.w(f"*Modality: {img.get('modality', '')} | Source: {img['source']}*")
            md.w()
            if img.get("impression"):
                md.w(f"> {img['impression']}")
                md.w()

    # Pathology reports (all time — these are always important)
    pathology = db.query(
        "SELECT p.report_date, p.specimen, p.diagnosis, p.staging, p.margins, "
        "p.lymph_nodes, p.source, pr.name as procedure_name "
        "FROM pathology_reports p "
        "LEFT JOIN procedures pr ON p.procedure_id = pr.id "
        "ORDER BY p.report_date DESC"
    )
    if pathology:
        md.separator()
        md.heading("Pathology Reports", level=2)
        for p in pathology:
            title_parts = [p.get("procedure_name", ""), p["report_date"]]
            md.heading(" — ".join(t for t in title_parts if t), level=3)
            if p.get("specimen"):
                md.w(f"**Specimen:** {p['specimen']}")
            if p.get("diagnosis"):
                md.w(f"**Diagnosis:** {p['diagnosis']}")
            if p.get("staging"):
                md.w(f"**Staging:** {p['staging']}")
            if p.get("margins"):
                md.w(f"**Margins:** {p['margins']}")
            if p.get("lymph_nodes"):
                md.w(f"**Lymph Nodes:** {p['lymph_nodes']}")
            md.w(f"*Source: {p['source']}*")
            md.w()

    # Allergies
    allergies = db.query(
        "SELECT allergen, reaction, severity, source FROM allergies "
        "WHERE LOWER(status) = 'active' ORDER BY allergen"
    )
    if allergies:
        md.separator()
        md.heading("Allergies", level=2)
        md.table(
            ["Allergen", "Reaction", "Severity", "Source"],
            [[a["allergen"], a.get("reaction", ""), a.get("severity", ""),
              a["source"]] for a in allergies],
        )

    # Write output
    md.write_to_file(output_path)
    return output_path


def export_pdf(
    db: ChartfoldDB,
    output_path: str = "chartfold_export.pdf",
    lookback_months: int = 6,
) -> str:
    """Export key clinical data as PDF via pandoc.

    Requires pandoc to be installed. Falls back to markdown if pandoc is unavailable.

    Args:
        db: Database connection.
        output_path: Where to write the PDF file.
        lookback_months: How many months of recent data to include.

    Returns the output file path (may be .md if pandoc unavailable).
    """
    md_path = output_path.replace(".pdf", ".md")
    export_markdown(db, output_path=md_path, lookback_months=lookback_months)

    try:
        subprocess.run(
            ["pandoc", md_path, "-o", output_path,
             "--pdf-engine=xelatex",
             "-V", "geometry:margin=1in",
             "-V", "fontsize=10pt"],
            check=True, capture_output=True,
        )
        return output_path
    except FileNotFoundError:
        print("Warning: pandoc not found. Markdown file generated instead.")
        return md_path
    except subprocess.CalledProcessError as e:
        # Try weasyprint as fallback
        try:
            subprocess.run(
                ["pandoc", md_path, "-o", output_path, "--pdf-engine=weasyprint"],
                check=True, capture_output=True,
            )
            return output_path
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"Warning: PDF generation failed. Markdown file at {md_path}")
            return md_path


def _get_sources(db: ChartfoldDB) -> list[str]:
    """Get list of loaded source names."""
    rows = db.query("SELECT DISTINCT source FROM load_log ORDER BY source")
    if rows:
        return [r["source"] for r in rows]
    # Fallback: check actual tables
    rows = db.query(
        "SELECT DISTINCT source FROM lab_results "
        "UNION SELECT DISTINCT source FROM medications "
        "ORDER BY source"
    )
    return [r["source"] for r in rows]
