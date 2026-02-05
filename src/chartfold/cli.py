#!/usr/bin/env python3
"""CLI entry point for chartfold package.

Usage:
    python -m chartfold load epic <input_dir> [--db chartfold.db]
    python -m chartfold load meditech <input_dir> [--db chartfold.db]
    python -m chartfold load athena <input_dir> [--db chartfold.db]
    python -m chartfold load all --epic-dir <> --meditech-dir <> --athena-dir <> [--db ...]
    python -m chartfold query <sql> [--db chartfold.db]
    python -m chartfold summary [--db chartfold.db]
    python -m chartfold export markdown [--output FILE] [--lookback N] [--full] [--pdf]
    python -m chartfold export html [--output FILE] [--lookback N] [--full]
    python -m chartfold export json [--output FILE]
    python -m chartfold export hugo [--output DIR] [--config FILE] [--linked-sources]
    python -m chartfold serve-mcp [--db chartfold.db]
"""

import argparse
import os
import sys

DEFAULT_DB = "chartfold.db"


def main():
    parser = argparse.ArgumentParser(
        prog="chartfold",
        description="Parse, load, and query clinical records from EHR exports.",
    )
    sub = parser.add_subparsers(dest="command")

    # --- load ---
    load_parser = sub.add_parser("load", help="Load source data into SQLite")
    load_sub = load_parser.add_subparsers(dest="source")

    for src in ("epic", "meditech", "athena"):
        p = load_sub.add_parser(src, help=f"Load {src} source")
        p.add_argument("input_dir", help="Directory containing source files")
        p.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
        p.add_argument("--source-name", default="", help="Source name override (default: derived from directory)")

    auto_parser = load_sub.add_parser("auto", help="Auto-detect source type and load")
    auto_parser.add_argument("input_dir", help="Directory containing source files")
    auto_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    auto_parser.add_argument("--source-name", default="", help="Source name override (default: derived from directory)")

    all_parser = load_sub.add_parser("all", help="Load all sources at once")
    all_parser.add_argument("--epic-dir", help="Epic source directory")
    all_parser.add_argument("--meditech-dir", help="MEDITECH source directory")
    all_parser.add_argument("--athena-dir", help="athenahealth/SIHF source directory")
    all_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    all_parser.add_argument("--epic-source-name", default="", help="Epic source name override")
    all_parser.add_argument("--meditech-source-name", default="", help="MEDITECH source name override")
    all_parser.add_argument("--athena-source-name", default="", help="athena source name override")

    # --- diff ---
    diff_parser = sub.add_parser("diff", help="Show what's new since a given date")
    diff_parser.add_argument("since_date", help="ISO date (YYYY-MM-DD) — show changes since this date")
    diff_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")

    # --- query ---
    query_parser = sub.add_parser("query", help="Run SQL query against the database")
    query_parser.add_argument("sql", help="SQL query to execute")
    query_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")

    # --- summary ---
    summary_parser = sub.add_parser("summary", help="Show database summary")
    summary_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")

    # --- export (with subcommands) ---
    export_parser = sub.add_parser("export", help="Export clinical data in various formats")
    export_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    export_sub = export_parser.add_subparsers(dest="export_format")

    # Common db argument for all export subcommands
    db_help = "SQLite database path"

    # export markdown
    md_parser = export_sub.add_parser("markdown", help="Export as Markdown")
    md_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    md_parser.add_argument("--output", default="chartfold_export.md", help="Output file path")
    md_parser.add_argument("--lookback", type=int, default=6, help="Months of recent data to include")
    md_parser.add_argument("--full", action="store_true", help="Export all data (full database dump)")
    md_parser.add_argument("--pdf", action="store_true", help="Generate PDF via pandoc")
    md_parser.add_argument("--include-load-log", action="store_true", help="Include audit log in full JSON export")
    md_parser.add_argument("--exclude-notes", action="store_true", help="Exclude personal notes from full export")

    # export json (for full exports)
    json_parser = export_sub.add_parser("json", help="Export as JSON (full database dump)")
    json_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    json_parser.add_argument("--output", default="chartfold_export.json", help="Output file path")
    json_parser.add_argument("--include-load-log", action="store_true", help="Include audit log")
    json_parser.add_argument("--exclude-notes", action="store_true", help="Exclude personal notes")

    # export html
    html_parser = export_sub.add_parser("html", help="Export as self-contained HTML with charts")
    html_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    html_parser.add_argument("--output", default="chartfold_export.html", help="Output file path")
    html_parser.add_argument("--lookback", type=int, default=6, help="Months of recent data to include")
    html_parser.add_argument("--full", action="store_true", help="Export all data (full database dump)")
    html_parser.add_argument("--config", default="", help="Path to chartfold.toml config file")

    # export hugo (moved from generate-site)
    hugo_parser = export_sub.add_parser("hugo", help="Generate Hugo static site")
    hugo_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    hugo_parser.add_argument("--output", default="./site", help="Hugo output directory")
    hugo_parser.add_argument("--config", default="", help="Path to chartfold.toml config file")
    hugo_parser.add_argument("--linked-sources", action="store_true",
                             help="Copy source EHR assets into Hugo static folder")

    # --- import ---
    import_parser = sub.add_parser("import", help="Import data from JSON export")
    import_parser.add_argument("input_file", help="Path to JSON export file")
    import_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    import_parser.add_argument("--validate-only", action="store_true", help="Validate without importing")
    import_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing database")

    # --- init-config ---
    config_parser = sub.add_parser("init-config", help="Generate chartfold.toml config from database")
    config_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    config_parser.add_argument("--output", default="chartfold.toml", help="Config file output path")

    # --- notes ---
    notes_parser = sub.add_parser("notes", help="View personal notes and analyses")
    notes_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    notes_sub = notes_parser.add_subparsers(dest="notes_action")

    notes_list_parser = notes_sub.add_parser("list", help="List recent notes (default)")
    notes_list_parser.add_argument("--limit", type=int, default=20, help="Max notes to show")

    notes_search_parser = notes_sub.add_parser("search", help="Search notes")
    notes_search_parser.add_argument("--tag", default="", help="Filter by tag")
    notes_search_parser.add_argument("--query", default="", help="Text search in title/content")
    notes_search_parser.add_argument("--ref-table", default="", help="Filter by linked table")

    notes_show_parser = notes_sub.add_parser("show", help="Show full note content")
    notes_show_parser.add_argument("id", type=int, help="Note ID to display")

    # --- assets ---
    assets_parser = sub.add_parser("assets", help="View source assets (PDFs, images, etc.)")
    assets_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    assets_sub = assets_parser.add_subparsers(dest="assets_action")

    assets_summary_parser = assets_sub.add_parser("summary", help="Show asset summary by source and type (default)")

    assets_list_parser = assets_sub.add_parser("list", help="List assets")
    assets_list_parser.add_argument("--source", default="", help="Filter by source")
    assets_list_parser.add_argument("--type", default="", help="Filter by asset type (pdf, png, etc.)")
    assets_list_parser.add_argument("--limit", type=int, default=50, help="Max assets to show")

    assets_find_parser = assets_sub.add_parser("find", help="Find assets for a specific record")
    assets_find_parser.add_argument("--table", required=True, help="Clinical table name")
    assets_find_parser.add_argument("--id", type=int, required=True, help="Record ID in the table")

    # --- identify ---
    identify_parser = sub.add_parser("identify", help="Detect EHR source type of a directory")
    identify_parser.add_argument("input_dir", help="Directory to inspect")

    # --- serve-mcp ---
    mcp_parser = sub.add_parser("serve-mcp", help="Start MCP server for Claude integration")
    mcp_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "load":
        _handle_load(args)
    elif args.command == "export":
        _handle_export(args)
    elif args.command == "import":
        _handle_import(args)
    elif args.command == "diff":
        _handle_diff(args)
    elif args.command == "query":
        _handle_query(args)
    elif args.command == "summary":
        _handle_summary(args)
    elif args.command == "init-config":
        _handle_init_config(args)
    elif args.command == "notes":
        _handle_notes(args)
    elif args.command == "assets":
        _handle_assets(args)
    elif args.command == "identify":
        _handle_identify(args)
    elif args.command == "serve-mcp":
        _handle_serve_mcp(args)


