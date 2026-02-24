#!/usr/bin/env python3
"""CLI entry point for chartfold package.

Usage:
    python -m chartfold load epic <input_dir> [--db chartfold.db]
    python -m chartfold load meditech <input_dir> [--db chartfold.db]
    python -m chartfold load athena <input_dir> [--db chartfold.db]
    python -m chartfold load all --epic-dir <> --meditech-dir <> --athena-dir <> [--db ...]
    python -m chartfold query <sql> [--db chartfold.db]
    python -m chartfold summary [--db chartfold.db]
    python -m chartfold export html [--output FILE] [--embed-images] [--config FILE]
    python -m chartfold export json [--output FILE]
    python -m chartfold serve-mcp [--db chartfold.db]
"""

import argparse
import os
import sys
from pathlib import Path

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
        p.add_argument(
            "--source-name",
            default="",
            help="Source name override (default: derived from directory)",
        )

    auto_parser = load_sub.add_parser("auto", help="Auto-detect source type and load")
    auto_parser.add_argument("input_dir", help="Directory containing source files")
    auto_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    auto_parser.add_argument(
        "--source-name", default="", help="Source name override (default: derived from directory)"
    )

    analyses_load_parser = load_sub.add_parser(
        "analyses", help="Load analysis markdown files into the database"
    )
    analyses_load_parser.add_argument("input_dir", help="Directory containing analysis .md files")
    analyses_load_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")

    mychart_parser = load_sub.add_parser(
        "mychart-visit", help="Load images/data from MyChart MHTML visit page"
    )
    mychart_parser.add_argument("input_file", help="Path to .mhtml file")
    mychart_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    mychart_parser.add_argument(
        "--image-dir", default="", help="Directory to save extracted images (default: next to .mhtml)"
    )
    mychart_parser.add_argument(
        "--source-name", default="mychart", help="Source identifier (default: mychart)"
    )

    test_result_parser = load_sub.add_parser(
        "mychart-test-result", help="Load genomic test results from MyChart MHTML"
    )
    test_result_parser.add_argument("input_file", help="Path to .mhtml file")
    test_result_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    test_result_parser.add_argument(
        "--source-name", default="mychart_tempus", help="Source identifier (default: mychart_tempus)"
    )

    all_parser = load_sub.add_parser("all", help="Load all sources at once")
    all_parser.add_argument("--epic-dir", help="Epic source directory")
    all_parser.add_argument("--meditech-dir", help="MEDITECH source directory")
    all_parser.add_argument("--athena-dir", help="athenahealth/SIHF source directory")
    all_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    all_parser.add_argument("--epic-source-name", default="", help="Epic source name override")
    all_parser.add_argument(
        "--meditech-source-name", default="", help="MEDITECH source name override"
    )
    all_parser.add_argument("--athena-source-name", default="", help="athena source name override")

    # --- diff ---
    diff_parser = sub.add_parser("diff", help="Show what's new since a given date")
    diff_parser.add_argument(
        "since_date", help="ISO date (YYYY-MM-DD) — show changes since this date"
    )
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

    # export json (for full exports)
    json_parser = export_sub.add_parser("json", help="Export as JSON (full database dump)")
    json_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    json_parser.add_argument("--output", default="chartfold_export.json", help="Output file path")
    json_parser.add_argument("--include-load-log", action="store_true", help="Include audit log")
    json_parser.add_argument("--exclude-notes", action="store_true", help="Exclude personal notes")

    # export html
    html_parser = export_sub.add_parser(
        "html", help="Export as self-contained HTML SPA with embedded SQLite"
    )
    html_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    html_parser.add_argument("--output", default="chartfold_export.html", help="Output file path")
    html_parser.add_argument("--config", default="", help="Path to chartfold.toml config file")
    html_parser.add_argument(
        "--embed-images",
        action="store_true",
        help="Embed image assets from source_assets in the HTML file",
    )

    # export arkiv
    arkiv_parser = export_sub.add_parser(
        "arkiv", help="Export as arkiv universal record format (JSONL + manifest)"
    )
    arkiv_parser.add_argument("--db", default=DEFAULT_DB, help=db_help)
    arkiv_parser.add_argument(
        "--output", default="chartfold_arkiv", help="Output directory path"
    )
    arkiv_parser.add_argument(
        "--exclude-notes", action="store_true", help="Exclude personal notes and analyses"
    )

    # --- import ---
    import_parser = sub.add_parser("import", help="Import data from JSON export")
    import_parser.add_argument("input_file", help="Path to JSON export file")
    import_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    import_parser.add_argument(
        "--validate-only", action="store_true", help="Validate without importing"
    )
    import_parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing database"
    )

    # --- init-config ---
    config_parser = sub.add_parser(
        "init-config", help="Generate chartfold.toml config from database"
    )
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

    # --- analyses ---
    analyses_parser = sub.add_parser("analyses", help="Manage structured analyses")
    analyses_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    analyses_sub = analyses_parser.add_subparsers(dest="analyses_action")

    analyses_list_parser = analyses_sub.add_parser("list", help="List all analyses")
    analyses_list_parser.add_argument("--limit", type=int, default=20, help="Max analyses to show")

    analyses_search_parser = analyses_sub.add_parser("search", help="Search analyses")
    analyses_search_parser.add_argument("--tag", default="", help="Filter by tag")
    analyses_search_parser.add_argument("--query", default="", help="Text search")
    analyses_search_parser.add_argument("--category", default="", help="Filter by category")

    analyses_show_parser = analyses_sub.add_parser("show", help="Show full analysis content")
    analyses_show_parser.add_argument("slug", help="Analysis slug to display")

    analyses_delete_parser = analyses_sub.add_parser("delete", help="Delete an analysis")
    analyses_delete_parser.add_argument("slug", help="Analysis slug to delete")
    analyses_delete_parser.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt"
    )

    # --- assets ---
    assets_parser = sub.add_parser("assets", help="View source assets (PDFs, images, etc.)")
    assets_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    assets_sub = assets_parser.add_subparsers(dest="assets_action")

    assets_sub.add_parser("summary", help="Show asset summary by source and type (default)")

    assets_list_parser = assets_sub.add_parser("list", help="List assets")
    assets_list_parser.add_argument("--source", default="", help="Filter by source")
    assets_list_parser.add_argument(
        "--type", default="", help="Filter by asset type (pdf, png, etc.)"
    )
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
    elif args.command == "analyses":
        _handle_analyses(args)
    elif args.command == "assets":
        _handle_assets(args)
    elif args.command == "identify":
        _handle_identify(args)
    elif args.command == "serve-mcp":
        _handle_serve_mcp(args)


