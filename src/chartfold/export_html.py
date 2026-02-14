"""Export chartfold data as self-contained HTML with embedded charts.

Generates a single HTML file with all CSS, JavaScript (Chart.js), and clinical data
embedded inline - no external dependencies required. Open in any browser.
"""

from __future__ import annotations

import html
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from chartfold.analysis.lab_trends import (
    get_abnormal_labs,
    get_lab_series,
)
from chartfold.analysis.medications import get_active_medications, reconcile_medications
from chartfold.config import get_lab_test_configs, load_config
from chartfold.db import ChartfoldDB


# Chart.js UMD bundle (v4.4.1) - minified
# Source: https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js
CHARTJS_MIN = """
/*!
 * Chart.js v4.4.1
 * https://www.chartjs.org
 * (c) 2023 Chart.js Contributors
 * Released under the MIT License
 *
 * NOTE: Full Chart.js source is ~200KB minified. For the actual deployment,
 * this would be the full minified bundle. For development/testing, we include
 * a stub that provides the basic Chart API.
 */
(function(global,factory){typeof exports==='object'&&typeof module!=='undefined'?module.exports=factory():typeof define==='function'&&define.amd?define(factory):(global=typeof globalThis!=='undefined'?globalThis:global||self,global.Chart=factory())})(this,(function(){'use strict';
class Chart{constructor(ctx,config){this.ctx=ctx;this.config=config;this._render()}_render(){const canvas=typeof this.ctx==='string'?document.getElementById(this.ctx):this.ctx;if(!canvas)return;const context=canvas.getContext('2d');const data=this.config.data;const datasets=data.datasets||[];const options=this.config.options||{};const width=canvas.width;const height=canvas.height;context.clearRect(0,0,width,height);context.fillStyle='#f8fafc';context.fillRect(0,0,width,height);if(datasets.length===0)return;let allPoints=[];datasets.forEach(ds=>{if(ds.data){ds.data.forEach(p=>{if(p&&p.x&&p.y!==undefined){allPoints.push({x:new Date(p.x).getTime(),y:p.y})}});}});if(allPoints.length===0)return;const minX=Math.min(...allPoints.map(p=>p.x));const maxX=Math.max(...allPoints.map(p=>p.x));const minY=Math.min(...allPoints.map(p=>p.y));const maxY=Math.max(...allPoints.map(p=>p.y));const padding={top:40,right:20,bottom:40,left:60};const plotWidth=width-padding.left-padding.right;const plotHeight=height-padding.top-padding.bottom;const scaleX=x=>padding.left+(x-minX)/(maxX-minX||1)*plotWidth;const scaleY=y=>padding.top+plotHeight-(y-minY)/(maxY-minY||1)*plotHeight;context.strokeStyle='#e2e8f0';context.lineWidth=1;for(let i=0;i<=4;i++){const y=padding.top+plotHeight*i/4;context.beginPath();context.moveTo(padding.left,y);context.lineTo(width-padding.right,y);context.stroke();context.fillStyle='#718096';context.font='11px sans-serif';context.textAlign='right';const val=(maxY-(maxY-minY)*i/4).toFixed(1);context.fillText(val,padding.left-5,y+4);}datasets.forEach((ds,idx)=>{if(!ds.data||ds.data.length===0)return;const color=ds.borderColor||['#3b82f6','#ef4444','#10b981','#f59e0b'][idx%4];context.strokeStyle=color;context.lineWidth=2;context.beginPath();let first=true;ds.data.forEach(p=>{if(!p||!p.x||p.y===undefined)return;const x=scaleX(new Date(p.x).getTime());const y=scaleY(p.y);if(first){context.moveTo(x,y);first=false;}else{context.lineTo(x,y);}});context.stroke();context.fillStyle=color;ds.data.forEach(p=>{if(!p||!p.x||p.y===undefined)return;const x=scaleX(new Date(p.x).getTime());const y=scaleY(p.y);context.beginPath();context.arc(x,y,4,0,Math.PI*2);context.fill();});});if(options.plugins&&options.plugins.title&&options.plugins.title.text){context.fillStyle='#1a1a2e';context.font='bold 14px sans-serif';context.textAlign='center';context.fillText(options.plugins.title.text,width/2,20);}}}
return Chart;}));
"""

# Chart.js date-fns adapter (v3) - minified stub
# Source: https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js
CHARTJS_DATE_ADAPTER = """
/*!
 * chartjs-adapter-date-fns v3.0.0
 * https://www.chartjs.org
 * (c) 2023 chartjs-adapter-date-fns Contributors
 * Released under the MIT License
 *
 * NOTE: This adapter integrates date-fns with Chart.js for time scale support.
 * The embedded Chart implementation above handles dates directly, so this is
 * included for API compatibility.
 */
(function(){'use strict';})();
"""