def _handle_load(args):
    from chartfold.db import ChartfoldDB

    if args.source is None:
        print("Usage: chartfold load <auto|epic|meditech|athena|all> ...")
        sys.exit(1)

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.source == "auto":
            _load_auto(db, args.input_dir, getattr(args, "source_name", ""))
        elif args.source == "all":
            if args.epic_dir:
                _load_epic(db, args.epic_dir, getattr(args, "epic_source_name", ""))
            if args.meditech_dir:
                _load_meditech(db, args.meditech_dir, getattr(args, "meditech_source_name", ""))
            if args.athena_dir:
                _load_athena(db, args.athena_dir, getattr(args, "athena_source_name", ""))
        elif args.source == "epic":
            _load_epic(db, args.input_dir, getattr(args, "source_name", ""))
        elif args.source == "meditech":
            _load_meditech(db, args.input_dir, getattr(args, "source_name", ""))
        elif args.source == "athena":
            _load_athena(db, args.input_dir, getattr(args, "source_name", ""))

        # Print summary after loading
        _print_db_summary(db)


def _print_stage_comparison(parser_counts: dict[str, int], adapter_counts: dict[str, int],
                            db_counts: dict[str, int]) -> None:
    """Print a comparison table of parser vs adapter vs DB record counts."""
    # Collect all table names that have at least one non-zero count
    all_keys = sorted(
        {k for d in (parser_counts, adapter_counts, db_counts) for k in d},
    )
    rows = []
    for key in all_keys:
        p = parser_counts.get(key, "")
        a = adapter_counts.get(key, "")
        d = db_counts.get(key, "")
        if p == 0 and a == 0 and d == 0:
            continue
        flags = []
        if isinstance(p, int) and isinstance(a, int):
            if p > a:
                flags.append("dedup")
            elif p < a:
                flags.append("expand")
        if isinstance(a, int) and isinstance(d, int) and a != d:
            flags.append("LOSS!" if d < a else "extra!")
        flag = f" ({', '.join(flags)})" if flags else ""
        rows.append((key, p, a, d, flag))

    if not rows:
        return

    print("\n  Stage Comparison:")
    print(f"    {'Table':<25} {'Parser':>7}  {'Adapter':>7}  {'DB':>7}")
    print(f"    {'-'*25} {'-'*7}  {'-'*7}  {'-'*7}")
    for key, p, a, d, flag in rows:
        p_str = str(p) if p != "" else "-"
        a_str = str(a) if a != "" else "-"
        d_str = str(d) if d != "" else "-"
        print(f"    {key:<25} {p_str:>7}  {a_str:>7}  {d_str:>7}{flag}")