def _handle_load(args):
    from chartfold.db import ChartfoldDB

    if args.source is None:
        print("Usage: chartfold load <auto|epic|meditech|athena|mychart-visit|analyses|all> ...")
        sys.exit(1)

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.source == "analyses":
            _load_analyses(db, args.input_dir)
            return
        elif args.source == "mychart-visit":
            _load_mychart_visit(db, args)
            _print_db_summary(db)
            return
        elif args.source == "mychart-test-result":
            _load_mychart_test_result(db, args)
            _print_db_summary(db)
            return
        elif args.source == "auto":
            _load_auto(db, args.input_dir, getattr(args, "source_name", ""))
        elif args.source == "all":
            if args.epic_dir:
                _load_source(db, "epic", args.epic_dir, getattr(args, "epic_source_name", ""))
            if args.meditech_dir:
                _load_source(db, "meditech", args.meditech_dir, getattr(args, "meditech_source_name", ""))
            if args.athena_dir:
                _load_source(db, "athena", args.athena_dir, getattr(args, "athena_source_name", ""))
        elif args.source in _KNOWN_SOURCES:
            _load_source(db, args.source, args.input_dir, getattr(args, "source_name", ""))

        # Print summary after loading
        _print_db_summary(db)


def _print_load_result(
    result: dict,
    parser_counts: dict[str, int],
    adapter_counts: dict[str, int],
) -> None:
    """Print pipeline comparison + diff summary from load result."""
    table_stats = result["tables"]

    # Collect all table names from all sources
    all_keys = sorted(
        {k for d in (parser_counts, adapter_counts, table_stats) for k in d},
    )
    rows = []
    total_new = 0
    total_existing = 0
    total_removed = 0
    for key in all_keys:
        p = parser_counts.get(key, "")
        a = adapter_counts.get(key, "")
        stats = table_stats.get(key)
        total = stats["total"] if stats else 0
        new = stats["new"] if stats else 0
        existing = stats["existing"] if stats else 0
        removed = stats["removed"] if stats else 0

        if p == 0 and a == 0 and total == 0 and removed == 0:
            continue

        total_new += new
        total_existing += existing
        total_removed += removed

        # Build diff annotation
        parts = []
        if new:
            parts.append(f"+{new}")
        if existing:
            parts.append(f"={existing}")
        if removed:
            parts.append(f"-{removed}")
        diff = " ".join(parts) if parts else ""

        # Pipeline flags
        flags = []
        if isinstance(p, int) and isinstance(a, int):
            if p > a:
                flags.append("dedup")
            elif p < a:
                flags.append("expand")
        flag = f" ({', '.join(flags)})" if flags else ""

        rows.append((key, p, a, total, diff, flag))

    if not rows:
        return

    print(f"\n  Stage Comparison:")
    print(f"    {'Table':<22} {'Parser':>7}  {'Adapt':>7}  {'Load':>7}  {'Diff'}")
    print(f"    {'-' * 22} {'-' * 7}  {'-' * 7}  {'-' * 7}  {'-' * 14}")
    for key, p, a, total, diff, flag in rows:
        p_str = str(p) if p != "" else "-"
        a_str = str(a) if a != "" else "-"
        print(f"    {key:<22} {p_str:>7}  {a_str:>7}  {total:>7}  {diff}{flag}")

    # Summary line
    parts = []
    if total_new:
        parts.append(f"{total_new} new")
    if total_existing:
        parts.append(f"{total_existing} existing")
    if total_removed:
        parts.append(f"{total_removed} removed")
    if parts:
        print(f"\n  Summary: {', '.join(parts)}")
    elif not total_new and not total_removed:
        print(f"\n  No changes")