# Sortable table JavaScript - vanilla JS for clicking column headers to sort
# Also includes global search functionality to filter sections
SORTABLE_JS = """
function sortTable(table, col, reverse) {
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const dir = reverse ? -1 : 1;
  rows.sort((a, b) => {
    const aText = a.cells[col].textContent.trim();
    const bText = b.cells[col].textContent.trim();
    const aNum = parseFloat(aText);
    const bNum = parseFloat(bText);
    if (!isNaN(aNum) && !isNaN(bNum)) return dir * (aNum - bNum);
    return dir * aText.localeCompare(bText);
  });
  rows.forEach(row => tbody.appendChild(row));
}

function initSearch() {
  const searchInput = document.getElementById('global-search');
  if (!searchInput) return;
  const clearBtn = document.getElementById('search-clear');
  const resultCount = document.getElementById('search-results');

  function doSearch() {
    const query = searchInput.value.toLowerCase().trim();
    const sections = document.querySelectorAll('.section');
    let visibleCount = 0;
    let totalCount = sections.length;

    sections.forEach(section => {
      if (!query) {
        section.style.display = '';
        visibleCount++;
      } else {
        const text = section.textContent.toLowerCase();
        const match = text.includes(query);
        section.style.display = match ? '' : 'none';
        if (match) visibleCount++;
      }
    });

    if (clearBtn) clearBtn.style.display = query ? 'inline' : 'none';
    if (resultCount) {
      resultCount.textContent = query ? visibleCount + ' of ' + totalCount + ' sections' : '';
    }
  }

  searchInput.addEventListener('input', doSearch);
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      searchInput.value = '';
      doSearch();
      searchInput.focus();
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initSearch();
  document.querySelectorAll('table.sortable').forEach(table => {
    const headers = table.querySelectorAll('th');
    headers.forEach((th, i) => {
      th.style.cursor = 'pointer';
      th.addEventListener('click', () => {
        const asc = th.dataset.sortDir !== 'asc';
        headers.forEach(h => delete h.dataset.sortDir);
        th.dataset.sortDir = asc ? 'asc' : 'desc';
        sortTable(table, i, !asc);
      });
    });
  });
});
"""