def _load_auto(db, input_dir: str, source_name: str = ""):
    from chartfold.sources.base import detect_source, resolve_epic_dir

    input_dir = os.path.expanduser(input_dir)
    if not os.path.isdir(input_dir):
        print(f"Error: Directory not found: {input_dir}")
        return

    source = detect_source(input_dir)
    if source is None:
        print(f"Error: Could not detect EHR source type in {input_dir}")
        print("Expected one of:")
        print("  Epic:     DOC####.XML files (or IHE_XDM/ subdirectory)")
        print("  MEDITECH: US Core FHIR Resources.json + CCDA/ directory")
        print("  athena:   Document_XML/*AmbulatorySummary*.xml")
        return

    print(f"Detected source: {source}")
    if source == "epic":
        _load_epic(db, resolve_epic_dir(input_dir), source_name)
    elif source == "meditech":
        _load_meditech(db, input_dir, source_name)
    elif source == "athena":
        _load_athena(db, input_dir, source_name)


def _check_input_dir(input_dir: str, source_type: str) -> bool:
    """Check if input directory exists and print error if not.

    Assumes input_dir has already been expanded via os.path.expanduser().
    Returns True if valid.
    """
    if not os.path.isdir(input_dir):
        print(f"Error: {source_type} directory not found: {input_dir}")
        return False
    return True