def _load_auto(db, input_dir: str, source_name: str = ""):
    from chartfold.sources.base import detect_source, resolve_epic_dir

    input_dir = os.path.expanduser(input_dir)

    # Handle MHTML files directly (MyChart pages)
    if os.path.isfile(input_dir) and input_dir.lower().endswith(".mhtml"):
        class _Args:
            pass
        args = _Args()
        args.input_file = input_dir

        # Peek at HTML to detect test-result vs visit-note
        if _is_test_result_mhtml(input_dir):
            args.source_name = source_name or "mychart_tempus"
            print("Detected source: mychart-test-result (MHTML file)")
            _load_mychart_test_result(db, args)
        else:
            args.source_name = source_name or "mychart"
            args.image_dir = ""
            print("Detected source: mychart-visit (MHTML file)")
            _load_mychart_visit(db, args)
        return

    if not os.path.isdir(input_dir):
        print(f"Error: Not a directory or .mhtml file: {input_dir}")
        return

    source = detect_source(input_dir)
    if source is None:
        print(f"Error: Could not detect EHR source type in {input_dir}")
        print("Expected one of:")
        print("  Epic:     DOC####.XML files (or IHE_XDM/ subdirectory)")
        print("  MEDITECH: US Core FHIR Resources.json + CCDA/ directory")
        print("  athena:   Document_XML/*AmbulatorySummary*.xml")
        print("  MyChart:  .mhtml file (Past Visit Details page)")
        return

    print(f"Detected source: {source}")
    resolved_dir = resolve_epic_dir(input_dir) if source == "epic" else input_dir
    _load_source(db, source, resolved_dir, source_name)


def _check_input_dir(input_dir: str, source_type: str) -> bool:
    """Check if input directory exists and print error if not.

    Assumes input_dir has already been expanded via os.path.expanduser().
    Returns True if valid.
    """
    if not os.path.isdir(input_dir):
        print(f"Error: {source_type} directory not found: {input_dir}")
        return False
    return True


