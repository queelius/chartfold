# AI Chat Interface for HTML SPA Export — Design

## Goal

Add an AI-powered natural language chat interface to the chartfold HTML SPA export, allowing doctors and caregivers to ask questions about the patient's medical data without any setup.

## Context

The HTML SPA export already embeds a full SQLite database (via sql.js/WebAssembly) with all clinical tables queryable client-side. This design adds a chat panel where users type natural language questions, and Claude answers by running SQL queries against the embedded database.

## Architecture: Client-Side Agent Loop

```
Browser (chartfold HTML export)
  +-- sql.js          (already exists, full DB loaded)
  +-- Chat UI         (new "Ask AI" tab)
  +-- Agent loop JS:
        User question
          -> POST to proxy -> Claude API (Haiku 4.5)
          <- Claude responds with tool_use (SQL queries)
          -> Browser executes SQL against local sql.js
          -> Results sent back to Claude via proxy
          <- Claude interprets, responds in natural language
          (loop until text response)
```

The proxy is a Cloudflare Worker at `metafunctor-edge` (separate repo). It:
- Injects the Anthropic API key from Cloudflare secrets (key never touches the client)
- Hardcodes the model to `claude-haiku-4-5-20251001` (cost control)
- Enforces origin allowlist (only metafunctor.com + localhost)
- Adds CORS headers for browser access

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent loop location | Client-side (browser) | Builds on existing sql.js, preserves archival self-containment |
| AI model | Haiku 4.5, hardcoded in Worker | Cost control (~$0.001-0.003/turn). Upgraded centrally without re-export |
| API key location | Cloudflare Worker secrets | Never in client code. Rotated via `wrangler secret put` |
| Proxy | metafunctor-edge (separate repo/infra) | Reusable across all static site apps. Hosting-agnostic |
| System prompt | Schema + summary stats + current analyses | Rich case context without dumping raw data |
| Conversation persistence | Session only (in-memory) | No localStorage/D1 for v1. Fresh start on reload |
| Streaming | No | Wait for full response. Simpler implementation |
| Write operations | None | Read-only SQL only, matching MCP server's security model |

## System Prompt Generation

At export time, `export_spa()` generates a system prompt embedded in the HTML:

```
Role instructions (medical data analyst, cite data, no diagnostic advice)
  +
Full DB schema (from schema.sql, ~3KB)
  +
Summary stats (sources, date range, record counts, ~500 bytes)
  +
All "current" analyses (from analyses table, 5-20KB)
```

Analyses with status "current" (from frontmatter) are included as the case briefing. Archived analyses and personal notes are excluded.

Total prompt size: ~10-25KB. Well within Haiku's 200K context window.

## Chat UI

A new "Ask AI" tab in the SPA navigation, containing:
- Scrollable message history area
- Text input with send button
- Settings icon (proxy URL override via localStorage)
- Status indicator (ready / thinking / error)

Behaviors:
- Multiple tool_use calls per turn (Claude may run several queries)
- SQL results capped at LIMIT 100 to control payload size
- sql.js errors returned as tool_result errors (Claude self-corrects)
- Model name not exposed to user (controlled by Worker)

## Export-Time Configuration

New CLI flags:

```bash
chartfold export html --output summary.html --ai-chat \
  --proxy-url https://metafunctor-edge.xxx.workers.dev
```

`--ai-chat` adds to the export:
1. `chat.js` module (agent loop + UI)
2. `chat.css` styles
3. `<script id="chartfold-system-prompt">` with generated prompt
4. `<script id="chartfold-chat-config">` with `{"proxyUrl": "..."}`
5. "Ask AI" tab in navigation

Without `--ai-chat`, the export is identical to today.

Proxy URL is overridable via localStorage key `chartfold_proxy_url` (for development/testing).

## Tool Definition

Single tool provided to Claude:

```json
{
  "name": "run_sql",
  "description": "Execute a read-only SQL query against the patient's health database. Returns results as an array of objects. Use SELECT only.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "SQL SELECT query to execute"
      }
    },
    "required": ["query"]
  }
}
```

## Codebase Changes

**New files:**
- `src/chartfold/spa/js/chat.js` — Agent loop + chat UI (~200-300 lines)
- `src/chartfold/spa/css/chat.css` — Chat panel styling

**Modified files:**
- `src/chartfold/spa/export.py` — `--ai-chat` flag, system prompt generation, conditional chat.js inclusion
- `src/chartfold/cli.py` — Wire `--ai-chat` and `--proxy-url` flags
- `src/chartfold/spa/js/app.js` — Conditional "Ask AI" tab
- `src/chartfold/spa/js/sections.js` — Chat section container

**Not changed:**
- Database, schema, models, adapters, MCP server
- Arkiv export/import
- No new Python dependencies

## Infrastructure Dependencies

- **metafunctor-edge** Cloudflare Worker deployed with:
  - `ANTHROPIC_API_KEY` secret configured
  - Origin allowlist for metafunctor.com
  - Model hardcoded to `claude-haiku-4-5-20251001`
- The HTML export works without the proxy (all existing features function) — only the AI chat requires the proxy connection

## Future Enhancements (not in scope)

- D1 integration (live-queryable DB without embedding)
- Conversation persistence (localStorage or D1)
- Streaming responses
- Multiple tool definitions (lab trends, medication reconciliation)
- Shared annotations between patient and doctor
- Model upgrade path (Worker-controlled, no re-export needed)