def _load_epic(db, input_dir: str, source_name: str = ""):
    from chartfold.adapters.epic_adapter import _parser_counts, epic_to_unified
    from chartfold.sources.epic import process_epic_documents

    input_dir = os.path.expanduser(input_dir)
    if not _check_input_dir(input_dir, "Epic"):
        return

    print(f"\n--- Loading Epic from {input_dir} ---")
    data = process_epic_documents(input_dir)
    parser_counts = _parser_counts(data)
    records = epic_to_unified(data, source_name=source_name or None)
    adapter_counts = records.counts()
    db_counts = db.load_source(records)
    print(f"Source: {records.source}")
    _print_stage_comparison(parser_counts, adapter_counts, db_counts)


def _load_meditech(db, input_dir: str, source_name: str = ""):
    from chartfold.adapters.meditech_adapter import _parser_counts, meditech_to_unified
    from chartfold.sources.meditech import process_meditech_export

    input_dir = os.path.expanduser(input_dir)
    if not _check_input_dir(input_dir, "MEDITECH"):
        return

    print(f"\n--- Loading MEDITECH from {input_dir} ---")
    data = process_meditech_export(input_dir)
    parser_counts = _parser_counts(data)
    records = meditech_to_unified(data, source_name=source_name or None)
    adapter_counts = records.counts()
    db_counts = db.load_source(records)
    print(f"Source: {records.source}")
    _print_stage_comparison(parser_counts, adapter_counts, db_counts)


def _load_athena(db, input_dir: str, source_name: str = ""):
    from chartfold.adapters.athena_adapter import _parser_counts, athena_to_unified
    from chartfold.sources.athena import process_athena_export

    input_dir = os.path.expanduser(input_dir)
    if not _check_input_dir(input_dir, "athenahealth"):
        return

    print(f"\n--- Loading athenahealth/SIHF from {input_dir} ---")
    data = process_athena_export(input_dir)
    parser_counts = _parser_counts(data)
    records = athena_to_unified(data, source_name=source_name or None)
    adapter_counts = records.counts()
    db_counts = db.load_source(records)
    print(f"Source: {records.source}")
    _print_stage_comparison(parser_counts, adapter_counts, db_counts)


def _handle_export(args):
    from chartfold.db import ChartfoldDB

    if args.export_format is None:
        print("Usage: chartfold export <markdown|html|json|hugo> [options]")
        print("\nSubcommands:")
        print("  markdown   Export as Markdown (default format)")
        print("  html       Export as self-contained HTML with charts")
        print("  json       Export as JSON (full database dump)")
        print("  hugo       Generate Hugo static site")
        print("\nRun 'chartfold export <subcommand> --help' for options.")
        sys.exit(1)

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.export_format == "markdown":
            if getattr(args, "full", False):
                from chartfold.export_full import export_full_markdown
                path = export_full_markdown(db, output_path=args.output)
            elif getattr(args, "pdf", False):
                from chartfold.export import export_pdf
                output = args.output if args.output.endswith(".pdf") else args.output.replace(".md", ".pdf")
                path = export_pdf(db, output_path=output, lookback_months=args.lookback)
            else:
                from chartfold.export import export_markdown
                path = export_markdown(db, output_path=args.output, lookback_months=args.lookback)

        elif args.export_format == "json":
            from chartfold.export_full import export_full_json
            include_notes = not getattr(args, "exclude_notes", False)
            include_load_log = getattr(args, "include_load_log", False)
            path = export_full_json(
                db,
                output_path=args.output,
                include_notes=include_notes,
                include_load_log=include_load_log,
            )

        elif args.export_format == "html":
            from chartfold.export_html import export_html, export_html_full
            if getattr(args, "full", False):
                path = export_html_full(
                    db,
                    output_path=args.output,
                    config_path=getattr(args, "config", ""),
                )
            else:
                path = export_html(
                    db,
                    output_path=args.output,
                    lookback_months=args.lookback,
                    config_path=getattr(args, "config", ""),
                )

        elif args.export_format == "hugo":
            from chartfold.hugo.generate import generate_site
            generate_site(
                args.db, args.output,
                config_path=getattr(args, "config", ""),
                linked_sources=getattr(args, "linked_sources", False),
            )
            return  # generate_site prints its own message

    print(f"Exported to {path}")