def _get_source_loader(source_key: str):
    """Return (label, parse_fn, adapt_fn, counts_fn) for the given source key.

    Imports are deferred to avoid loading all source modules at startup.
    """
    if source_key == "epic":
        from chartfold.adapters.epic_adapter import _parser_counts, epic_to_unified
        from chartfold.sources.epic import process_epic_documents

        return "Epic", process_epic_documents, epic_to_unified, _parser_counts

    if source_key == "meditech":
        from chartfold.adapters.meditech_adapter import _parser_counts, meditech_to_unified
        from chartfold.sources.meditech import process_meditech_export

        return "MEDITECH", process_meditech_export, meditech_to_unified, _parser_counts

    if source_key == "athena":
        from chartfold.adapters.athena_adapter import _parser_counts, athena_to_unified
        from chartfold.sources.athena import process_athena_export

        return "athenahealth/SIHF", process_athena_export, athena_to_unified, _parser_counts

    raise ValueError(f"Unknown source: {source_key}")


_KNOWN_SOURCES = {"epic", "meditech", "athena"}


def _load_source(db, source_key: str, input_dir: str, source_name: str = ""):
    """Load a single EHR source through the parse -> adapt -> load pipeline."""
    label, parse_fn, adapt_fn, counts_fn = _get_source_loader(source_key)

    input_dir = os.path.expanduser(input_dir)
    if not _check_input_dir(input_dir, label):
        return

    print(f"\n--- Loading {label} from {input_dir} ---")
    data = parse_fn(input_dir)
    parser_counts = counts_fn(data)
    records = adapt_fn(data, source_name=source_name or None)
    adapter_counts = records.counts()
    result = db.load_source(records, replace=True)
    print(f"Source: {records.source}")
    if result["skipped"]:
        print("  Skipped: data identical to last load")
        return
    _print_load_result(result, parser_counts, adapter_counts)


def _load_analyses(db, input_dir: str):
    """Load analysis markdown files into the database."""
    from chartfold.analysis_parser import parse_analysis_dir

    input_dir = os.path.expanduser(input_dir)
    if not os.path.isdir(input_dir):
        print(f"Error: Directory not found: {input_dir}")
        sys.exit(1)

    analyses = parse_analysis_dir(input_dir)
    if not analyses:
        print(f"No .md files found in {input_dir}")
        return

    print(f"\nLoading {len(analyses)} analyses from {input_dir}...")
    for a in analyses:
        aid = db.save_analysis(**a)
        tags = ", ".join(a["tags"]) if a["tags"] else ""
        tag_str = f" [{tags}]" if tags else ""
        print(f"  {a['slug']:<30} {a['title'][:40]}{tag_str}")

    print(f"\n{len(analyses)} analyses loaded.")


def _load_mychart_visit(db, args):
    """Load clinical images and data from an Epic MyChart MHTML visit page."""
    from chartfold.adapters.mhtml_visit_adapter import (
        _parser_counts,
        mychart_to_unified,
        save_images,
    )
    from chartfold.sources.mhtml_visit import parse_mhtml

    input_file = os.path.expanduser(args.input_file)
    if not os.path.isfile(input_file):
        print(f"Error: MHTML file not found: {input_file}")
        sys.exit(1)

    # Determine image output directory
    image_dir = args.image_dir
    if not image_dir:
        image_dir = str(Path(input_file).parent / "mychart_images")

    print(f"\n--- Loading MyChart visit from {input_file} ---")
    data = parse_mhtml(input_file)

    if not data.visit_date and not data.images:
        print("Error: No visit data or images found in MHTML file.")
        return

    # Print visit info
    if data.visit_date:
        print(f"  Visit: {data.visit_type} - {data.visit_date}")
    if data.provider:
        print(f"  Provider: {data.provider}")
    if data.facility:
        print(f"  Facility: {data.facility}")
    print(f"  Images: {len(data.images)}")
    print(f"  Study references: {len(data.study_refs)}")

    # Save images to disk
    if data.images:
        saved = save_images(data, image_dir)
        print(f"  Saved {len(saved)} images to {image_dir}")

    # Convert to unified records
    parser_counts = _parser_counts(data)
    records = mychart_to_unified(data, source=args.source_name, image_dir=image_dir)
    adapter_counts = records.counts()

    # Use replace=False for granular import (don't delete existing data)
    result = db.load_source(records, replace=False)
    print(f"  Source: {records.source}")
    if result["skipped"]:
        print("  Skipped: data identical to last load")
        return
    _print_load_result(result, parser_counts, adapter_counts)

    # Post-load: link source_assets to imaging_reports by study metadata
    linked = _link_assets_to_imaging(db, records.source)
    if linked:
        print(f"  Linked {linked} image(s) to imaging reports")


