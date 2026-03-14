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
            "SELECT id, asset_type, file_path, content_type FROM source_assets"
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

        mime = row["content_type"] or IMAGE_MIME_TYPES.get(
            asset_type, "application/octet-stream"
        )
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
) -> str:
    """Export a chartfold database as a single-file SPA HTML.

    Args:
        db_path: Path to the SQLite database file.
        output_path: Path for the output HTML file.
        config_path: Optional path to a TOML config file.
        embed_images: If True, embed image assets from the database.
        ai_chat: If True, include the AI chat interface (chat.js, chat.css,
            system prompt, and proxy config).
        proxy_url: URL of the CORS proxy for the AI chat API requests.
            Only used when ai_chat is True.

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
    images_json = _escape_for_script_tag(
        _load_images_json(db_path) if embed_images else "{}"
    )

    # 7. Generate AI chat data (system prompt + config) when enabled
    chat_prompt_tag = ""
    chat_config_tag = ""
    if ai_chat:
        from chartfold.spa.chat_prompt import generate_system_prompt

        system_prompt = _escape_for_script_tag(generate_system_prompt(db_path))
        chat_prompt_tag = (
            f'\n    <script id="chartfold-system-prompt" type="text/plain">'
            f"{system_prompt}</script>"
        )
        chat_config = _escape_for_script_tag(
            json.dumps({"proxyUrl": proxy_url or None})
        )
        chat_config_tag = (
            f'\n    <script id="chartfold-chat-config" type="application/json">'
            f"{chat_config}</script>"
        )

    # 8. Assemble HTML
    chat_tags = chat_prompt_tag + chat_config_tag
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
    <script id="chartfold-images" type="application/json">{images_json}</script>{chat_tags}
    <script>{sqljs_loader_text}</script>
    <script id="app-js">{app_js}</script>
</body>
</html>"""

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    return str(out)
