---
title: Molecular Profile
category: oncology
summary: >
  Comprehensive report of all molecular, genomic, and liquid biopsy results.
  MSS, KRAS/NRAS/BRAF wild-type, TMB-low (4 mut/Mb), HRD score 23/50 (NOT
  deficient despite BRCA1 methylation). MRD-negative by Guardant360. Resolves
  PARP inhibitor eligibility question.
tags:
  - molecular-profiling
  - genomic-testing
  - MSI-status
  - RAS-wild-type
  - TMB-assessment
  - HRD-analysis
  - BRCA1-methylation
  - MRD-negative
  - liquid-biopsy
  - Tempus
  - Guardant360
  - treatment-eligibility
source: claude
date: "2026-02-15"
status: current
data_snapshot: "2026-02-16"
related_tables:
  - lab_results
  - pathology_reports
related_conditions:
  - Colorectal adenocarcinoma (MSS, RAS wild-type)
  - BRCA1 promoter methylation
date_range:
  start: "2022-01-01"
  end: "2026-02-16"
testing_platforms:
  - name: PCR (Anderson)
    date: "2022-01"
    markers: [KRAS, NRAS, BRAF]
  - name: IHC MMR panel
    dates: ["2021-12", "2024-05"]
    markers: [MLH1, MSH2, MSH6, PMS2]
  - name: Tempus xT (648-gene + RNA)
    date: "2025-07-09"
    markers: [TMB, HRD, MSI, 648 genes]
  - name: Tempus XF (liquid biopsy)
    date: "2025-07-08"
    result: inconclusive (no ctDNA detected)
  - name: Guardant360 (liquid biopsy)
    date: "2026-01-15"
    result: MRD-negative, BRCA1 methylation detected
  - name: Guardant Tissue + RNA
    date: "2026-02-11"
    result: pending
key_findings:
  - HRD score 23/50 — NOT deficient, PARP inhibitors not indicated
  - MRD-negative (ctDNA not detected) — favorable prognosis
  - RAS/BRAF wild-type — eligible for anti-EGFR therapy (panitumumab)
  - MSS — checkpoint immunotherapy not standard
related_analyses:
  - cancer-timeline
  - deep-analysis
  - clinical-trials
  - questions-for-oncologist
---

# Molecular Profile — Alexander Towell

## Summary of Molecular Characteristics

| Feature | Result | Source | Date | Clinical Significance |
|---------|--------|--------|------|----------------------|
| **Microsatellite status** | MSS (stable) | PCR (Anderson) + IHC (Anderson + BJH) | 2021-12 / 2024-05 | Not eligible for checkpoint immunotherapy (pembrolizumab/nivolumab) |
| **KRAS** | Wild-type | PCR (Integrated Oncology) | 2022-01 | Eligible for anti-EGFR therapy |
| **NRAS** | Wild-type | PCR (Integrated Oncology) | 2022-01 | Eligible for anti-EGFR therapy |
| **BRAF V600** | Wild-type | PCR (Integrated Oncology) | 2022-01 | No encorafenib/cetuximab regimen needed |
| **MMR IHC** | MLH1+, MSH2+, MSH6+, PMS2+ (all intact) | IHC (Anderson) | 2024-05 | Confirms MSS; low probability MSI-H |
| **TMB** | 2.2 m/MB (low) | Tempus XF (liquid) | 2025-07 | Not eligible for TMB-high immunotherapy |
| **Tumor fraction (ctDNA)** | <0.05% | Guardant360 (liquid) | 2026-01 | **MRD-negative** — no detectable circulating tumor DNA |
| **BRCA1 promoter methylation** | Detected | Guardant360 (liquid) | 2026-01 | Potential PARP inhibitor sensitivity; HRD implications |
| **Tempus XF overall** | Inconclusive | Tempus XF (liquid) | 2025-07 | No reportable pathogenic variants, no treatment options |
| **Tempus xT TMB** | 3.7 m/MB (low) | Tempus xT (tissue) | 2025-07-09 | Below TMB-high threshold |
| **Tempus xT MSI** | Stable | Tempus xT (tissue) | 2025-07-09 | Confirms MSS from prior tests |
| **Tempus xT HRD** | **Not Detected** (score 23, threshold 50) | Tempus xT (tissue RNA) | 2025-07-09 | BRCA1 methylation does NOT create functional HRD |
| **Tempus xT PD-L1** | Negative (<1%, all 4 assays) | Tempus xT (tissue) | 2025-07-09 | Not eligible for PD-L1-directed therapy |
| **Tempus xT HLA** | A*02:01, A*31:01, B*14:02, B*15:01, C*04:01, C*08:02 | Tempus xT (tissue) | 2025-07-09 | Relevant for neoantigen vaccine eligibility |
| **Tempus xT RNA** | Negative for gene rearrangements | Tempus xT (tissue RNA) | 2025-07-09 | No actionable fusions |