def _handle_import(args):
    from chartfold.export_full import import_json, validate_json_export

    if args.validate_only:
        result = validate_json_export(args.input_file)
        if result["valid"]:
            print("Validation successful!")
            print("\nTable counts:")
            for table, count in sorted(result["summary"].items()):
                if count > 0:
                    print(f"  {table:<25} {count:>6}")
            total = sum(result["summary"].values())
            print(f"\n  Total records: {total}")
        else:
            print("Validation failed:")
            for error in result["errors"]:
                print(f"  - {error}")
            sys.exit(1)
    else:
        result = import_json(
            args.input_file,
            args.db,
            validate_only=False,
            overwrite=args.overwrite,
        )

        if result["success"]:
            print(f"Import successful to {args.db}")
            print("\nRecords imported:")
            for table, count in sorted(result["counts"].items()):
                if count > 0:
                    print(f"  {table:<25} {count:>6}")
            total = sum(result["counts"].values())
            print(f"\n  Total records: {total}")
        else:
            print("Import failed:")
            for error in result["errors"]:
                print(f"  - {error}")
            sys.exit(1)


def _handle_diff(args):
    from chartfold.analysis.visit_diff import visit_diff
    from chartfold.db import ChartfoldDB

    with ChartfoldDB(args.db) as db:
        db.init_schema()
        diff = visit_diff(db, since_date=args.since_date)

    print(f"\n{'='*50}")
    print(f"Changes since {diff['since_date']}")
    print(f"{'='*50}")

    sections = [
        ("New Labs", "new_labs", ["test_name", "value", "unit", "interpretation", "result_date", "source"]),
        ("New Imaging", "new_imaging", ["study_name", "modality", "study_date", "source"]),
        ("New Pathology", "new_pathology", ["report_date", "specimen", "diagnosis", "source"]),
        ("Medication Changes", "medication_changes", ["name", "status", "start_date", "stop_date", "source"]),
        ("New Notes", "new_notes", ["note_type", "author", "note_date", "source"]),
        ("New Conditions", "new_conditions", ["condition_name", "clinical_status", "onset_date", "source"]),
        ("New Encounters", "new_encounters", ["encounter_date", "encounter_type", "facility", "provider"]),
        ("New Procedures", "new_procedures", ["name", "procedure_date", "facility", "source"]),
    ]

    for title, key, headers in sections:
        rows = diff.get(key, [])
        if not rows:
            continue
        print(f"\n  {title} ({len(rows)}):")
        col_widths = [max(len(h), max((len(str(r.get(h, "") or "")[:40]) for r in rows), default=0))
                      for h in headers]
        fmt = "    " + " | ".join(f"{{:<{w}}}" for w in col_widths)
        print(fmt.format(*headers))
        print("    " + "-+-".join("-" * w for w in col_widths))
        for r in rows[:20]:
            vals = [str(r.get(h, "") or "")[:40] for h in headers]
            print(fmt.format(*vals))
        if len(rows) > 20:
            print(f"    ... and {len(rows) - 20} more")

    summary = diff.get("summary", {})
    total = sum(summary.values())
    if total == 0:
        print("\n  No changes found.")
    else:
        print(f"\n  Total: {total} new/changed records")


def _handle_query(args):
    from chartfold.db import ChartfoldDB

    with ChartfoldDB(args.db) as db:
        try:
            rows = db.query(args.sql)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if not rows:
            print("(no results)")
            return

        # Print as aligned table
        headers = list(rows[0].keys())
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, h in enumerate(headers):
                val = str(row[h]) if row[h] is not None else ""
                col_widths[i] = max(col_widths[i], min(len(val), 60))

        fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
        print(fmt.format(*headers))
        print("-+-".join("-" * w for w in col_widths))
        for row in rows:
            vals = [str(row[h])[:60] if row[h] is not None else "" for h in headers]
            print(fmt.format(*vals))

        print(f"\n({len(rows)} rows)")


def _handle_summary(args):
    from chartfold.db import ChartfoldDB

    with ChartfoldDB(args.db) as db:
        _print_db_summary(db)