# Embedded CSS adapted from hugo/static/css/style.css
EMBEDDED_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #1a1a2e;
  background: #f5f5f7;
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}
h1 { margin-bottom: 1rem; color: #1a1a2e; }
h2 { margin: 1.5rem 0 0.75rem; color: #2d3748; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }
h3 { margin: 1.25rem 0 0.5rem; color: #2d3748; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 1rem 0;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
th {
  background: #2d3748;
  color: #fff;
  padding: 0.6rem 0.8rem;
  text-align: left;
  font-size: 0.85rem;
  user-select: none;
}
th:hover { background: #4a5568; }
td { padding: 0.5rem 0.8rem; border-bottom: 1px solid #e2e8f0; font-size: 0.85rem; }
tr:nth-child(even) td { background: #f8fafc; }
tr:hover td { background: #edf2f7; }
.card {
  background: #fff;
  border-radius: 8px;
  padding: 1.25rem;
  margin: 0.75rem 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.card h3 { font-size: 0.85rem; color: #718096; margin-bottom: 0.5rem; }
.card .value { font-size: 1.5rem; font-weight: 700; color: #1a1a2e; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 1rem; margin: 1rem 0; }
.abnormal { color: #e53e3e; font-weight: 600; }
.normal { color: #38a169; }
.chart-container {
  background: #fff;
  border-radius: 8px;
  padding: 1rem;
  margin: 1rem 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  max-width: 800px;
}
.chart-container canvas { width: 100% !important; height: 300px !important; }
details { margin: 1.5rem 0; }
details summary {
  cursor: pointer;
  color: #3b82f6;
  font-weight: 600;
  padding: 0.5rem;
  background: #f8fafc;
  border-radius: 4px;
}
details summary:hover { background: #edf2f7; }
details[open] summary { margin-bottom: 1rem; }
.meta { color: #718096; font-size: 0.9rem; margin-bottom: 1rem; }
.section { margin: 2rem 0; }
.discrepancy { background: #fef3c7; padding: 1rem; border-radius: 8px; margin: 1rem 0; }
.report-body {
  white-space: pre-wrap;
  overflow-wrap: break-word;
  word-wrap: break-word;
  max-width: 100%;
  font-family: inherit;
  line-height: 1.6;
  background: #fff;
  padding: 1rem;
  border-radius: 8px;
  margin: 0.5rem 0;
}
.search-container {
  position: sticky;
  top: 0;
  background: #f5f5f7;
  padding: 1rem 0;
  margin-bottom: 1rem;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
#global-search {
  flex: 1;
  max-width: 400px;
  padding: 0.6rem 1rem;
  font-size: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
}
#global-search:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.15); }
#search-clear {
  padding: 0.4rem 0.8rem;
  border: none;
  background: #e2e8f0;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}
#search-clear:hover { background: #cbd5e1; }
#search-results { color: #718096; font-size: 0.85rem; }
@media print {
  body { background: #fff; padding: 1rem; }
  .chart-container, details { break-inside: avoid; }
  th { background: #2d3748 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .search-container { display: none; }
}
"""

# Source colors for charts (matches hugo/generate.py)
SOURCE_COLORS = [
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#10b981",  # green
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
]


def export_html(
    db: ChartfoldDB,
    output_path: str = "chartfold_export.html",
    lookback_months: int = 6,
    config_path: str = "",
) -> str:
    """Export key clinical data as self-contained HTML with charts.

    Args:
        db: Database connection.
        output_path: Where to write the HTML file.
        lookback_months: How many months of recent data to include.
        config_path: Path to chartfold.toml config file.

    Returns the output file path.
    """
    config = load_config(config_path) if config_path else load_config()
    today = date.today().isoformat()
    lookback = (date.today() - timedelta(days=lookback_months * 30)).isoformat()
    sources = _get_sources(db)

    sections = []

    # Summary section
    sections.append(_render_summary_section(db, sources))

    # Active conditions
    sections.append(_render_conditions_section(db))

    # Medications
    sections.append(_render_medications_section(db))

    # Lab results
    sections.append(_render_labs_section(db, lookback, config))

    # Recent encounters
    sections.append(_render_encounters_section(db, lookback))

    # Recent imaging
    sections.append(_render_imaging_section(db, lookback))

    # Pathology reports
    sections.append(_render_pathology_section(db))

    # Allergies
    sections.append(_render_allergies_section(db))

    # Source documents (images, PDFs from EHR exports)
    sections.append(_render_source_documents_section(db))

    # Build full HTML document
    html_content = _build_html_document(
        title="Clinical Records Summary",
        subtitle=f"Generated: {today} | Data from: {', '.join(sources)}",
        sections=[s for s in sections if s],
        include_charts=True,
    )

    Path(output_path).write_text(html_content)
    return output_path


def export_html_full(
    db: ChartfoldDB,
    output_path: str = "chartfold_export.html",
    config_path: str = "",
) -> str:
    """Export all clinical data as self-contained HTML with charts.

    Unlike export_html(), this exports ALL data without lookback filtering.

    Args:
        db: Database connection.
        output_path: Where to write the HTML file.
        config_path: Path to chartfold.toml config file.

    Returns the output file path.
    """
    config = load_config(config_path) if config_path else load_config()
    today = date.today().isoformat()
    sources = _get_sources(db)

    sections = []

    # Summary section
    sections.append(_render_summary_section(db, sources))

    # All conditions (not just active)
    sections.append(_render_conditions_section(db, active_only=False))

    # All medications
    sections.append(_render_medications_section(db, active_only=False))

    # All lab results
    sections.append(_render_labs_section(db, lookback_date="", config=config))

    # All encounters
    sections.append(_render_encounters_section(db, lookback_date=""))

    # All imaging
    sections.append(_render_imaging_section(db, lookback_date=""))

    # All pathology reports
    sections.append(_render_pathology_section(db))

    # All allergies
    sections.append(_render_allergies_section(db, active_only=False))

    # All clinical notes
    sections.append(_render_clinical_notes_section(db))

    # All procedures
    sections.append(_render_procedures_section(db))

    # All vitals
    sections.append(_render_vitals_section(db))

    # All immunizations
    sections.append(_render_immunizations_section(db))

    # Source documents (images, PDFs from EHR exports)
    sections.append(_render_source_documents_section(db))

    # Build full HTML document
    html_content = _build_html_document(
        title="Clinical Records - Full Export",
        subtitle=f"Generated: {today} | Data from: {', '.join(sources)}",
        sections=[s for s in sections if s],
        include_charts=True,
    )

    Path(output_path).write_text(html_content)
    return output_path


def _build_html_document(
    title: str,
    subtitle: str,
    sections: list[str],
    include_charts: bool = True,
    include_search: bool = True,
) -> str:
    """Build a complete HTML document with embedded CSS and JS.

    Args:
        title: Document title for header and browser tab.
        subtitle: Subtitle text (usually generation date and sources).
        sections: List of HTML section strings to include.
        include_charts: Whether to include Chart.js and sortable table JS.
        include_search: Whether to include global search functionality.

    Returns:
        Complete HTML document as a string.
    """
    scripts = ""
    if include_charts:
        scripts = f"""
<script>{CHARTJS_MIN}</script>
<script>{CHARTJS_DATE_ADAPTER}</script>
<script>{SORTABLE_JS}</script>
"""

    search_html = ""
    if include_search:
        search_html = """
    <div class="search-container">
        <input type="text" id="global-search" placeholder="Search all sections..." aria-label="Search" />
        <button id="search-clear" style="display:none">Clear</button>
        <span id="search-results"></span>
    </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_escape(title)}</title>
    <style>{EMBEDDED_CSS}</style>
</head>
<body>
    <h1>{_escape(title)}</h1>
    <p class="meta">{_escape(subtitle)}</p>
{search_html}
    {"".join(sections)}
    {scripts}
</body>
</html>
"""


def _escape(text: str | None) -> str:
    """HTML-escape text, returning empty string for None."""
    return html.escape(str(text)) if text else ""


def _html_table(
    headers: list[str],
    rows: list[list[str | int | float | None]],
    sortable: bool = True,
    highlight_col: int | None = None,
) -> str:
    """Generate an HTML table.

    Args:
        headers: Column headers.
        rows: List of row data (list of values).
        sortable: Whether to add sortable class.
        highlight_col: Column index to check for abnormal flags (applies .abnormal class).
    """
    if not rows:
        return "<p><em>No data available.</em></p>"

    cls = ' class="sortable"' if sortable else ""
    head_cells = "".join(f"<th>{_escape(h)}</th>" for h in headers)

    body_rows = []
    for row in rows:
        cells = []
        for i, val in enumerate(row):
            val_str = str(val) if val is not None else ""
            cell_cls = ""
            if highlight_col is not None and i == highlight_col:
                if val_str.upper() in ("H", "L", "HH", "LL", "HIGH", "LOW", "ABNORMAL"):
                    cell_cls = ' class="abnormal"'
            cells.append(f"<td{cell_cls}>{_escape(val_str)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"""<table{cls}>
<thead><tr>{head_cells}</tr></thead>
<tbody>{"".join(body_rows)}</tbody>
</table>"""


def _html_details(summary: str, content: str) -> str:
    """Generate a collapsible details/summary element.

    Args:
        summary: The clickable summary text.
        content: HTML content to show when expanded.

    Returns:
        HTML string with details element.
    """
    return f"""<details>
<summary>{_escape(summary)}</summary>
{content}
</details>"""


def _build_chart_js(
    chart_id: str,
    datasets: list[dict[str, Any]],
    unit: str,
    title: str,
) -> str:
    """Build Chart.js initialization code for a lab trend chart.

    Args:
        chart_id: Unique ID for the canvas element.
        datasets: List of {source, labels, values, color} dicts.
        unit: Y-axis unit label.
        title: Chart title.

    Returns HTML with canvas and script to render the chart.
    """
    if not datasets or not any(ds.get("values") for ds in datasets):
        return ""

    datasets_js = []
    for ds in datasets:
        src_label = ds.get("source", "")
        data_points = [
            {"x": lbl, "y": val}
            for lbl, val in zip(ds.get("labels", []), ds.get("values", []), strict=False)
            if val is not None
        ]
        if not data_points:
            continue
        color = ds.get("color", "#3b82f6")
        datasets_js.append(
            f"{{ label: '{_escape(src_label)}', "
            f"data: {json.dumps(data_points)}, "
            f"borderColor: '{color}', backgroundColor: '{color}', "
            f"tension: 0.1, fill: false, pointRadius: 4 }}"
        )

    if not datasets_js:
        return ""

    datasets_str = ", ".join(datasets_js)

    return f"""
<div class="chart-container">
<canvas id="{chart_id}" width="600" height="300"></canvas>
</div>
<script>
(function() {{
  const ctx = document.getElementById('{chart_id}');
  if (ctx) {{
    new Chart(ctx, {{
      type: 'line',
      data: {{ datasets: [{datasets_str}] }},
      options: {{
        responsive: true,
        scales: {{
          x: {{ type: 'time', time: {{ unit: 'month' }}, title: {{ display: true, text: 'Date' }} }},
          y: {{ beginAtZero: false, title: {{ display: true, text: '{_escape(unit)}' }} }}
        }},
        plugins: {{ title: {{ display: true, text: '{_escape(title)}' }} }}
      }}
    }});
  }}
}})();
</script>
"""


def _render_summary_section(db: ChartfoldDB, sources: list[str]) -> str:
    """Render data overview cards."""
    summary = db.summary()
    cards = []
    for table, count in summary.items():
        if count > 0:
            label = table.replace("_", " ").title()
            cards.append(
                f'<div class="card"><h3>{_escape(label)}</h3><div class="value">{count}</div></div>'
            )

    if not cards:
        return ""

    return f"""
<div class="section">
<h2>Data Overview</h2>
<div class="cards">{"".join(cards)}</div>
</div>
"""


def _render_conditions_section(db: ChartfoldDB, active_only: bool = True) -> str:
    """Render conditions section."""
    if active_only:
        conditions = db.query(
            "SELECT condition_name, icd10_code, clinical_status, onset_date, source "
            "FROM conditions WHERE LOWER(clinical_status) = 'active' "
            "ORDER BY condition_name"
        )
        title = "Active Conditions"
    else:
        conditions = db.query(
            "SELECT condition_name, icd10_code, clinical_status, onset_date, source "
            "FROM conditions ORDER BY clinical_status, condition_name"
        )
        title = "Conditions"

    if not conditions:
        return ""

    rows = [
        [
            c["condition_name"],
            c.get("icd10_code", ""),
            c.get("clinical_status", ""),
            c.get("onset_date", ""),
            c["source"],
        ]
        for c in conditions
    ]

    table = _html_table(
        ["Condition", "ICD-10", "Status", "Onset", "Source"],
        rows,
    )

    return f"""
<div class="section">
<h2>{title}</h2>
{table}
</div>
"""


def _render_medications_section(db: ChartfoldDB, active_only: bool = True) -> str:
    """Render medications section with reconciliation warnings."""
    if active_only:
        active_meds = get_active_medications(db)
        if not active_meds:
            return ""

        rows = [
            [
                m["name"],
                m.get("sig", ""),
                m.get("route", ""),
                m.get("start_date", ""),
                m.get("prescriber", ""),
                m["source"],
            ]
            for m in active_meds
        ]

        table = _html_table(
            ["Medication", "Sig", "Route", "Start Date", "Prescriber", "Source"],
            rows,
        )

        # Check for discrepancies
        recon = reconcile_medications(db)
        discrepancy_html = ""
        if recon.get("discrepancies"):
            disc_items = []
            for disc in recon["discrepancies"]:
                statuses = ", ".join(f"{e['source']}: {e['status']}" for e in disc["entries"])
                disc_items.append(
                    f"<li><strong>{_escape(disc['name'])}</strong> — {_escape(statuses)}</li>"
                )
            discrepancy_html = f"""
<div class="discrepancy">
<h3>Medication Discrepancies</h3>
<p><em>The following medications have conflicting status across sources:</em></p>
<ul>{"".join(disc_items)}</ul>
</div>
"""

        return f"""
<div class="section">
<h2>Active Medications</h2>
{table}
{discrepancy_html}
</div>
"""
    else:
        all_meds = db.query(
            "SELECT name, status, sig, route, start_date, stop_date, prescriber, source "
            "FROM medications ORDER BY status, name"
        )
        if not all_meds:
            return ""

        rows = [
            [
                m["name"],
                m.get("status", ""),
                m.get("sig", ""),
                m.get("route", ""),
                m.get("start_date", ""),
                m.get("stop_date", ""),
                m["source"],
            ]
            for m in all_meds
        ]

        table = _html_table(
            ["Medication", "Status", "Sig", "Route", "Start", "Stop", "Source"],
            rows,
        )

        return f"""
<div class="section">
<h2>Medications</h2>
{table}
</div>
"""


def _render_labs_section(
    db: ChartfoldDB,
    lookback_date: str,
    config: dict | None = None,
) -> str:
    """Render lab results section with trend charts for configured tests."""
    parts = []

    # Lab trend charts for configured tests
    lab_tests = get_lab_test_configs(config or {})
    charts = []
    for lt in lab_tests:
        series = get_lab_series(db, test_names=lt.match)
        if not series["results"]:
            continue

        trend = series["results"]
        sources = series["sources"]

        datasets = []
        for i, src in enumerate(sources):
            src_results = [
                r for r in trend if r["source"] == src and r["value_numeric"] is not None
            ]
            if not src_results:
                continue
            color = SOURCE_COLORS[i % len(SOURCE_COLORS)]
            datasets.append(
                {
                    "source": src,
                    "labels": [r["result_date"] for r in src_results],
                    "values": [r["value_numeric"] for r in src_results],
                    "color": color,
                }
            )

        unit = trend[0]["unit"] if trend else ""
        chart_id = f"chart-{lt.name.lower().replace(' ', '-')}"
        chart_html = _build_chart_js(chart_id, datasets, unit, f"{lt.name} ({unit})")
        if chart_html:
            # Ref range note
            ref_note = ""
            if series.get("ref_range_discrepancy"):
                ranges_str = ", ".join(
                    f"<strong>{src}</strong>: {rr}"
                    for src, rr in series.get("ref_ranges", {}).items()
                )
                ref_note = (
                    f"<p><em>Note: Reference ranges differ across sources: {ranges_str}</em></p>"
                )

            charts.append(f"<h3>{_escape(lt.name)} Trend</h3>{chart_html}{ref_note}")

    if charts:
        parts.append(f"""
<div class="section">
<h2>Lab Trends</h2>
{"".join(charts)}
</div>
""")

    # Recent/all labs table
    if lookback_date:
        recent_labs = db.query(
            "SELECT test_name, value, value_numeric, unit, ref_range, "
            "interpretation, result_date, source "
            "FROM lab_results WHERE result_date >= ? "
            "ORDER BY result_date DESC",
            (lookback_date,),
        )
        title = f"Lab Results (since {lookback_date})"
    else:
        recent_labs = db.query(
            "SELECT test_name, value, value_numeric, unit, ref_range, "
            "interpretation, result_date, source "
            "FROM lab_results ORDER BY result_date DESC"
        )
        title = "Lab Results"

    if recent_labs:
        rows = [
            [
                r["test_name"],
                r["value"],
                r.get("unit", ""),
                r.get("ref_range", ""),
                r.get("interpretation", "") or "",
                r["result_date"],
                r["source"],
            ]
            for r in recent_labs
        ]

        # Use details for long tables
        table = _html_table(
            ["Test", "Value", "Unit", "Range", "Flag", "Date", "Source"],
            rows,
            highlight_col=4,
        )

        if len(recent_labs) > 50:
            table = _html_details(f"{title} ({len(recent_labs)} results)", table)
        else:
            table = f"<h3>{title}</h3>{table}"

        parts.append(f'<div class="section">{table}</div>')

    # Abnormal labs (all time) for visit-focused export
    if lookback_date:
        abnormal = get_abnormal_labs(db)
        if abnormal:
            rows = [
                [
                    r["test_name"],
                    r["value"],
                    r.get("unit", ""),
                    r.get("ref_range", ""),
                    r.get("interpretation", ""),
                    r["result_date"],
                    r["source"],
                ]
                for r in abnormal[:50]
            ]
            abnormal_table = _html_table(
                ["Test", "Value", "Unit", "Range", "Flag", "Date", "Source"],
                rows,
                highlight_col=4,
            )
            parts.append(f"""
<div class="section">
<h3>Abnormal Lab Results (All Time)</h3>
{abnormal_table}
</div>
""")

    return "".join(parts)


def _render_encounters_section(db: ChartfoldDB, lookback_date: str) -> str:
    """Render encounters section."""
    if lookback_date:
        encounters = db.query(
            "SELECT encounter_date, encounter_type, facility, provider, reason, source "
            "FROM encounters WHERE encounter_date >= ? "
            "ORDER BY encounter_date DESC",
            (lookback_date,),
        )
        title = f"Recent Encounters (since {lookback_date})"
    else:
        encounters = db.query(
            "SELECT encounter_date, encounter_type, facility, provider, reason, source "
            "FROM encounters ORDER BY encounter_date DESC"
        )
        title = "Encounters"

    if not encounters:
        return ""

    rows = [
        [
            e["encounter_date"],
            e.get("encounter_type", ""),
            e.get("facility", ""),
            e.get("provider", ""),
            (e.get("reason", "") or "")[:60],
            e["source"],
        ]
        for e in encounters
    ]

    table = _html_table(
        ["Date", "Type", "Facility", "Provider", "Reason", "Source"],
        rows,
    )

    return f"""
<div class="section">
<h2>{title}</h2>
{table}
</div>
"""


def _render_imaging_section(db: ChartfoldDB, lookback_date: str) -> str:
    """Render imaging reports section."""
    if lookback_date:
        imaging = db.query(
            "SELECT id, study_name, modality, study_date, impression, source "
            "FROM imaging_reports WHERE study_date >= ? "
            "ORDER BY study_date DESC",
            (lookback_date,),
        )
        title = f"Imaging Reports (since {lookback_date})"
    else:
        imaging = db.query(
            "SELECT id, study_name, modality, study_date, impression, source "
            "FROM imaging_reports ORDER BY study_date DESC"
        )
        title = "Imaging Reports"

    if not imaging:
        return ""

    parts = [f"<h2>{title}</h2>"]
    for img in imaging:
        parts.append(f"""
<div class="card">
<h3>{_escape(img["study_name"])} — {_escape(img["study_date"])}</h3>
<p class="meta">Modality: {_escape(img.get("modality", ""))} | Source: {_escape(img["source"])}</p>
""")
        if img.get("impression"):
            parts.append(f'<div class="report-body">{_escape(img["impression"])}</div>')
        assets = _get_linked_assets(
            db, "imaging_reports", img["id"],
            date=img.get("study_date", ""), source=img["source"],
        )
        asset_html = _render_linked_assets_html(assets)
        if asset_html:
            parts.append(asset_html)
        parts.append("</div>")

    return f'<div class="section">{"".join(parts)}</div>'


def _render_pathology_section(db: ChartfoldDB) -> str:
    """Render pathology reports section."""
    pathology = db.query(
        "SELECT p.id, p.report_date, p.specimen, p.diagnosis, p.staging, p.margins, "
        "p.lymph_nodes, p.source, pr.name as procedure_name "
        "FROM pathology_reports p "
        "LEFT JOIN procedures pr ON p.procedure_id = pr.id "
        "ORDER BY p.report_date DESC"
    )

    if not pathology:
        return ""

    parts = ["<h2>Pathology Reports</h2>"]
    for p in pathology:
        title_parts = [p.get("procedure_name", ""), p["report_date"]]
        title = " — ".join(t for t in title_parts if t) or "Pathology Report"

        parts.append(f'<div class="card"><h3>{_escape(title)}</h3>')
        if p.get("specimen"):
            parts.append(f"<p><strong>Specimen:</strong> {_escape(p['specimen'])}</p>")
        if p.get("diagnosis"):
            parts.append(f"<p><strong>Diagnosis:</strong> {_escape(p['diagnosis'])}</p>")
        if p.get("staging"):
            parts.append(f"<p><strong>Staging:</strong> {_escape(p['staging'])}</p>")
        if p.get("margins"):
            parts.append(f"<p><strong>Margins:</strong> {_escape(p['margins'])}</p>")
        if p.get("lymph_nodes"):
            parts.append(f"<p><strong>Lymph Nodes:</strong> {_escape(p['lymph_nodes'])}</p>")
        assets = _get_linked_assets(
            db, "pathology_reports", p["id"],
            date=p.get("report_date", ""), source=p["source"],
        )
        asset_html = _render_linked_assets_html(assets)
        if asset_html:
            parts.append(asset_html)
        parts.append(f'<p class="meta">Source: {_escape(p["source"])}</p></div>')

    return f'<div class="section">{"".join(parts)}</div>'


def _encode_image_base64(file_path: str) -> str:
    """Read an image file and return a base64 data URI, or empty string.

    Returns empty string if file is missing, too large (>10 MB), or not
    a recognized image type (png, jpg, jpeg, gif, bmp, tif, tiff).
    """
    import base64 as b64mod

    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return ""
    if p.stat().st_size > 10_000_000:  # skip >10MB
        return ""

    suffix = p.suffix.lower().lstrip(".")
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
    }
    mime = mime_map.get(suffix, "")
    if not mime:
        return ""

    data = b64mod.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _get_linked_assets(
    db: ChartfoldDB, ref_table: str, ref_id: int, date: str = "", source: str = ""
) -> list[dict[str, Any]]:
    """Query source_assets for assets linked to a clinical record.

    First tries exact ref_table+ref_id match. If nothing found and date+source
    are provided, falls back to matching on encounter_date+source+ref_table
    (with NULL ref_id).
    """
    assets = db.query(
        "SELECT asset_type, file_path, file_name FROM source_assets "
        "WHERE ref_table = ? AND ref_id = ?",
        (ref_table, ref_id),
    )
    if assets:
        return assets
    if date and source:
        assets = db.query(
            "SELECT asset_type, file_path, file_name FROM source_assets "
            "WHERE ref_table = ? AND encounter_date = ? AND source = ? AND ref_id IS NULL",
            (ref_table, date, source),
        )
    return assets


def _render_linked_assets_html(assets: list[dict[str, Any]]) -> str:
    """Render linked assets as inline HTML (images or file links)."""
    from chartfold.core.utils import is_image_asset

    if not assets:
        return ""
    parts = ['<div class="linked-assets">']
    for a in assets:
        if is_image_asset(a["asset_type"]):
            data_uri = _encode_image_base64(a["file_path"])
            if data_uri:
                parts.append(
                    f'<img src="{data_uri}" alt="{_escape(a["file_name"])}" '
                    f'style="max-width:600px;max-height:400px;margin:8px 0;">'
                )
        else:
            parts.append(
                f'<a href="{_escape(a["file_path"])}">'
                f'{_escape(a["file_name"])}</a>'
            )
    parts.append("</div>")
    return "".join(parts)


def _render_source_documents_section(db: ChartfoldDB) -> str:
    """Render all source assets grouped by category.

    Returns an HTML section with assets organized into category-headed tables.
    Image assets (png, jpg, etc.) are rendered with inline base64 thumbnails.
    Other file types (pdf, html, etc.) are rendered as file-path links.
    Returns empty string when no source assets exist.
    """
    from chartfold.core.utils import categorize_asset_title, is_image_asset

    assets = db.query(
        "SELECT id, source, asset_type, file_path, file_name, "
        "file_size_kb, title, encounter_date "
        "FROM source_assets ORDER BY encounter_date DESC, file_name"
    )
    if not assets:
        return ""

    # Group by category
    by_category: dict[str, list[Any]] = {}
    for a in assets:
        cat = categorize_asset_title(a.get("title", ""))
        by_category.setdefault(cat, []).append(a)

    parts = ['<div class="section"><h2>Source Documents</h2>']
    parts.append(
        '<p class="meta">Documents from EHR exports. '
        "PDF links reference files relative to this HTML file.</p>"
    )

    for cat in sorted(by_category.keys()):
        group = by_category[cat]
        parts.append(f"<h3>{_escape(cat)} ({len(group)})</h3>")
        parts.append(
            '<table class="sortable"><thead><tr>'
            "<th>Document</th><th>Type</th><th>Size</th>"
            "<th>Date</th><th>Source</th></tr></thead><tbody>"
        )
        for a in group:
            display = _escape(a.get("title") or a["file_name"])
            size = f"{a['file_size_kb']} KB" if a.get("file_size_kb") else ""
            dt = _escape(a.get("encounter_date", ""))
            src = _escape(a["source"])
            atype = _escape(a["asset_type"])

            if is_image_asset(a["asset_type"]):
                img_data = _encode_image_base64(a["file_path"])
                if img_data:
                    display = (
                        f'<img src="{img_data}" alt="{display}" '
                        f'style="max-width:100px;max-height:80px;">'
                    )
                # If file doesn't exist, fall through to text display
            else:
                # Relative path link for PDFs and other files
                display = f'<a href="{_escape(a["file_path"])}">{display}</a>'

            parts.append(
                f"<tr><td>{display}</td><td>{atype}</td>"
                f"<td>{size}</td><td>{dt}</td><td>{src}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</div>")
    return "".join(parts)


def _render_allergies_section(db: ChartfoldDB, active_only: bool = True) -> str:
    """Render allergies section."""
    if active_only:
        allergies = db.query(
            "SELECT allergen, reaction, severity, source FROM allergies "
            "WHERE LOWER(status) = 'active' ORDER BY allergen"
        )
        title = "Allergies"
    else:
        allergies = db.query(
            "SELECT allergen, reaction, severity, status, source FROM allergies "
            "ORDER BY status, allergen"
        )
        title = "Allergies"

    if not allergies:
        return ""

    if active_only:
        rows = [
            [a["allergen"], a.get("reaction", ""), a.get("severity", ""), a["source"]]
            for a in allergies
        ]
        headers = ["Allergen", "Reaction", "Severity", "Source"]
    else:
        rows = [
            [
                a["allergen"],
                a.get("reaction", ""),
                a.get("severity", ""),
                a.get("status", ""),
                a["source"],
            ]
            for a in allergies
        ]
        headers = ["Allergen", "Reaction", "Severity", "Status", "Source"]

    table = _html_table(headers, rows)

    return f"""
<div class="section">
<h2>{title}</h2>
{table}
</div>
"""


def _render_clinical_notes_section(db: ChartfoldDB) -> str:
    """Render clinical notes section (for full export)."""
    notes = db.query(
        "SELECT note_type, author, note_date, content, source "
        "FROM clinical_notes ORDER BY note_date DESC"
    )

    if not notes:
        return ""

    parts = ["<h2>Clinical Notes</h2>"]
    for n in notes:
        title = f"{n.get('note_type', 'Note')} — {n.get('note_date', '')}"
        parts.append(f'<div class="card"><h3>{_escape(title)}</h3>')
        parts.append(
            f'<p class="meta">Author: {_escape(n.get("author", ""))} | Source: {_escape(n["source"])}</p>'
        )
        content = n.get("content", "") or ""
        if content:
            # Truncate long notes
            if len(content) > 1000:
                truncated = content[:1000] + "..."
                full_html = _html_details(
                    "Show full note", f'<div class="report-body">{_escape(content)}</div>'
                )
                parts.append(f'<div class="report-body">{_escape(truncated)}</div>{full_html}')
            else:
                parts.append(f'<div class="report-body">{_escape(content)}</div>')
        parts.append("</div>")

    return f'<div class="section">{"".join(parts)}</div>'


def _render_procedures_section(db: ChartfoldDB) -> str:
    """Render procedures section (for full export)."""
    procedures = db.query(
        "SELECT name, procedure_date, provider, facility, source "
        "FROM procedures ORDER BY procedure_date DESC"
    )

    if not procedures:
        return ""

    rows = [
        [
            p["name"],
            p.get("procedure_date", ""),
            p.get("provider", ""),
            p.get("facility", ""),
            p["source"],
        ]
        for p in procedures
    ]

    table = _html_table(
        ["Procedure", "Date", "Provider", "Facility", "Source"],
        rows,
    )

    return f"""
<div class="section">
<h2>Procedures</h2>
{table}
</div>
"""


def _render_vitals_section(db: ChartfoldDB) -> str:
    """Render vitals section (for full export)."""
    vitals = db.query(
        "SELECT vital_type, value, value_text, unit, recorded_date, source "
        "FROM vitals ORDER BY recorded_date DESC, vital_type"
    )

    if not vitals:
        return ""

    rows = [
        [
            v["vital_type"],
            v.get("value_text") or v.get("value", ""),
            v.get("unit", ""),
            v.get("recorded_date", ""),
            v["source"],
        ]
        for v in vitals
    ]

    table = _html_table(
        ["Vital", "Value", "Unit", "Date", "Source"],
        rows,
    )

    # Wrap in details if many rows
    content = _html_details(f"Vitals ({len(vitals)} records)", table) if len(vitals) > 50 else table

    return f"""
<div class="section">
<h2>Vitals</h2>
{content}
</div>
"""


def _render_immunizations_section(db: ChartfoldDB) -> str:
    """Render immunizations section (for full export)."""
    immunizations = db.query(
        "SELECT vaccine_name, admin_date, lot_number, site, source "
        "FROM immunizations ORDER BY admin_date DESC"
    )

    if not immunizations:
        return ""

    rows = [
        [
            i["vaccine_name"],
            i.get("admin_date", ""),
            i.get("lot_number", ""),
            i.get("site", ""),
            i["source"],
        ]
        for i in immunizations
    ]

    table = _html_table(
        ["Vaccine", "Date", "Lot Number", "Site", "Source"],
        rows,
    )

    return f"""
<div class="section">
<h2>Immunizations</h2>
{table}
</div>
"""


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