## Pending Results

| Test | Specimen | Ordered | Status |
|------|----------|---------|--------|
| **Guardant 360 Tissue + Tissue RNA** | Liver segment 5/8 resection (Dec 2025) | 2026-02-11 | **Pending** |

## Detailed Test Results

### Guardant360 Liquid Biopsy (January 15, 2026)

- **Panel**: ctDNA-based liquid biopsy
- **Tumor Fraction**: <0.05% — essentially no circulating tumor DNA detected
- **MSI-HIGH**: Not detected
- **TMB**: Not Evaluable (insufficient ctDNA for calculation)
- **PROMOTER METHYLATION**: BRCA1

**Interpretation**: The tumor fraction <0.05% is a strong MRD-negative signal.
After two liver resections and extensive systemic therapy, there is no
measurable molecular evidence of residual disease in the bloodstream.
The TMB being "not evaluable" is consistent — when there's essentially no
tumor DNA circulating, you can't calculate a mutation burden.

### Tempus XF Liquid Biopsy (July 8, 2025)

- **Panel**: 523-gene liquid biopsy
- **Overall Interpretation**: Inconclusive
- **Reportable Pathogenic Variants**: None
- **TMB**: 2.2 mutations/megabase (low)
- **MSI-High**: Not detected
- **Treatment Implications**: None reportable
- **Low Coverage Regions**: ABL2, AXIN2, CYP17A1, IRF1, NOTCH2, NTRK2, RHOA, RUNX1, RXRA, SDHAF2, TGFBR1, TP63
- **Portal Link**: https://clinical-portal.securetempus.com/patient/aa82de47-ea6d-4ef7-a329-9495209b26ec/reports/a8e1daf0-a9e1-4822-9ce3-25523cdb42d6

