# Data Sources

chartfold supports three major EHR data export formats. This document describes how to obtain exports from each system and what data is extracted.

## Epic MyChart

### Obtaining Exports

1. Log into MyChart
2. Navigate to **Health Summary** or **Medical Records**
3. Select **Download My Data** or **Export**
4. Choose **IHE XDM** or **CDA** format
5. Download the ZIP file and extract

### Expected Directory Structure

```
epic_export/
├── DOC0001.XML    # CDA R2 documents
├── DOC0002.XML
├── DOC0003.XML
└── ...
```

Files follow the pattern `DOC\d{4}\.XML`.

### Data Extracted

| Category | Fields |
|----------|--------|
| **Patient** | Name, DOB, gender, MRN |
| **Encounters** | Date, type, facility, provider, reason |
| **Lab Results** | Test name, LOINC, value, unit, ref range, interpretation, date |
| **Medications** | Name, status, sig, route, start/stop dates, prescriber |
| **Conditions** | Name, ICD-10, status, onset date |
| **Allergies** | Allergen, reaction, severity, status |
| **Procedures** | Name, date, provider, facility, SNOMED code |
| **Vitals** | Type, value, unit, date |
| **Immunizations** | Vaccine, date, lot number, site |
| **Clinical Notes** | Type, author, date, content |
| **Imaging** | Study name, modality, date, impression |
| **Pathology** | Date, specimen, diagnosis, staging, margins |

## MEDITECH Expanse

MEDITECH exports use a dual-format approach that chartfold merges automatically.

### Obtaining Exports

1. Contact your healthcare provider's medical records department
2. Request a MEDITECH Expanse export
3. You may receive multiple formats — chartfold uses both FHIR and CCDA

### Expected Directory Structure

```
meditech_export/
├── US Core FHIR Resources.json    # FHIR R4 Bundle
├── Table of Contents.ndjson       # Document index
└── CCDA/
    ├── a1b2c3d4-e5f6-7890-abcd-ef1234567890.xml
    ├── b2c3d4e5-f6a7-8901-bcde-f12345678901.xml
    └── ...
```

CCDA files are UUID-named.

### Dual-Format Merge

| Data Type | FHIR Source | CCDA Source |
|-----------|-------------|-------------|
| **Encounters** | ✓ Primary | — |
| **Conditions** | ✓ Primary | ✓ (merged) |
| **Medications** | ✓ Primary | ✓ (merged) |
| **Lab Results** | — | ✓ HTML tables |
| **Vitals** | ✓ | ✓ (merged) |
| **Immunizations** | ✓ | ✓ (merged) |
| **Allergies** | — | ✓ |
| **Clinical Notes** | — | ✓ |
| **Social History** | — | ✓ |
| **Family History** | — | ✓ |
| **Mental Status** | — | ✓ |

When both sources have the same data:
- FHIR conditions override CCDA problems (by name match)
- Deduplication uses composite keys: `(test.lower(), date_iso, value)` for labs

### FHIR Resources Processed

- `Patient`
- `Encounter`
- `Condition`
- `MedicationRequest`, `MedicationStatement`
- `Observation` (vitals only; labs come from CCDA)
- `Immunization`

## athenahealth / SIHF

### Obtaining Exports

1. Request an ambulatory summary from your athenahealth provider
2. The export comes as FHIR R4 XML

### Expected Directory Structure

```
athena_export/
└── Document_XML/
    └── Patient_AmbulatorySummary_2025-01-31.xml
```

Or directly in the input directory:
```
athena_export/
└── Patient_AmbulatorySummary_2025-01-31.xml
```

Files match `*AmbulatorySummary*.xml`.

### Data Extracted

| Category | Notes |
|----------|-------|
| **Patient** | Basic demographics |
| **Encounters** | Ambulatory visits |
| **Lab Results** | From Observation resources |
| **Medications** | From MedicationRequest |
| **Conditions** | From Condition resources |
| **Immunizations** | Vaccination history |
| **Allergies** | From AllergyIntolerance |
| **Social History** | Smoking, alcohol, etc. |
| **Family History** | From FamilyMemberHistory |

## Source Provenance

Every record in chartfold includes a `source` field identifying where it came from:

```sql
SELECT DISTINCT source FROM lab_results;
-- Returns: epic, meditech, athena
```

This enables:
- Cross-source comparison
- Duplicate detection
- Audit trail

## Troubleshooting

### Epic: Missing documents

Epic exports sometimes split across multiple ZIP files. Make sure all DOC*.XML files are in the same directory.

### MEDITECH: XML parsing errors

MEDITECH CCDA files sometimes have encoding issues. chartfold uses XML recovery mode (`recover=True`) to handle malformed documents.

### athena: No data extracted

Ensure the file contains `AmbulatorySummary` in its name. athena exports may use different naming conventions — check `Document_XML/` subdirectory.

### General: Dates not parsing

chartfold normalizes dates from various formats:
- `2025-01-15`
- `01/15/2025`
- `Jan 15, 2025`
- `20250115`

If dates appear as `None`, check the source file for unusual date formats and report an issue.
