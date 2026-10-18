"""SPA export: single-file HTML with embedded SQLite database via sql.js.

Produces a self-contained HTML file that loads the database in the browser
using WebAssembly (sql.js) for client-side SQL queries.
"""

from __future__ import annotations

import base64
import contextlib
import gzip
import json
import shutil
import sqlite3
import tempfile
import tomllib
from pathlib import Path

from health_memex.core.utils import IMAGE_MIME_TYPES
from health_memex.db import _SOFT_DELETE_TABLES

_SPA_DIR = Path(__file__).parent

# Tables that carry the archived_at soft-delete column and must have their
# soft-deleted rows removed before a DB is shipped in the public SPA bundle.
# Sorted for deterministic DELETE order.
_SOFT_DELETE_SPA_TABLES: tuple[str, ...] = tuple(sorted(_SOFT_DELETE_TABLES))

# Tables that hold personal marginalia / analyses. They are dropped from the
# SPA bundle unless the operator opts in with include_notes=True. Mirrors the
# arkiv exporter's note-exclusion list.
_NOTE_TABLES_SPA: tuple[str, ...] = ("notes", "note_tags", "analyses", "analysis_tags")

# The audit trail. Always dropped from the public bundle (it records load
# history and per-source record counts that the SPA never reads).
_AUDIT_TABLES_SPA: tuple[str, ...] = ("load_log",)

# sql.js is not compiled with FTS5 support; shipping the shadow tables just
# bloats the bundle and would make the browser's ``CREATE VIRTUAL TABLE``
# step fail. The SPA falls back to ``LIKE`` for text search.
_FTS5_TABLES: tuple[str, ...] = (
    "clinical_notes_fts",
    "pathology_fts",
    "imaging_fts",
)

# Triggers that feed the FTS5 shadow tables. They reference the virtual
# tables above and must be dropped before the tables are dropped, or the
# drops will fail when SQLite tries to re-validate the trigger body.
_FTS5_TRIGGERS: tuple[str, ...] = (
    "clinical_notes_ai",
    "clinical_notes_ad",
    "clinical_notes_au",
    "pathology_ai",
    "pathology_ad",
    "pathology_au",
    "imaging_ai",
    "imaging_ad",
    "imaging_au",
)

# JS files must be concatenated in dependency order.
# chat.js is inserted between base (data/UI layer) and tail (sections/routing/init)
# only when AI chat is enabled.
_JS_FILES_BASE = [
    "db.js",
    "ui.js",
    "markdown.js",
    "chart.js",
]

_JS_FILES_TAIL = [
    "sections.js",
    "router.js",
    "app.js",
]

_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


