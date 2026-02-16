"""YAML+markdown parser for structured analyses.

Parses analysis files with optional YAML frontmatter:

    ---
    title: Cancer Timeline Analysis
    category: oncology
    tags: [cancer, CEA]
    ---

    # Cancer Timeline Analysis
    ...markdown body...

Files without frontmatter use the filename as title.
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    import yaml
except ImportError as e:
    raise ImportError(
        "PyYAML is required for analysis parsing. Install with: pip install pyyaml"
    ) from e


def parse_analysis_file(path: str | Path) -> dict:
    """Parse a single analysis markdown file.

    Returns a dict with: slug, title, content, frontmatter_json,
    category, summary, tags, source.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    slug = path.stem  # "cancer-timeline.md" -> "cancer-timeline"

    frontmatter: dict = {}
    content = text

    # Split YAML frontmatter from markdown body
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            yaml_text = parts[1]
            content = parts[2].lstrip("\n")
            frontmatter = yaml.safe_load(yaml_text) or {}

    title = frontmatter.pop("title", None)
    if not title:
        # Derive title from first heading or filename
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        if not title:
            title = slug.replace("-", " ").title()

    category = frontmatter.pop("category", None)
    summary = frontmatter.pop("summary", None)
    tags = frontmatter.pop("tags", [])
    source = frontmatter.pop("source", "user")

    # Store remaining frontmatter fields as JSON
    frontmatter_json = json.dumps(frontmatter) if frontmatter else None

    return {
        "slug": slug,
        "title": title,
        "content": content,
        "frontmatter_json": frontmatter_json,
        "category": category,
        "summary": summary,
        "tags": tags if isinstance(tags, list) else [tags],
        "source": source,
    }


def parse_analysis_dir(dir_path: str | Path) -> list[dict]:
    """Parse all .md files in a directory.

    Returns a list of parsed analysis dicts, sorted by slug.
    """
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Analysis directory not found: {dir_path}")

    results = []
    for md_file in sorted(dir_path.glob("*.md")):
        if md_file.name.lower() == "readme.md":
            continue
        results.append(parse_analysis_file(md_file))

    return results
