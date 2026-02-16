---
title: Questions for Dr. Tan — Prioritized
category: patient-communication
summary: >
  Structured question list for oncologist, prioritized by clinical urgency.
  Tier 1: Guardant Tissue results, Tempus xT HRD findings, BRCA1 implications,
  disease origin question. Tier 2: Margin follow-up, lung nodules, anti-EGFR
  strategy. Tier 3: Liquid biopsy timing, trial eligibility, genetic counseling.
tags:
  - patient-engagement
  - shared-decision-making
  - treatment-planning
  - pending-results
  - Tempus-xT
  - Guardant360
  - BRCA1-methylation
  - HRD-status
  - diagnostic-uncertainty
  - genetic-counseling
  - clinical-trial-eligibility
  - neuropathy-management
source: claude
date: "2026-02-15"
status: current
data_snapshot: "2026-02-16"
related_tables:
  - lab_results
  - imaging_reports
  - pathology_reports
  - procedures
  - medications
related_conditions:
  - Metastatic colorectal cancer
  - BRCA1 promoter methylation
  - Peripheral neuropathy (oxaliplatin-induced)
  - Hashimoto's thyroiditis
  - Lung nodules (indeterminate)
date_range:
  start: "2026-02-01"
  end: "2026-02-16"
pending_results:
  - test: Guardant Tissue + RNA
    ordered: "2026-02-11"
    specimen: December 2025 liver resection
related_analyses:
  - deep-analysis
  - molecular-profile
  - clinical-trials
---

# Questions for Dr. Tan — Prioritized

## Tier 1: High-Impact, Time-Sensitive

### 1. Guardant Tissue + RNA Results (Pending)
"The Guardant 360 Tissue + Tissue RNA test was ordered from the December liver specimen on Feb 11. When do we expect results, and what specifically are you looking for? Will the tissue-based test reveal more about BRCA1 methylation status and HRD?"

*Why this matters*: The liquid biopsy showed <0.05% tumor fraction (MRD-negative) and BRCA1 methylation. The tissue test may reveal additional somatic mutations, HRD status, and potentially actionable findings not detectable in blood when ctDNA is undetectable.

### 2. Tempus xT Tissue Results — RECOVERED (see molecular-profile.md)
~~"The Tempus xT test results appear to be in a PDF attachment that I can't access."~~

**UPDATE**: The Tempus xT results were found in the raw CDA XML from Epic (DOC0001.XML). They were missed by the database import due to a parser bug. Key findings:
- HRD Status: **Not Detected** (score 23, threshold 50)
- PD-L1: Negative across all 4 assays
- TMB: 3.7 m/MB (low)
- MSI: Stable
- Treatment rec: anti-EGFR (cetuximab/panitumumab)
- 3 clinical trial matches identified

**Revised question**: "I was able to find the Tempus xT results. The HRD score was 23 out of 50. Does this definitively rule out PARP inhibitor benefit? And can you share the 3 clinical trial matches the report identified?"

### 3. BRCA1 Methylation — Largely Resolved by Tempus xT
~~"Does BRCA1 methylation create a 'BRCAness' phenotype?"~~

**UPDATE**: The Tempus xT HRD score of 23 (threshold 50) indicates the BRCA1 methylation is NOT creating functional homologous recombination deficiency. PARP inhibitors are unlikely to benefit.

**Revised question**: "The Tempus xT showed HRD score 23/50 — not deficient. The Guardant Tissue + RNA is pending from the December liver specimen. Could HRD status change in the newer metastasis? Or should we consider PARP inhibitors deprioritized at this point?"

### 4. One Cancer or Two?
"Dr. Byrnes' 2024 Wash U pathology review raised the question of whether the ileal tumor was a new primary or a peritoneal metastasis from the 2021 sigmoid cancer. With all the evidence now — no mucosal precursor, perienteric origin, 5 tumor deposits, rectovesicular peritoneal deposits — what is the current consensus? Does the Guardant Tissue test help answer this?"

