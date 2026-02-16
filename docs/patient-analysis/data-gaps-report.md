---
title: Data Parity Gap Report
category: data-quality
summary: >
  Audit of 40+ data gaps between raw EHR source files and the SQLite database.
  Identifies parser/adapter bugs (Tempus xT regex, DiagnosticReport misclassification,
  medication status), missing coded data (LOINC, RxNorm, ICD-10), and architectural
  limitations. Severity-rated with file/line references for fixes.
tags:
  - data-quality
  - data-gaps
  - parser-bugs
  - adapter-bugs
  - Epic
  - MEDITECH
  - athena
  - genomic-data
  - coded-data
  - clinical-data-completeness
source: claude
date: "2026-02-15"
status: archived
data_snapshot: "2026-02-15"
archive_reason: Many gaps have since been closed by pipeline fixes
related_tables:
  - lab_results
  - clinical_notes
  - imaging_reports
  - medications
  - procedures
  - pathology_reports
  - conditions
  - encounters
  - immunizations
ehr_sources:
  - epic_ihe_xdm
  - meditech_anderson
  - athena_sihf
date_range:
  start: "2021-09-27"
  end: "2026-02-16"
key_findings:
  - Tempus xT 648-gene panel completely missing (Epic parser regex bug)
  - 62 lab DiagnosticReports misclassified as clinical notes (MEDITECH)
  - 16 individual clinical notes collapsed into 1 blob (athena)
  - Missing LOINC codes on 260 athena lab results
  - Missing RxNorm codes on MEDITECH medications
gaps_by_severity:
  critical: 3
  high: 9
  medium: 15
  low: 13
---

# Data Parity Gap Report — Raw EHR Sources vs. SQLite Database

## Executive Summary

Analysis of raw EHR source files in `dev/{anderson,siteman,sihf}` against the SQLite database at `dev/chartfold.db` reveals **40+ data gaps** across all three sources. The most impactful:

- **TEMPUS XT 648-gene genomic panel** completely missing (Epic parser regex bug)
- **62 lab DiagnosticReports** misclassified as clinical notes (MEDITECH adapter bug)
- **16 individual clinical notes** collapsed into 1 blob record (athena parser design)
- **21 imaging studies** stored as procedures instead of imaging reports (athena classifier)
- **~20 missing encounters** from MEDITECH (only 5 of ~25+ captured)
- **All LOINC, RxNorm, ICD-10 codes** missing from athena source (parser architecture)

---

## Epic/Siteman (source: `epic_ihe_xdm`)

**Raw data**: 80 CDA XML documents in `dev/siteman/IHE_XDM/Alexander1/`

### CRITICAL: TEMPUS XT Genomic Panel Missing

**File**: `src/chartfold/sources/epic.py` line 247-250

The parser regex only matches `"Final result"` or `"Preliminary result"` captions:
```python
r"(.+?)\s*-\s*(?:Final|Preliminary)\s+result\s*\(..."
```

But the Tempus XT caption is:
```
TEMPUS XT DNA AND RNA SOLID TUMOR - Edited Result - FINAL (07/09/2025 8:07 AM CDT)
```

**38 data rows completely dropped**, including:
- MSI Status: Stable
- TMB: 3.7 m/MB
- PD-L1 scores (4 assays, all negative/<1%)
- **HRD Status: Not Detected** (score 23, threshold 50)
- Pertinent Negatives: KRAS, BRAF, NRAS wild-type
- Treatment Recommendation: Cetuximab or Panitumumab
- 3 Clinical Trial Matches with NCT IDs
- HLA Typing (A*02:01, A*31:01, B*14:02, B*15:01, etc.)
- RNA Result: Negative for gene rearrangements

**Clinical significance**: EXTREME. This is the missing Tempus xT tissue report we identified in `questions-for-oncologist.md`. The data IS in the CDA XML — it just failed to parse.

**Fix**: Expand regex to match `"Edited Result"` pattern.

### HIGH: Nursing Notes — 11 Documents, 34K chars

`"Nursing Notes"` is not in `EPIC_CONFIG.note_sections`. Contains:
- Oncology infusion nursing assessments with pre-treatment vitals
- Symptom assessments (nausea, neuropathy, fatigue)
- Chemotherapy tolerance documentation
- Disconnect kit instructions for 5-FU portable pump

**Fix**: Add `"Nursing Notes"` to config.

### HIGH: Per-Encounter Vital Signs — ~207 vs 9 imported

Only the most recent vitals snapshot is captured (from cumulative doc). Per-encounter docs each have their own vitals across 25 encounter dates (2023-2026).

**Fix**: Extract vitals from per-encounter documents, not just cumulative docs.

### HIGH: Administered Medications — 22 Documents