**Interpretation**: At this time point (6 weeks post-liver resection #1),
the liquid biopsy was already inconclusive with no variants. This is consistent
with the Guardant result 6 months later — suggesting the tumor was not
shedding significant ctDNA even while liver metastases were still present.

### Original Tumor Molecular Profile (January 2022)

Tested by Integrated Oncology (Brentwood, TN) on sigmoid colectomy specimen:
- Reference numbers: BMM22-10, BMS22-16, BNR22-8, BMR22-21
- **MSI by PCR**: Microsatellite stability (MSS)
- **KRAS**: Negative for mutation
- **NRAS**: Negative for mutation
- **BRAF V600**: Negative for mutation

### Tempus xT Tissue + RNA Panel (July 9, 2025) — RECOVERED FROM RAW DATA

**Note**: This data was initially missing from the database due to a parser bug (the Epic CDA
caption format "Edited Result - FINAL" didn't match the expected "Final result" regex). The
results below were extracted directly from the raw CDA XML in `dev/siteman/IHE_XDM/Alexander1/DOC0001.XML`.

- **Panel**: TEMPUS XT DNA AND RNA SOLID TUMOR (648-gene panel)
- **Specimen**: Liver segment 2 resection (May 2025), Block A1
- **Overall Interpretation**: Positive
- **MSI Status**: Stable (confirms prior testing)
- **TMB**: 3.7 mutations/megabase (low — below TMB-high threshold of 10)
- **PD-L1**:
  - 28-8 assay: Negative
  - SP142 assay: <1%
  - 22C3 assay: Negative
  - SP263 assay: Negative
- **HRD Status**: **Not Detected** (RNA analysis, score 23, threshold 50)
- **Pertinent Negatives**: KRAS wild-type, BRAF wild-type, NRAS wild-type
- **Treatment Recommendation**: Cetuximab or Panitumumab (Anti-EGFR MAb, FDA approved, NCCN consensus)
- **Clinical Trial Matches**: 3 trials identified with NCT IDs and distances
- **HLA Typing**: HLA-A (A*02:01, A*31:01), HLA-B (B*14:02, B*15:01), HLA-C (C*04:01, C*08:02)
- **xR (RNA) Result**: Negative for gene rearrangements
- **Germline Variants**: None found

**Critical interpretation**: The HRD score of 23 (threshold 50) means the tumor is
**NOT homologous recombination deficient** despite the BRCA1 promoter methylation detected
by Guardant360. This significantly dampens the case for PARP inhibitor therapy — the BRCA1
methylation may not be creating a functional "BRCAness" phenotype. The Guardant Tissue + RNA
test (pending) from the Dec 2025 liver specimen may provide updated HRD status.

### MMR IHC Panel (May 2024)

Performed on ileal tumor biopsy:
- **MLH1**: Positive (intact)
- **MSH2**: Positive (intact)
- **MSH6**: Positive (intact)
- **PMS2**: Positive (intact)
- **Interpretation**: All nuclear markers intact, low probability of MSI-H

## Composite Molecular Portrait

```
RAS/BRAF Status:    All wild-type (KRAS, NRAS, BRAF V600) — confirmed by 3 platforms
MSI Status:         MSS (confirmed by PCR + IHC on 2 specimens + Tempus xT)
TMB:                Low (2.2 liquid / 3.7 tissue m/MB)
HRD Status:         NOT DETECTED (score 23/50) — Tempus xT RNA analysis
PD-L1:              Negative (<1% on all 4 assays)
HER2:               Not tested
ctDNA/MRD:          Negative (<0.05% tumor fraction)
Epigenetic:         BRCA1 promoter methylation (but NOT functional HRD)
HLA Type:           A*02:01, A*31:01, B*14:02, B*15:01, C*04:01, C*08:02
RNA Fusions:        None detected
Tumor sidedness:    Left-sided primary (sigmoid)
```

## Clinical Implications of This Profile

### Favorable factors for anti-EGFR therapy
- RAS wild-type (triple WT: KRAS, NRAS, BRAF)
- Left-sided primary (sigmoid)
- These two factors together represent the "ideal" anti-EGFR profile
- **PARADIGM trial** showed OS benefit for panitumumab vs bevacizumab in this exact population

### Unfavorable factors for immunotherapy
- MSS (not MSI-H) — excludes single-agent checkpoint inhibitors
- Low TMB (2.2) — excludes TMB-high pathway to immunotherapy
- However, **botensilimab/balstilimab** is showing unprecedented responses in MSS CRC (see clinical-trials.md)

### BRCA1 Methylation — Resolved by Tempus xT
- BRCA1 promoter methylation detected by Guardant360 (Jan 2026)
- However, **Tempus xT HRD analysis shows score 23 (threshold 50) — NOT deficient**
- This means BRCA1 methylation is NOT creating functional homologous recombination deficiency
- PARP inhibitor therapy is **unlikely to benefit** this tumor profile
- Cross-sensitivity with platinum agents remains (patient tolerates oxaliplatin well)
- The pending **Guardant Tissue + RNA** from Dec 2025 liver specimen may update HRD status
- If HRD remains negative, PARP inhibitor trials should be deprioritized

---
*Generated 2026-02-15 from chartfold database (3 EHR sources)*