def _print_db_summary(db):
    counts = db.summary()
    sources = db.sources()

    print(f"\n{'='*50}")
    print("Database Summary")
    print(f"{'='*50}")
    for table, count in counts.items():
        if count > 0:
            print(f"  {table:<25} {count:>6}")
    print(f"{'='*50}")

    if sources:
        print("\nLoad History:")
        for s in sources:
            print(f"  {s['source']:<25} loaded {s['loaded_at'][:19]}")


def _handle_init_config(args):
    from chartfold.config import generate_config
    from chartfold.db import ChartfoldDB

    with ChartfoldDB(args.db) as db:
        db.init_schema()
        path = generate_config(db, config_path=args.output)
    print(f"Config generated at {path}")


def _handle_notes(args):
    from chartfold.db import ChartfoldDB

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.notes_action == "show":
            _handle_notes_show(db, args.id)
        elif args.notes_action == "search":
            _handle_notes_search(db, args)
        else:
            # Default: list recent notes
            _handle_notes_list(db, getattr(args, "limit", 20))


def _handle_notes_list(db, limit: int = 20):
    rows = db.search_notes_personal()
    if not rows:
        print("No notes found.")
        return

    rows = rows[:limit]
    print(f"\n{'ID':>5}  {'Title':<40}  {'Tags':<25}  {'Updated':<20}")
    print(f"{'─'*5}  {'─'*40}  {'─'*25}  {'─'*20}")
    for r in rows:
        tags = ", ".join(r.get("tags", []))
        updated = (r.get("updated_at") or "")[:19]
        title = (r.get("title") or "")[:40]
        print(f"{r['id']:>5}  {title:<40}  {tags:<25}  {updated:<20}")

    print(f"\n({len(rows)} notes)")


def _handle_notes_search(db, args):
    rows = db.search_notes_personal(
        query=args.query or None,
        tag=args.tag or None,
        ref_table=args.ref_table or None,
    )
    if not rows:
        print("No notes match the search criteria.")
        return

    print(f"\n{'ID':>5}  {'Title':<40}  {'Tags':<25}  {'Updated':<20}")
    print(f"{'─'*5}  {'─'*40}  {'─'*25}  {'─'*20}")
    for r in rows:
        tags = ", ".join(r.get("tags", []))
        updated = (r.get("updated_at") or "")[:19]
        title = (r.get("title") or "")[:40]
        print(f"{r['id']:>5}  {title:<40}  {tags:<25}  {updated:<20}")

    print(f"\n({len(rows)} notes)")


def _handle_notes_show(db, note_id: int):
    note = db.get_note(note_id)
    if not note:
        print(f"Note {note_id} not found.")
        sys.exit(1)

    tags = ", ".join(note.get("tags", []))
    print(f"\n{'='*60}")
    print(f"Note #{note['id']}: {note['title']}")
    if tags:
        print(f"Tags: {tags}")
    if note.get("ref_table"):
        print(f"Linked to: {note['ref_table']} #{note.get('ref_id', '')}")
    print(f"Created: {note['created_at'][:19]}  Updated: {note['updated_at'][:19]}")
    print(f"{'='*60}\n")
    print(note["content"])
    print()


def _handle_assets(args):
    from chartfold.db import ChartfoldDB

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.assets_action == "list":
            _handle_assets_list(db, args)
        elif args.assets_action == "find":
            _handle_assets_find(db, args)
        else:
            # Default: summary
            _handle_assets_summary(db)


def _handle_assets_summary(db):
    """Show asset counts by source and type."""
    rows = db.query("""
        SELECT source, asset_type, COUNT(*) as count, SUM(file_size_kb) as total_kb
        FROM source_assets
        GROUP BY source, asset_type
        ORDER BY source, count DESC
    """)

    if not rows:
        print("No source assets found.")
        return

    print(f"\n{'Source':<25} {'Type':<10} {'Count':>8} {'Size (MB)':>12}")
    print(f"{'─'*25} {'─'*10} {'─'*8} {'─'*12}")

    current_source = None
    for r in rows:
        if r["source"] != current_source:
            if current_source is not None:
                print()
            current_source = r["source"]
        size_mb = (r["total_kb"] or 0) / 1024
        print(f"{r['source']:<25} {r['asset_type']:<10} {r['count']:>8} {size_mb:>12.1f}")

    # Total
    total = db.query("SELECT COUNT(*) as c, SUM(file_size_kb) as kb FROM source_assets")[0]
    print(f"\n{'Total':<36} {total['c']:>8} {(total['kb'] or 0)/1024:>12.1f} MB")