`"Administered Medications"` is not handled. Contains chemotherapy drug names with exact doses (oxaliplatin 100mg, fluorouracil 5000mg, leucovorin 350mg), administration dates/times, IV rates, and pre-medications.

### MODERATE: Other Missing Sections

| Section | Docs | What's Lost |
|---------|------|-------------|
| Medications at Time of Discharge | 16 | Post-surgical med reconciliation |
| Discharge Instructions | 2 | Post-liver-resection care instructions |
| Visit Diagnoses | 54 | Per-encounter diagnosis codes |
| Plan of Treatment | 79 | Scheduled lab orders, health maintenance |

### MODERATE-HIGH: Pathology Structured Fields

2 of 4 pathology reports have empty `diagnosis`, `gross_description`, `microscopic_description` despite rich `full_text` content. The pathology extractor regexes don't match Siteman/BJH formatting.

---

## MEDITECH/Anderson (source: `meditech_anderson`)

**Raw data**: FHIR JSON (691 resources) + 80 CCDA XML files + 25 encounter folders (375 PDFs) + Financial EHI

### CRITICAL: 62 Lab DiagnosticReports Misclassified as Clinical Notes

**File**: `src/chartfold/adapters/meditech_adapter.py` (line ~502-540)

FHIR DiagnosticReports with `category.coding.code = "LAB"` have empty `display` field. The adapter checks `"pathology" in cat.lower()` and `"radiology" in cat.lower()` — but since `cat = ""`, all 62 lab DiagnosticReports fall to the `else` branch and become ClinicalNote records.

**Impact**: 59 of 108 meditech clinical_notes are actually lab-related (e.g., "Hemoglobin", "Creatinine", "Ferritin", "CEA"). Real clinical notes count is ~49.

**Fix**: Check for `cat == "LAB"` or empty category with LAB-associated code patterns.

### CRITICAL: 7 Non-Imaging Reports Misclassified as Imaging Reports

MEDITECH assigns FHIR category `"Radiology"` to ALL non-LAB, non-pathology DiagnosticReports. This puts Office Visit Reports, H&P, Operative Notes, and ED Notes in the `imaging_reports` table.

**Misclassified**: 3 Office Visit Reports, 1 ED Note, 1 H&P, 1 H&P Report, 1 Operative Note

**Fix**: Use `code.text` field for secondary classification — check for imaging-specific terms.

### HIGH: ~20 Missing Encounters

FHIR has only 5 Encounter resources, but there are 25 V-number encounter directories and the Financial EHI data shows 31 unique visit dates.

Critical encounters missing: sigmoid colectomy (2021-12-29), initial colonoscopy (2021-11-22), port insertions, chemotherapy sessions.

**Fix**: Extract encounters from CCDA `Encounters` sections (data present in 71 of 74 parsed files).

### HIGH: Chemotherapy Infusion Records Completely Missing

Financial EHI contains billing data for **14+ FOLFOX chemotherapy cycles** with exact drug names, doses, and dates. None appears in clinical data.

**Fix**: Consider parsing Financial EHI for medication administration records.

### MEDIUM: Other MEDITECH Gaps

| Gap | In Raw | In DB | Notes |
|-----|--------|-------|-------|
| Device records (Port-A-Cath) | 2 | 0 | No Device resource parser |
| Advance Directives | 48 files | 0 | No section handler |
| Functional Status | 61 files | 0 | Assessment observations dropped |
| Care Plan Goals | 24 files | 0 | Anxiety, pain management goals |
| CareTeam roles | 4 | 0 | PCP, attending assignments |
| CCDA parse failures | 6 files | 0 | Encoding issues even with recover=True |

---

## athena/SIHF (source: `athena_sihf`)

**Raw data**: Single CDA XML ambulatory summary (`dev/sihf/Document_XML/alexander_towell_AmbulatorySummary1_alltime.xml`), 2692KB, 23 sections

### Architectural Issue: Parser Only Reads Text Tables, Not CDA Entries

The athena parser extracts data exclusively from human-readable `<text>` table elements. It does NOT parse structured CDA `<entry>` elements which contain coded data (LOINC, RxNorm, ICD-10, CVX, NPI). This is the root cause of most athena gaps.

### HIGH: 16 Individual Clinical Notes Collapsed into 1 Record

The XML "Notes" section contains **16 individual encounter notes** spanning 2021-09-27 through 2026-01-26, each with date, author, note type, and full clinical content. The DB stores these as 1 record (type="Notes") with 76KB of concatenated text.

