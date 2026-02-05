# Development Guide

## Setup

```bash
git clone https://github.com/queelius/chartfold.git
cd chartfold
pip install -e ".[dev,mcp]"
```

## Running Tests

```bash
# Run all tests (700+ tests)
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_adapters.py

# Run a single test class or method
python -m pytest tests/test_adapters.py::TestEpicAdapter::test_lab_panel_explosion

# Run tests with coverage
python -m pytest tests/ --cov=chartfold --cov-report=term-missing

# Run tests in parallel
python -m pytest tests/ -n auto
```

## Code Quality

### Linting

```bash
# Check for issues
ruff check .

# Auto-fix what's possible
ruff check --fix .

# Format code
ruff format .
```

### Type Checking

```bash
mypy src/chartfold/
```

## Project Structure

```
src/chartfold/
├── sources/        # EHR-specific parsers
│   ├── base.py     # SourceConfig and shared settings
│   ├── epic.py     # Epic MyChart CDA parser
│   ├── meditech.py # MEDITECH CCDA + FHIR parser
│   └── athena.py   # athenahealth FHIR parser
│
├── adapters/       # Normalize to UnifiedRecords
│   ├── epic_adapter.py
│   ├── meditech_adapter.py
│   └── athena_adapter.py
│
├── core/           # Shared parsing utilities
│   ├── cda.py      # CDA R2 namespace handling
│   ├── fhir.py     # FHIR resource extraction
│   └── utils.py    # Date normalization, deduplication
│
├── analysis/       # Query helpers
│   ├── lab_trends.py
│   ├── medications.py
│   ├── surgical_timeline.py
│   ├── visit_prep.py
│   ├── visit_diff.py
│   ├── data_quality.py
│   └── cross_source.py
│
├── extractors/     # Specialized parsers
│   ├── labs.py     # CEA extraction
│   └── pathology.py # Structured pathology parsing
│
├── formatters/     # Output formatters
│   └── markdown.py
│
├── hugo/           # Hugo site generator
│   └── generate.py
│
├── mcp/            # MCP server
│   ├── server.py
│   └── config.json
│
├── db.py           # Database interface
├── models.py       # Dataclass models
├── schema.sql      # SQLite schema
├── config.py       # TOML configuration
├── cli.py          # Command-line interface
├── export.py       # Markdown export
├── export_html.py  # HTML export
└── export_full.py  # JSON export
```

## Adding a New EHR Source

### 1. Create Source Parser

Create `sources/newsource.py`:

```python
from chartfold.sources.base import SourceConfig

NEWSOURCE_CONFIG = SourceConfig(
    source_name="newsource",
    # ... other config
)

def process_newsource_export(input_dir: str) -> dict:
    """Parse newsource export files.

    Returns dict with keys:
    - lab_results: list of lab dicts
    - medications: list of medication dicts
    - conditions: list of condition dicts
    - etc.
    """
    data = {
        "lab_results": [],
        "medications": [],
        # ...
    }

    # Parse files in input_dir

    return data
```

### 2. Create Adapter

Create `adapters/newsource_adapter.py`:

```python
from chartfold.models import UnifiedRecords, LabResult, MedicationRecord
from chartfold.core.utils import normalize_date_to_iso

def newsource_to_unified(data: dict) -> UnifiedRecords:
    """Convert newsource data to UnifiedRecords."""
    source = data.get("source_name", "newsource")
    records = UnifiedRecords(source=source)

    for lab in data.get("lab_results", []):
        records.lab_results.append(
            LabResult(
                source=source,
                test_name=lab.get("name", ""),
                value=lab.get("value", ""),
                result_date=normalize_date_to_iso(lab.get("date")),
                # ...
            )
        )

    return records


def _parser_counts(data: dict) -> dict:
    """Return record counts from parser output for verification."""
    return {
        "lab_results": len(data.get("lab_results", [])),
        "medications": len(data.get("medications", [])),
        # ...
    }
```

### 3. Add CLI Command

In `cli.py`, add:

```python
@load_group.command()
@click.argument("input_dir", type=click.Path(exists=True))
def newsource(input_dir):
    """Load data from newsource export."""
    _load_newsource(input_dir)


def _load_newsource(input_dir: str):
    from chartfold.sources.newsource import process_newsource_export
    from chartfold.adapters.newsource_adapter import newsource_to_unified, _parser_counts

    data = process_newsource_export(input_dir)
    records = newsource_to_unified(data)

    # Comparison table for verification
    _print_comparison(
        parser_counts=_parser_counts(data),
        adapter_records=records,
    )

    with ChartfoldDB() as db:
        db.init_schema()
        db.load_source(records)
```

### 4. Add Tests

Create `tests/test_newsource.py`:

```python
import pytest
from chartfold.sources.newsource import process_newsource_export
from chartfold.adapters.newsource_adapter import newsource_to_unified


@pytest.fixture
def sample_newsource_data():
    return {
        "lab_results": [
            {"name": "CEA", "value": "5.8", "date": "2025-01-15"}
        ],
        # ...
    }


def test_parser_extracts_labs(sample_newsource_data):
    # Test parser output
    pass


def test_adapter_normalizes_dates(sample_newsource_data):
    records = newsource_to_unified(sample_newsource_data)
    assert records.lab_results[0].result_date == "2025-01-15"
```

## Testing Patterns

### Fixtures

Key fixtures in `tests/conftest.py`:

- `tmp_db` — Fresh database for each test
- `loaded_db` — Database with sample data loaded
- `sample_unified_records` — Pre-built UnifiedRecords
- `sample_epic_data` — Sample Epic parser output
- `sample_meditech_data` — Sample MEDITECH parser output
- `surgical_db` — Database with surgical timeline data

### Roundtrip Tests

`test_roundtrip.py` verifies no data loss through the pipeline:

```python
def test_epic_roundtrip(sample_epic_data, tmp_db):
    """Parser count → Adapter count → DB count should match."""
    parser_counts = _parser_counts(sample_epic_data)
    records = epic_to_unified(sample_epic_data)
    tmp_db.load_source(records)

    db_counts = tmp_db.summary()
    assert db_counts["lab_results"] == parser_counts["lab_results"]
```

## Debugging

### Verbose Loading

```bash
# See detailed output during load
chartfold load epic ~/exports/epic/ --verbose
```

### Query Inspection

```bash
# Raw SQL queries
chartfold query "SELECT * FROM lab_results LIMIT 5"

# Schema inspection
chartfold query "PRAGMA table_info(lab_results)"
```

### Database Inspection

```bash
sqlite3 chartfold.db
.tables
.schema lab_results
SELECT COUNT(*) FROM lab_results GROUP BY source;
```