*Why this matters*: This affects staging, prognosis calculations, and potentially treatment intensity decisions.

---

## Tier 2: Important for Treatment Planning

### 5. Positive Margin on Segment 2 (May 2025)
"The first liver resection had a positive cauterized margin and perineural invasion. The second resection (Dec 2025) had negative margins. Was the segment 2 area re-evaluated at the second surgery? Is there concern about local recurrence at that site?"

### 6. Indeterminate Right Lung Nodule
"The 8-9mm right lower lobe solid nodule has been stable for 14+ months. You've noted it 'may represent metastatic disease vs benign process.' At what point would we consider a CT-guided biopsy to definitively characterize it? If it IS metastatic, does that change the treatment approach?"

### 7. Right Suprahilar Lymph Node
"The right suprahilar lymph node has been called 'indeterminate' on three consecutive PET/CTs over 18 months. Would an EBUS-guided biopsy be reasonable to resolve this? Or does stability effectively rule out metastatic disease?"

### 8. FOLFOX Duration and Neuropathy
"I had neuropathy from the first round of FOLFOX (2022). Now on mFOLFOX6 again with gabapentin started. What's the planned number of cycles? Is there a cumulative dose limit we're watching? If neuropathy worsens, would you switch to FOLFIRI/panitumumab?"

### 9. Anti-EGFR Strategy Confirmation
"I understand you're holding panitumumab in reserve rather than adding it now, consistent with the New EPOC trial showing anti-EGFR can worsen outcomes in the post-resection NED setting. Can you confirm the plan: deploy panitumumab only if disease recurs and is unresectable? What would trigger that decision?"

---

## Tier 3: Surveillance and Long-Term Planning

### 10. Repeat Liquid Biopsy Timing
"Given the MRD-negative Guardant360, when should we repeat ctDNA testing? The CIRCULATE-Japan GALAXY data suggests MRD-negative patients with resected liver mets may not benefit from adjuvant chemo. How does that factor into our plan?"

### 11. Botensilimab/Balstilimab Awareness
"I've read about the BOT/BAL immunotherapy combination showing 42% two-year survival in MSS CRC at ESMO GI 2025. The BATTMAN Phase 3 trial started enrolling in late 2025. If my current regimen eventually fails, would I be eligible? Is Siteman a trial site?"

### 12. Genetic Counseling
"My family history includes colon cancer in a relative (I need to clarify which one). Given my early-onset CRC at 46 and the BRCA1 methylation finding, has genetic counseling been considered? Should I pursue germline genetic testing beyond what the tumor profiling has shown?"

### 13. Thyroid Monitoring
"The August 2025 PET showed persistent diffuse left hemithyroid activity. Given my Hashimoto's thyroiditis and right thyroid lobectomy, is this just Hashimoto's inflammation? Or should the remaining thyroid tissue be evaluated more closely?"

### 14. Chronic Ileitis / Crohn's Consideration
"The ileal tumor arose without a visible mucosal precursor. Chronic ileitis (as in Crohn's disease) is a known risk factor for small bowel adenocarcinoma. Was Crohn's formally evaluated and ruled out? This could affect long-term GI surveillance planning."

### 15. Iron and Nutrition Monitoring
"My ferritin went from <1 at diagnosis to 5.09 in 2024 — still very low. Am I absorbing oral iron adequately with the shortened bowel (sigmoid + right hemi resections)? Should we consider IV iron infusion?"

---

## Information to Bring to the Appointment

1. **This analysis document** (printed or on tablet)
2. **CEA trend chart** — shows the complete trajectory from 1.4 (2021) through 5.8 peak to 1.7 current
3. **All molecular results** in one place (see molecular-profile.md)
4. **Request**: Copy of the Tempus xT tissue report PDF
5. **Request**: Copy of the bone scan report from May 22, 2024 (results not in database structured data)
6. **Ask**: Which relative had colon cancer? (to inform genetic counseling)

---
*Generated 2026-02-15 from chartfold database analysis*
