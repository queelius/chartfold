"""Markdown output formatter for extracted clinical data."""

from collections import defaultdict


class MarkdownWriter:
    """Builds markdown output incrementally."""

    def __init__(self):
        self._lines: list[str] = []

    def w(self, line: str = "") -> None:
        self._lines.append(line)

    def heading(self, text: str, level: int = 2) -> None:
        self.w(f"{'#' * level} {text}")
        self.w()

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        self.w("| " + " | ".join(headers) + " |")
        self.w("|" + "|".join("---" for _ in headers) + "|")
        for row in rows:
            self.w("| " + " | ".join(str(c) for c in row) + " |")
        self.w()

    def separator(self) -> None:
        self.w("---")
        self.w()

    def text(self) -> str:
        return "\n".join(self._lines)

    def write_to_file(self, filepath: str) -> int:
        content = self.text()
        with open(filepath, "w") as f:
            f.write(content)
        return len(self._lines)


def format_epic_output(data: dict) -> str:
    """Format Epic extraction results as markdown."""
    md = MarkdownWriter()
    md.heading("Extracted Clinical Data — Epic MyChart Export", level=1)
    md.w()
    md.w(f"*Extracted from {len(data['inventory'])} CDA XML documents.*")
    md.w(f"*Parse errors: {len(data['errors'])}*")
    md.w()

    if data["errors"]:
        md.heading("Parse Errors")
        for err in data["errors"]:
            md.w(f"- **{err['doc_id']}**: {err['error']}")
        md.w()

    # Document Inventory
    md.separator()
    md.heading("1. Document Inventory")
    md.table(
        ["Doc ID", "Date", "Title", "Size", "Key Sections"],
        [
            [
                inv["doc_id"],
                inv["date"],
                inv["title"],
                f"{inv['size_kb']}KB",
                ", ".join(
                    s
                    for s in inv["sections"]
                    if s
                    not in (
                        "Allergies",
                        "Immunizations",
                        "Social History",
                        "Last Filed Vital Signs",
                        "Insurance",
                        "Advance Directives",
                        "Care Teams",
                        "Medications",
                        "Active Problems",
                    )
                ),
            ]
            for inv in data["inventory"]
        ],
    )

    # CEA Values
    md.separator()
    md.heading("2. CEA Values (Chronological)")
    if data["cea_values"]:
        md.table(
            ["#", "Date", "CEA (ng/mL)", "Reference"],
            [
                [str(i), cea["date"], f"**{cea['value']}**", cea["ref_range"]]
                for i, cea in enumerate(data["cea_values"], 1)
            ],
        )
    else:
        md.w("*No CEA values found.*")
        md.w()

    # Lab Results
    md.separator()
    md.heading("3. Lab Results (Most Recent First)")
    labs_by_date = defaultdict(list)
    for lab in data["lab_results"]:
        labs_by_date[lab["date"]].append(lab)

    for date in sorted(labs_by_date.keys(), reverse=True):
        panels = labs_by_date[date]
        md.heading(date, level=3)
        for panel in panels:
            md.w(f"**{panel['panel']}** ({panel['time']})")
            md.w()
            if panel["components"]:
                md.table(
                    ["Component", "Value", "Reference Range"],
                    [[c["name"], c["value"], c["ref_range"]] for c in panel["components"]],
                )

    # Imaging Reports
    md.separator()
    md.heading("4. Imaging Reports (Most Recent First)")
    for img in data["imaging_reports"]:
        md.heading(f"{img['study']} — {img['date']}", level=3)
        if img["impression"]:
            md.w("**Impression:**")
            md.w()
            md.w(f"> {img['impression'][:500]}")
            md.w()

    # Pathology Reports
    md.separator()
    md.heading("5. Pathology Reports")
    for path in data["pathology_reports"]:
        md.heading(f"{path['panel']} — {path['date']}", level=3)
        if path["diagnosis"]:
            md.w("**Diagnosis:**")
            md.w()
            md.w("```")
            md.w(path["diagnosis"])
            md.w("```")
            md.w()

    # Clinical Notes
    md.separator()
    md.heading("6. Clinical Notes")
    notes_by_type = defaultdict(list)
    for note in data["clinical_notes"]:
        notes_by_type[note["section"]].append(note)

    for sec_type in sorted(notes_by_type.keys()):
        md.heading(sec_type, level=3)
        for note in sorted(notes_by_type[sec_type], key=lambda n: n["date"], reverse=True):
            md.heading(f"{note['doc_id']} — {note['date']}", level=4)
            text = note["text"]
            if len(text) > 10000:
                text = text[:10000] + "\n\n[... truncated ...]"
            md.w("```")
            md.w(text)
            md.w("```")
            md.w()

    # Medications
    md.separator()
    md.heading("7. Medications")
    if data["medications"]:
        md.w("```")
        md.w(data["medications"][:8000])
        md.w("```")
    md.w()

    # Problems
    md.separator()
    md.heading("8. Active Problems")
    if data["problems"]:
        md.w("```")
        md.w(data["problems"][:5000])
        md.w("```")
    md.w()

    # Encounter Timeline
    md.separator()
    md.heading("9. Encounter Timeline (Most Recent First)")
    md.table(
        ["Date", "Doc ID", "Key Sections", "Facility"],
        [
            [
                enc["date_fmt"],
                enc["doc_id"],
                ", ".join(enc["key_sections"][:5]),
                enc["facility"],
            ]
            for enc in data["encounter_timeline"]
        ],
    )

    return md.text()