def _link_assets_to_imaging(db, source: str) -> int:
    """Link source_assets to imaging_reports using study metadata.

    After mychart import, source_assets have study_name/study_date in their
    metadata JSON but no ref_table/ref_id (since imaging_report IDs didn't
    exist at adapter time). This matches them up post-load.
    """
    rows = db.query(
        """
        SELECT sa.id AS asset_id, ir.id AS report_id
        FROM source_assets sa
        JOIN imaging_reports ir
          ON json_extract(sa.metadata, '$.study_name') = ir.study_name
         AND json_extract(sa.metadata, '$.study_date') = ir.study_date
        WHERE sa.source = ?
          AND (sa.ref_table IS NULL OR sa.ref_table = '')
          AND sa.metadata IS NOT NULL
          AND sa.metadata != ''
        """,
        (source,),
    )
    if not rows:
        return 0
    with db.conn:
        for row in rows:
            db.conn.execute(
                "UPDATE source_assets SET ref_table = 'imaging_reports', ref_id = ? WHERE id = ?",
                (row["report_id"], row["asset_id"]),
            )
    return len(rows)


def _is_test_result_mhtml(file_path: str) -> bool:
    """Peek at an MHTML file to detect if it's a test-result page.

    Test-result pages have componentHeading classes (for TMB, MSI, etc.)
    and a "Test Results List" back-link which visit-note pages do not.
    We read 200KB because the HTML portion starts after MIME headers.
    """
    try:
        with open(file_path, "r", errors="replace") as f:
            head = f.read(200_000)
        return "componentHeading" in head
    except OSError:
        return False


def _load_mychart_test_result(db, args):
    """Load genomic test results from an Epic MyChart MHTML test-result page."""
    from chartfold.adapters.mhtml_test_result_adapter import (
        _parser_counts,
        test_result_to_unified,
    )
    from chartfold.sources.mhtml_test_result import parse_test_result_mhtml

    input_file = os.path.expanduser(args.input_file)
    if not os.path.isfile(input_file):
        print(f"Error: MHTML file not found: {input_file}")
        sys.exit(1)

    print(f"\n--- Loading MyChart test result from {input_file} ---")
    data = parse_test_result_mhtml(input_file)

    if not data.test_name and not data.variants:
        print("Error: No test result data found in MHTML file.")
        return

    # Print test info
    print(f"  Test: {data.test_name}")
    if data.panel:
        print(f"  Panel: {data.panel}")
    if data.provider:
        print(f"  Provider: {data.provider}")
    if data.collection_date:
        print(f"  Collected: {data.collection_date}")
    if data.result_date:
        print(f"  Result: {data.result_date}")
    print(f"  Variants: {len(data.variants)}")

    # Convert to unified records
    parser_counts = _parser_counts(data)
    records = test_result_to_unified(data, source=args.source_name)
    adapter_counts = records.counts()

    # Use replace=False for granular import
    result = db.load_source(records, replace=False)
    print(f"  Source: {records.source}")
    if result["skipped"]:
        print("  Skipped: data identical to last load")
        return
    _print_load_result(result, parser_counts, adapter_counts)