**Lost data includes clinically significant notes:**
- **04/01/2025**: Complete family history — Mother (COPD, deceased), Father (hypertension, living), Maternal Grandmother (Type 2 Diabetes, deceased). Also substance use history, social history.
- **06/10/2025**: Daily migraines — improve when chemo paused, worsen when restarted. Daily sudafed, 6 cups coffee, frequent ibuprofen/tylenol.
- **10/27/2025**: Psychiatric assessment — "1.5 years ago diagnosed with stage 4 cancer and given 1 year to live." Detailed anxiety management with lorazepam and ambien.
- **11/25/2025**: "Spotted some lesions in his liver. Meeting with surgeon tomorrow." Increased sleep disturbance from anxiety.
- **01/26/2026**: "Going into more intense chemo. Had surgery 12/18 — recovered." Mood: good.

**Fix**: Parse each `<entry>` in the Notes section individually. Extract date from `effectiveTime`, author from `assignedPerson`, content from text reference.

### HIGH: LOINC Codes Missing from All 260 Lab Results

All 260 lab records have empty `test_loinc`. The CDA entries contain LOINC codes (e.g., `6690-2` for WBC, `718-7` for Hemoglobin) but the parser reads only the text table which has no LOINC column.

**Fix**: Parse CDA `<entry>` elements for LOINC codes, or add a LOINC lookup from test name.

### HIGH: 21 Imaging Studies in Procedures Table Instead of Imaging Reports

The Procedures section has two sub-tables: one for surgical/medical procedures, one for imaging studies. The parser treats both as procedures.

Imaging studies wrongly in procedures: CT scans, PET scans, X-rays, ultrasounds, MRI, nuclear medicine bone scan.

**Impact**: `imaging_reports` has 0 records from athena. Surgical timeline tool can't find imaging.

### HIGH: Medication Status Bug — All "Not available"

**File**: `src/chartfold/sources/athena.py`, `_extract_medications`

The header matching loop matches `"Fill Status"` before `"Status"` because `"status" in "fill status"` is true. All medications get `status = "Not available"` (the Fill Status value) instead of their actual status (`active`, `completed`, `aborted`).

### HIGH: RxNorm Codes Missing from All 29 Medications

CDA entries contain RxNorm codes (e.g., `310325` for ferrous sulfate) but text table has no RxNorm column.

### HIGH: ICD-10 Codes Missing from All 12 Conditions

CDA entries contain ICD-10 codes (e.g., `G47.30` for sleep apnea) but text table has no ICD-10 column. SNOMED codes ARE captured.

### MEDIUM: Other athena Gaps

| Gap | Records | Notes |
|-----|---------|-------|
| Encounter diagnosis ICD-10 codes | 16 encounters | Parser extracts but adapter drops |
| CVX codes + lot numbers | 12 immunizations | Only in CDA entries |
| Procedure provider/facility/status | 29 procedures | Text table columns not mapped |
| Medication prescriber | 29 medications | "LastModified by" column not mapped |
| Functional Status section | 8 entries | Not parsed at all |
| Medical History section | 28 entries | Not parsed (5 positive: HTN, GI, anxiety, GERD, asthma) |
| Care Team | 1 entry | PCP: Kelsey Beard, FNP-BC |
| Social history dates | 20 entries | Date column not mapped |
| Patient demographics | 1 record | Race, ethnicity, language, marital status dropped |

---

## Cross-Source Impact on Clinical Analysis

### Data That Changes Our Understanding

1. **Tempus xT tissue results** (Gap: Epic regex) — The HRD Status "Not Detected" (score 23) resolves a key open question. Combined with BRCA1 promoter methylation from Guardant360, this suggests the BRCA1 methylation may NOT create a functional "BRCAness" phenotype. Updates questions 2 and 3 for Dr. Tan.

2. **Family history details** (Gap: athena notes blob) — The 04/01/2025 SIHF note reveals: maternal grandmother had Type 2 Diabetes, father has hypertension. The "Carcinoma of colon" family member mentioned in MEDITECH is NOT listed in this comprehensive family history, which is notable.

3. **Psychiatric notes** (Gap: athena notes blob) — Patient was "given 1 year to live" at stage 4 diagnosis. Anxiety managed with lorazepam and ambien prescribed by oncology. This context is important for holistic care planning.

4. **Migraines** (Gap: athena notes blob) — Daily migraines that correlate with chemotherapy. Propranolol started for prophylaxis. Now taking 6 cups of coffee daily and frequent ibuprofen/tylenol — relevant for drug interactions and liver health.

5. **Chemotherapy administration records** (Gaps: Epic administered meds + MEDITECH Financial EHI) — Complete chemotherapy history with exact doses is not in the database.

### Summary Statistics

| Source | Critical Gaps | High Gaps | Medium Gaps | Low Gaps |
|--------|--------------|-----------|-------------|----------|
| Epic/Siteman | 1 | 3 | 5 | 2 |
| MEDITECH/Anderson | 2 | 2 | 6 | 5 |
| athena/SIHF | 0 | 6 | 6 | 4 |
| **Total** | **3** | **11** | **17** | **11** |

---
*Generated 2026-02-15 from raw source file analysis*