def _strip_fts5_and_vacuum(db_path: Path, include_notes: bool = False) -> None:
    """Sanitize, strip FTS5 shadow tables, and VACUUM *db_path* in place.

    Deny-by-default for the public SPA bundle. Steps (each in its own
    connection to avoid cross-transaction issues):

    1. Set ``PRAGMA journal_mode=DELETE`` so no ``-wal``/``-shm`` sidecars
       are left next to the exported DB.
    2. Drop the FTS5 update triggers (which reference the virtual tables).
    3. Drop the FTS5 virtual tables themselves.
    4. Sanitize (see ``_sanitize_db_for_spa``): delete soft-deleted
       (archived) rows from every soft-delete table, drop the load_log
       audit trail, and (unless include_notes is True) drop the personal
       notes / analyses tables.
    5. VACUUM in a fresh connection (VACUUM cannot run inside a
       transaction with other statements in flight). VACUUM also reclaims
       the space freed by the deletes so secrets are not left in free pages.

    Always operate on a copy; never pass the primary DB here. The
    operations are destructive with respect to full-text search and the
    sanitized records.

    Args:
        db_path: Path to the temp DB copy to sanitize in place.
        include_notes: If True, keep the personal notes / analyses tables
            in the bundle. Archived rows and load_log are removed
            regardless.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        for trig in _FTS5_TRIGGERS:
            conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
        for fts in _FTS5_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {fts}")
        _sanitize_db_for_spa(conn, include_notes=include_notes)
        conn.commit()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("VACUUM")


def _sanitize_db_for_spa(conn: sqlite3.Connection, include_notes: bool) -> None:
    """Remove non-publishable data from an SPA-bound DB copy (in *conn*).

    Deny-by-default. Removes:
      - every soft-deleted (archived_at IS NOT NULL) row from each
        soft-delete table, so the SPA never ships records the user deleted,
      - the load_log audit trail (load history / per-source counts), and
      - the personal notes / analyses tables, unless include_notes is True.

    Does not commit or VACUUM; the caller is responsible for both. VACUUM
    afterwards reclaims the freed pages so removed rows leave no residue.
    """
    # 1. Delete archived rows from every soft-delete table.
    for table in _SOFT_DELETE_SPA_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE archived_at IS NOT NULL")

    # 2. Drop the audit trail.
    for table in _AUDIT_TABLES_SPA:
        conn.execute(f"DROP TABLE IF EXISTS {table}")

    # 3. Drop personal notes / analyses unless explicitly included.
    if not include_notes:
        for table in _NOTE_TABLES_SPA:
            conn.execute(f"DROP TABLE IF EXISTS {table}")


def _escape_for_script_tag(content: str) -> str:
    """Escape content for safe embedding inside <script> tags.

    Replaces '</' with '<\\/' to prevent premature closing of <script> elements.
    Works for any content type (JSON, plain text, etc.) embedded in <script> tags.
    """
    return content.replace("</", "<\\/")


def _load_config_json(path: str) -> str:
    """Load a TOML config file and return its contents as a JSON string.

    Returns '{}' if the file does not exist or the path is empty.
    """
    if not path:
        return "{}"
    config_path = Path(path)
    if not config_path.is_file():
        return "{}"
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    return json.dumps(data)


def _load_images_json(db_path: str) -> str:
    """Load image assets from the database and return as JSON map.

    Queries source_assets for image types (png, jpg, etc.), reads the file
    from disk if it exists and is under 10 MB, and base64-encodes it.
    Returns a JSON object keyed by string asset ID with data-URI values.
    """
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return "{}"

    result: dict[str, str] = {}
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, asset_type, file_path, content_type FROM source_assets "
            "WHERE archived_at IS NULL"
        ).fetchall()
    except sqlite3.Error:
        return "{}"
    finally:
        conn.close()

    for row in rows:
        asset_type = (row["asset_type"] or "").lower()
        if asset_type not in IMAGE_MIME_TYPES:
            continue

        file_path = Path(row["file_path"])
        if not file_path.is_file() or file_path.stat().st_size > _MAX_IMAGE_SIZE:
            continue

        mime = row["content_type"] or IMAGE_MIME_TYPES.get(asset_type, "application/octet-stream")
        data_b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
        result[str(row["id"])] = f"data:{mime};base64,{data_b64}"

    return json.dumps(result)


def export_spa(
    db_path: str,
    output_path: str,
    config_path: str = "",
    embed_images: bool = False,
    ai_chat: bool = False,
    proxy_url: str = "",
    include_notes: bool = False,
) -> str:
    """Export a health-memex database as a single-file SPA HTML.

    The embedded DB is sanitized deny-by-default: soft-deleted (archived)
    records and the load_log audit trail are removed, and personal notes /
    analyses are excluded unless include_notes is True. The original DB at
    db_path is never mutated.

    Args:
        db_path: Path to the SQLite database file.
        output_path: Path for the output HTML file.
        config_path: Optional path to a TOML config file.
        embed_images: If True, embed image assets from the database.
        ai_chat: If True, include the AI chat interface (chat.js, chat.css,
            system prompt, and proxy config).
        proxy_url: URL of the CORS proxy for the AI chat API requests.
            Only used when ai_chat is True.
        include_notes: If True, ship the personal notes / analyses tables in
            the bundle. Archived rows and load_log are removed regardless.

    Returns:
        The output file path as a string.
    """
    # 1. Copy the DB to a temp file, strip FTS5 shadow tables, sanitize
    #    (remove archived rows / load_log / optionally notes), set
    #    journal_mode=DELETE, VACUUM, then read + gzip those bytes.
    #    The original DB at db_path is never mutated.
    with tempfile.NamedTemporaryFile(prefix="health_memex_spa_", suffix=".db", delete=False) as tmp:
        tmp_db = Path(tmp.name)
    try:
        shutil.copyfile(db_path, tmp_db)
        _strip_fts5_and_vacuum(tmp_db, include_notes=include_notes)
        db_bytes = tmp_db.read_bytes()
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_db.unlink()
    db_compressed = gzip.compress(db_bytes, compresslevel=9)
    db_gzip_b64 = base64.b64encode(db_compressed).decode("ascii")

    # 2. Read and encode the WASM binary (no gzip -- already compressed)
    wasm_path = _SPA_DIR / "vendor" / "sql-wasm.wasm"
    wasm_b64 = base64.b64encode(wasm_path.read_bytes()).decode("ascii")

    # 3. Read the sql.js loader script
    sqljs_loader_text = (_SPA_DIR / "vendor" / "sql-wasm.js").read_text(encoding="utf-8")

    # 4. Concatenate JS files in dependency order (chat.js only when enabled)
    js_files = _JS_FILES_BASE[:]
    if ai_chat:
        js_files.append("chat.js")
    js_files.extend(_JS_FILES_TAIL)

    js_parts = []
    js_dir = _SPA_DIR / "js"
    for js_file in js_files:
        js_path = js_dir / js_file
        if js_path.is_file():
            js_parts.append(js_path.read_text(encoding="utf-8"))
    app_js = "\n".join(js_parts)

    # 5. Read CSS (append chat.css when AI chat is enabled)
    css_path = _SPA_DIR / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    if ai_chat:
        chat_css_path = _SPA_DIR / "css" / "chat.css"
        if chat_css_path.is_file():
            css += "\n" + chat_css_path.read_text(encoding="utf-8")

    # 6. Load optional data (escaped for safe embedding in <script> tags)
    config_json = _escape_for_script_tag(_load_config_json(config_path))
    images_json = _escape_for_script_tag(_load_images_json(db_path) if embed_images else "{}")

    # 7. Generate AI chat data (system prompt + config) when enabled
    chat_prompt_tag = ""
    chat_config_tag = ""
    if ai_chat:
        from health_memex.spa.chat_prompt import generate_system_prompt

        system_prompt = _escape_for_script_tag(generate_system_prompt(db_path))
        chat_prompt_tag = (
            f'\n    <script id="health-memex-system-prompt" type="text/plain">'
            f"{system_prompt}</script>"
        )
        chat_config = _escape_for_script_tag(json.dumps({"proxyUrl": proxy_url or None}))
        chat_config_tag = (
            f'\n    <script id="health-memex-chat-config" type="application/json">'
            f"{chat_config}</script>"
        )

    # 8. Assemble HTML
    chat_tags = chat_prompt_tag + chat_config_tag
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Health Memex</title>
    <style>{css}</style>
</head>
<body>
    <div id="app">
        <div id="loading">
            <div class="spinner"></div>
            <p>Loading database...</p>
        </div>
    </div>
    <script id="sqljs-wasm" type="application/base64">{wasm_b64}</script>
    <script id="health-memex-db" type="application/gzip+base64">{db_gzip_b64}</script>
    <script id="health-memex-config" type="application/json">{config_json}</script>
    <script id="health-memex-images" type="application/json">{images_json}</script>{chat_tags}
    <script>{sqljs_loader_text}</script>
    <script id="app-js">{app_js}</script>
</body>
</html>"""

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    return str(out)