def _handle_export(args):
    from chartfold.db import ChartfoldDB

    if args.export_format is None:
        print("Usage: chartfold export <arkiv|html|json> [options]")
        print("\nSubcommands:")
        print("  arkiv      Export as arkiv universal record format (JSONL + manifest)")
        print("  html       Export as self-contained HTML SPA with embedded SQLite")
        print("  json       Export as JSON (full database dump)")
        print("\nRun 'chartfold export <subcommand> --help' for options.")
        sys.exit(1)

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.export_format == "json":
            from chartfold.export_full import export_full_json

            path = export_full_json(
                db,
                output_path=args.output,
                include_notes=not args.exclude_notes,
                include_load_log=args.include_load_log,
            )

        elif args.export_format == "html":
            from chartfold.spa.export import export_spa

            path = export_spa(
                db_path=args.db,
                output_path=args.output,
                config_path=args.config,
                embed_images=args.embed_images,
            )

        elif args.export_format == "arkiv":
            from chartfold.export_arkiv import export_arkiv

            path = export_arkiv(
                db,
                output_dir=args.output,
                include_notes=not args.exclude_notes,
            )

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

    print(f"\n{'=' * 50}")
    print(f"Changes since {diff['since_date']}")
    print(f"{'=' * 50}")

    sections = [
        (
            "New Labs",
            "new_labs",
            ["test_name", "value", "unit", "interpretation", "result_date", "source"],
        ),
        ("New Imaging", "new_imaging", ["study_name", "modality", "study_date", "source"]),
        ("New Pathology", "new_pathology", ["report_date", "specimen", "diagnosis", "source"]),
        (
            "Medication Changes",
            "medication_changes",
            ["name", "status", "start_date", "stop_date", "source"],
        ),
        ("New Notes", "new_notes", ["note_type", "author", "note_date", "source"]),
        (
            "New Conditions",
            "new_conditions",
            ["condition_name", "clinical_status", "onset_date", "source"],
        ),
        (
            "New Encounters",
            "new_encounters",
            ["encounter_date", "encounter_type", "facility", "provider"],
        ),
        ("New Procedures", "new_procedures", ["name", "procedure_date", "facility", "source"]),
    ]

    for title, key, headers in sections:
        rows = diff.get(key, [])
        if not rows:
            continue
        print(f"\n  {title} ({len(rows)}):")
        col_widths = [
            max(len(h), max((len(str(r.get(h, "") or "")[:40]) for r in rows), default=0))
            for h in headers
        ]
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

    print(f"\n{'=' * 50}")
    print("Database Summary")
    print(f"{'=' * 50}")
    for table, count in counts.items():
        if count > 0:
            print(f"  {table:<25} {count:>6}")
    print(f"{'=' * 50}")

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


def _print_notes_table(rows: list, empty_msg: str = "No notes found.") -> None:
    """Print a formatted table of notes."""
    if not rows:
        print(empty_msg)
        return

    print(f"\n{'ID':>5}  {'Title':<40}  {'Tags':<25}  {'Updated':<20}")
    print(f"{'─' * 5}  {'─' * 40}  {'─' * 25}  {'─' * 20}")
    for r in rows:
        tags = ", ".join(r.get("tags", []))
        updated = (r.get("updated_at") or "")[:19]
        title = (r.get("title") or "")[:40]
        print(f"{r['id']:>5}  {title:<40}  {tags:<25}  {updated:<20}")

    print(f"\n({len(rows)} notes)")


def _handle_notes_list(db, limit: int = 20):
    rows = db.search_notes_personal()
    _print_notes_table(rows[:limit])


def _handle_notes_search(db, args):
    rows = db.search_notes_personal(
        query=args.query or None,
        tag=args.tag or None,
        ref_table=args.ref_table or None,
    )
    _print_notes_table(rows, empty_msg="No notes match the search criteria.")


def _handle_notes_show(db, note_id: int):
    note = db.get_note(note_id)
    if not note:
        print(f"Note {note_id} not found.")
        sys.exit(1)

    tags = ", ".join(note.get("tags", []))
    print(f"\n{'=' * 60}")
    print(f"Note #{note['id']}: {note['title']}")
    if tags:
        print(f"Tags: {tags}")
    if note.get("ref_table"):
        print(f"Linked to: {note['ref_table']} #{note.get('ref_id', '')}")
    print(f"Created: {note['created_at'][:19]}  Updated: {note['updated_at'][:19]}")
    print(f"{'=' * 60}\n")
    print(note["content"])
    print()


def _handle_analyses(args):
    from chartfold.db import ChartfoldDB

    with ChartfoldDB(args.db) as db:
        db.init_schema()

        if args.analyses_action == "show":
            _handle_analyses_show(db, args.slug)
        elif args.analyses_action == "search":
            _handle_analyses_search(db, args)
        elif args.analyses_action == "delete":
            _handle_analyses_delete(db, args.slug, getattr(args, "yes", False))
        else:
            # Default: list
            _handle_analyses_list(db, getattr(args, "limit", 20))