def _handle_assets_list(db, args):
    """List assets with optional filters."""
    conditions = []
    params = []

    if args.source:
        conditions.append("source = ?")
        params.append(args.source)
    if args.type:
        conditions.append("asset_type = ?")
        params.append(args.type)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""

    rows = db.query(
        f"SELECT id, source, asset_type, file_name, file_size_kb, title, encounter_date "
        f"FROM source_assets{where} ORDER BY source, encounter_date DESC, file_name "
        f"LIMIT ?",
        tuple(params) + (args.limit,),
    )

    if not rows:
        print("No assets found matching criteria.")
        return

    print(f"\n{'ID':>6} {'Source':<20} {'Type':<6} {'File':<30} {'Size':>6} {'Date':<12}")
    print(f"{'─'*6} {'─'*20} {'─'*6} {'─'*30} {'─'*6} {'─'*12}")

    for r in rows:
        fname = (r["file_name"] or "")[:30]
        date = r["encounter_date"] or ""
        print(f"{r['id']:>6} {r['source']:<20} {r['asset_type']:<6} {fname:<30} {r['file_size_kb'] or 0:>6} {date:<12}")

    print(f"\n({len(rows)} assets)")


def _handle_assets_find(db, args):
    """Find assets for a specific clinical record."""
    # First get the record to find its source and date
    table = args.table
    record_id = args.id

    # Validate table name against known tables
    valid_tables = [
        "lab_results", "vitals", "medications", "conditions", "procedures",
        "pathology_reports", "imaging_reports", "clinical_notes", "immunizations",
        "allergies", "encounters", "social_history", "family_history", "mental_status",
    ]
    if table not in valid_tables:
        print(f"Unknown table: {table}")
        print(f"Valid tables: {', '.join(valid_tables)}")
        sys.exit(1)

    # Get the record
    record = db.query(f"SELECT * FROM {table} WHERE id = ?", (record_id,))
    if not record:
        print(f"Record {table}#{record_id} not found.")
        sys.exit(1)

    record = record[0]
    source = record.get("source", "")
    source_doc_id = record.get("source_doc_id", "")

    # Find assets linked via ref_table/ref_id
    assets = db.query(
        "SELECT * FROM source_assets WHERE ref_table = ? AND ref_id = ?",
        (table, record_id),
    )

    # Also find assets by source_doc_id if available
    if source_doc_id:
        doc_assets = db.query(
            "SELECT * FROM source_assets WHERE doc_id = ?",
            (source_doc_id,),
        )
        # Merge without duplicates
        existing_ids = {a["id"] for a in assets}
        for a in doc_assets:
            if a["id"] not in existing_ids:
                assets.append(a)

    # Find assets by source document file_path (join through documents table)
    if source_doc_id:
        doc = db.query(
            "SELECT file_path FROM documents WHERE source = ? AND doc_id = ?",
            (source, source_doc_id),
        )
        if doc and doc[0].get("file_path"):
            print(f"\nSource document: {doc[0]['file_path']}")

    if not assets:
        print(f"\nNo assets directly linked to {table}#{record_id}")
        return

    print(f"\nAssets linked to {table}#{record_id}:")
    print(f"{'ID':>6} {'Type':<6} {'File':<40} {'Title':<30}")
    print(f"{'─'*6} {'─'*6} {'─'*40} {'─'*30}")

    for a in assets:
        fname = (a["file_name"] or "")[:40]
        title = (a["title"] or "")[:30]
        print(f"{a['id']:>6} {a['asset_type']:<6} {fname:<40} {title:<30}")


def _handle_identify(args):
    from chartfold.sources.base import detect_source

    source = detect_source(args.input_dir)
    if source is None:
        print(f"Unknown — no recognized EHR format in {args.input_dir}")
        sys.exit(1)
    else:
        print(source)


def _handle_serve_mcp(args):
    os.environ["CHARTFOLD_DB"] = args.db

    from chartfold.mcp.server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
