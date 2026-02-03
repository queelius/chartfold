#!/usr/bin/env python3
"""CLI entry point for chartfold package.

Usage:
    python -m chartfold load epic <input_dir> [--db chartfold.db]
    python -m chartfold load meditech <input_dir> [--db chartfold.db]
    python -m chartfold load athena <input_dir> [--db chartfold.db]
    python -m chartfold load all --epic-dir <> --meditech-dir <> --athena-dir <> [--db ...]
    python -m chartfold query <sql> [--db chartfold.db]
    python -m chartfold summary [--db chartfold.db]
    python -m chartfold generate-site [--db chartfold.db] [--hugo-dir ./site]
    python -m chartfold serve-mcp [--db chartfold.db]
"""

import argparse
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

    all_parser = load_sub.add_parser("all", help="Load all sources at once")
    all_parser.add_argument("--epic-dir", help="Epic source directory")
    all_parser.add_argument("--meditech-dir", help="MEDITECH source directory")
    all_parser.add_argument("--athena-dir", help="athenahealth/SIHF source directory")
    all_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")

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

    # --- export ---
    export_parser = sub.add_parser("export", help="Export clinical data as markdown or PDF")
    export_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    export_parser.add_argument("--output", default="chartfold_export.md", help="Output file path (.md or .pdf)")
    export_parser.add_argument("--lookback", type=int, default=6, help="Months of recent data to include")
    export_parser.add_argument("--format", choices=["markdown", "pdf"], default="markdown", help="Output format")

    # --- init-config ---
    config_parser = sub.add_parser("init-config", help="Generate chartfold.toml config from database")
    config_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    config_parser.add_argument("--output", default="chartfold.toml", help="Config file output path")

    # --- generate-site ---
    site_parser = sub.add_parser("generate-site", help="Generate Hugo static site from database")
    site_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    site_parser.add_argument("--hugo-dir", default="./site", help="Hugo output directory")
    site_parser.add_argument("--config", default="", help="Path to chartfold.toml config file")

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
    elif args.command == "diff":
        _handle_diff(args)
    elif args.command == "query":
        _handle_query(args)
    elif args.command == "summary":
        _handle_summary(args)
    elif args.command == "init-config":
        _handle_init_config(args)
    elif args.command == "generate-site":
        _handle_generate_site(args)
    elif args.command == "notes":
        _handle_notes(args)
    elif args.command == "serve-mcp":
        _handle_serve_mcp(args)


def _handle_load(args):
    from chartfold.db import ChartfoldDB

    if args.source is None:
        print("Usage: chartfold load <epic|meditech|athena|all> ...")
        sys.exit(1)

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.source == "all":
            if args.epic_dir:
                _load_epic(db, args.epic_dir)
            if args.meditech_dir:
                _load_meditech(db, args.meditech_dir)
            if args.athena_dir:
                _load_athena(db, args.athena_dir)
        elif args.source == "epic":
            _load_epic(db, args.input_dir)
        elif args.source == "meditech":
            _load_meditech(db, args.input_dir)
        elif args.source == "athena":
            _load_athena(db, args.input_dir)

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


def _load_epic(db, input_dir: str):
    from chartfold.adapters.epic_adapter import epic_to_unified, _parser_counts
    from chartfold.sources.epic import process_epic_documents

    print(f"\n--- Loading Epic from {input_dir} ---")
    data = process_epic_documents(input_dir)
    parser_counts = _parser_counts(data)
    records = epic_to_unified(data)
    adapter_counts = records.counts()
    db_counts = db.load_source(records)
    _print_stage_comparison(parser_counts, adapter_counts, db_counts)


def _load_meditech(db, input_dir: str):
    from chartfold.adapters.meditech_adapter import meditech_to_unified, _parser_counts
    from chartfold.sources.meditech import process_meditech_export

    print(f"\n--- Loading MEDITECH from {input_dir} ---")
    data = process_meditech_export(input_dir)
    parser_counts = _parser_counts(data)
    records = meditech_to_unified(data)
    adapter_counts = records.counts()
    db_counts = db.load_source(records)
    _print_stage_comparison(parser_counts, adapter_counts, db_counts)


def _load_athena(db, input_dir: str):
    from chartfold.adapters.athena_adapter import athena_to_unified, _parser_counts
    from chartfold.sources.athena import process_athena_export

    print(f"\n--- Loading athenahealth/SIHF from {input_dir} ---")
    data = process_athena_export(input_dir)
    parser_counts = _parser_counts(data)
    records = athena_to_unified(data)
    adapter_counts = records.counts()
    db_counts = db.load_source(records)
    _print_stage_comparison(parser_counts, adapter_counts, db_counts)


def _handle_export(args):
    from chartfold.db import ChartfoldDB
    from chartfold.export import export_markdown, export_pdf

    with ChartfoldDB(args.db) as db:
        db.init_schema()
        if args.format == "pdf":
            output = args.output if args.output.endswith(".pdf") else args.output.replace(".md", ".pdf")
            path = export_pdf(db, output_path=output, lookback_months=args.lookback)
        else:
            path = export_markdown(db, output_path=args.output, lookback_months=args.lookback)

    print(f"Exported to {path}")


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


def _handle_generate_site(args):
    from chartfold.hugo.generate import generate_site

    generate_site(args.db, args.hugo_dir, config_path=getattr(args, "config", ""))


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


def _handle_serve_mcp(args):
    import os

    os.environ["CHARTFOLD_DB"] = args.db

    from chartfold.mcp.server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
