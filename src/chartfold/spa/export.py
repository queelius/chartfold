"""SPA export: single-file HTML with embedded SQLite database via sql.js.

Produces a self-contained HTML file that loads the database in the browser
using WebAssembly (sql.js) for client-side SQL queries.
"""

from __future__ import annotations

import base64
import gzip
import json
import sqlite3
import tomllib
from pathlib import Path

from chartfold.core.utils import IMAGE_MIME_TYPES

_SPA_DIR = Path(__file__).parent

# JS files must be concatenated in this dependency order
_JS_FILES = [
    "db.js",
    "ui.js",
    "markdown.js",
    "chart.js",
    "sections.js",
    "router.js",
    "app.js",
]

_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


def _safe_json_for_script(json_str: str) -> str:
    """Escape JSON for safe embedding inside <script> tags.

    Replaces '</' with '<\\/' to prevent premature closing of <script> elements.
    This is standard practice for inline JSON in HTML.
    """
    return json_str.replace("</", "<\\/")


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
    result: dict[str, str] = {}

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return "{}"

    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, asset_type, file_path, content_type FROM source_assets"
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return json.dumps(result)

    for row in rows:
        asset_type = (row["asset_type"] or "").lower()
        if asset_type not in IMAGE_MIME_TYPES:
            continue

        file_path = Path(row["file_path"])
        if not file_path.is_file() or file_path.stat().st_size > _MAX_IMAGE_SIZE:
            continue

        mime = row["content_type"] or IMAGE_MIME_TYPES.get(
            asset_type, "application/octet-stream"
        )
        data_b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
        result[str(row["id"])] = f"data:{mime};base64,{data_b64}"

    conn.close()
    return json.dumps(result)


def export_spa(
    db_path: str,
    output_path: str,
    config_path: str = "",
    embed_images: bool = False,
) -> str:
    """Export a chartfold database as a single-file SPA HTML.

    Args:
        db_path: Path to the SQLite database file.
        output_path: Path for the output HTML file.
        config_path: Optional path to a TOML config file.
        embed_images: If True, embed image assets from the database.

    Returns:
        The output file path as a string.
    """
    # 1. Read and compress the database
    db_bytes = Path(db_path).read_bytes()
    db_compressed = gzip.compress(db_bytes, compresslevel=9)
    db_gzip_b64 = base64.b64encode(db_compressed).decode("ascii")

    # 2. Read and encode the WASM binary (no gzip -- already compressed)
    wasm_path = _SPA_DIR / "vendor" / "sql-wasm.wasm"
    wasm_b64 = base64.b64encode(wasm_path.read_bytes()).decode("ascii")

    # 3. Read the sql.js loader script
    sqljs_loader_text = (_SPA_DIR / "vendor" / "sql-wasm.js").read_text(
        encoding="utf-8"
    )

    # 4. Concatenate JS files in dependency order
    js_parts = []
    js_dir = _SPA_DIR / "js"
    for js_file in _JS_FILES:
        js_path = js_dir / js_file
        if js_path.is_file():
            js_parts.append(js_path.read_text(encoding="utf-8"))
    app_js = "\n".join(js_parts)

    # 5. Read CSS
    css_path = _SPA_DIR / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    # 6. Load optional data (escaped for safe embedding in <script> tags)
    config_json = _safe_json_for_script(_load_config_json(config_path))
    images_json = _safe_json_for_script(
        _load_images_json(db_path) if embed_images else "{}"
    )

    # 7. Assemble HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chartfold</title>
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
    <script id="chartfold-db" type="application/gzip+base64">{db_gzip_b64}</script>
    <script id="chartfold-config" type="application/json">{config_json}</script>
    <script id="chartfold-images" type="application/json">{images_json}</script>
    <script>{sqljs_loader_text}</script>
    <script id="app-js">{app_js}</script>
</body>
</html>"""

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    return str(out)