def _print_analyses_table(rows: list, empty_msg: str = "No analyses found.") -> None:
    """Print a formatted table of analyses."""
    if not rows:
        print(empty_msg)
        return

    print(f"\n{'Slug':<30} {'Title':<35} {'Category':<12} {'Tags':<25} {'Updated':<20}")
    print(f"{'─' * 30} {'─' * 35} {'─' * 12} {'─' * 25} {'─' * 20}")
    for r in rows:
        tags = ", ".join(r.get("tags", []))[:25]
        updated = (r.get("updated_at") or "")[:19]
        title = (r.get("title") or "")[:35]
        slug = (r.get("slug") or "")[:30]
        category = (r.get("category") or "")[:12]
        print(f"{slug:<30} {title:<35} {category:<12} {tags:<25} {updated:<20}")

    print(f"\n({len(rows)} analyses)")


def _handle_analyses_list(db, limit: int = 20):
    rows = db.list_analyses()
    _print_analyses_table(rows[:limit])


def _handle_analyses_search(db, args):
    rows = db.search_analyses(
        query=args.query or None,
        tag=args.tag or None,
        category=args.category or None,
    )
    _print_analyses_table(rows, empty_msg="No analyses match the search criteria.")


def _handle_analyses_show(db, slug: str):
    analysis = db.get_analysis(slug)
    if not analysis:
        print(f"Analysis '{slug}' not found.")
        sys.exit(1)

    tags = ", ".join(analysis.get("tags", []))
    print(f"\n{'=' * 60}")
    print(f"{analysis['title']}")
    print(f"Slug: {analysis['slug']}")
    if analysis.get("category"):
        print(f"Category: {analysis['category']}")
    if tags:
        print(f"Tags: {tags}")
    if analysis.get("summary"):
        print(f"Summary: {analysis['summary']}")
    print(f"Source: {analysis['source']}")
    print(f"Created: {analysis['created_at'][:19]}  Updated: {analysis['updated_at'][:19]}")
    print(f"{'=' * 60}\n")
    print(analysis["content"])
    print()


def _handle_analyses_delete(db, slug: str, skip_confirm: bool = False):
    analysis = db.get_analysis(slug)
    if not analysis:
        print(f"Analysis '{slug}' not found.")
        sys.exit(1)

    if not skip_confirm:
        confirm = input(f"Delete analysis '{slug}' ({analysis['title']})? [y/N] ")
        if confirm.lower() != "y":
            print("Cancelled.")
            return

    db.delete_analysis(slug)
    print(f"Deleted analysis '{slug}'.")


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
    print(f"{'─' * 25} {'─' * 10} {'─' * 8} {'─' * 12}")

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
    print(f"\n{'Total':<36} {total['c']:>8} {(total['kb'] or 0) / 1024:>12.1f} MB")


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
        (*tuple(params), args.limit),
    )

    if not rows:
        print("No assets found matching criteria.")
        return

    print(f"\n{'ID':>6} {'Source':<20} {'Type':<6} {'File':<30} {'Size':>6} {'Date':<12}")
    print(f"{'─' * 6} {'─' * 20} {'─' * 6} {'─' * 30} {'─' * 6} {'─' * 12}")

    for r in rows:
        fname = (r["file_name"] or "")[:30]
        date = r["encounter_date"] or ""
        size = r["file_size_kb"] or 0
        atype = r["asset_type"]
        print(f"{r['id']:>6} {r['source']:<20} {atype:<6} {fname:<30} {size:>6} {date:<12}")

    print(f"\n({len(rows)} assets)")


def _handle_assets_find(db, args):
    """Find assets for a specific clinical record."""
    # First get the record to find its source and date
    table = args.table
    record_id = args.id

    # Validate table name against known tables
    valid_tables = [
        "lab_results",
        "vitals",
        "medications",
        "conditions",
        "procedures",
        "pathology_reports",
        "imaging_reports",
        "clinical_notes",
        "immunizations",
        "allergies",
        "encounters",
        "social_history",
        "family_history",
        "mental_status",
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
    print(f"{'─' * 6} {'─' * 6} {'─' * 40} {'─' * 30}")

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
    print(source)


def _handle_serve_mcp(args):
    os.environ["CHARTFOLD_DB"] = args.db

    from chartfold.mcp.server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
