# Fair (Type-Aware) Extraction Comparison — Design

**Date:** 2026-06-07
**Status:** Approved, pending implementation
**Extends:** the eval harness. Fixes the extraction agreement metric, which currently uses brittle
**exact value matching** and understates true agreement.

---

## Problem

`ExtractionAgreementDimension` compares candidate vs golden-set extraction with exact per-field
equality (`a == b`). Extraction fields are heterogeneous (strings, dates, numbers, lists of dicts),
so exact match counts formatting differences as mismatches:
- case/whitespace (`"Viral Fever"` vs `"viral fever"`)
- date formats (`"2024-11-01"` vs `"01/11/2024"`)
- number types (`4200` vs `4200.0`)
- partial-but-correct (`"Paracetamol"` vs `"Tab Paracetamol"`)
- **lists of dicts** (`medicines`, `line_items`, `test_results`): any sub-field/order diff = whole-field miss

Result: the reported 58% extraction "agreement" is a floor, not real semantic divergence.

Classification / requirements / consistency compare closed-set enums → exact match is correct and
stays unchanged. **Only extraction changes.**

---

## Golden-set field taxonomy (observed)

- **Strings**: names, addresses, `gstin`, `bill_number`, `lab_id`, `diagnosis_primary`, `chief_complaint`
- **Dates**: `prescription_date`, `bill_date`, `sample_date`, `report_date`, `discharge_date`, `admission_date`
- **Numbers (float)**: `*_amount`, `unit_rate`, `quantity`, `gst_amount`
- **Bool/enum**: `patient_gender`, `nabl_accredited`
- **Lists of dicts**: `medicines{medicine_name,strength_or_dosage,frequency,duration,instruction}`,
  `line_items{description,quantity,unit_rate,amount,category_hint}`,
  `test_results{test_name,result_value,unit,normal_range,interpretation}`, `tests_ordered{test_name,note}`
- **Lists of strings**: `diagnosis_secondary`, procedures
- **None**: field genuinely absent

---

## Design

### `evals/field_compare.py`
`compare_value(field_name, a, b) -> "exact" | "normalized" | "mismatch"`, routed by value type:

| Type | Rule |
|---|---|
| both `None` | exact |
| one `None`, other not | mismatch |
| **number** (int/float, or numeric string) | float compare, tol 1e-2 → exact if identical repr else normalized |
| **date** (field name ends `_date` or parseable) | parse both to ISO; equal → exact if same string else normalized |
| **bool / gender** | canonicalize (`m/male→m`, `f/female→f`, true/false) → normalized if equal |
| **string** | exact if raw equal; else normalize (lowercase, collapse ws, strip punctuation) and: equal → normalized; containment either way → normalized; `SequenceMatcher` ratio ≥ 0.9 → normalized; else mismatch |
| **list of str** | normalized-set: Jaccard ≥ 0.9 → normalized (else mismatch); empty==empty exact |
| **list of dict** | order-insensitive: match items by their key subfield (`medicine_name`/`description`/`test_name`/first str field) via normalized string compare; for matched pairs average sub-field agreement; score = (matched & ≥0.7 sub-agreement) / max(len ref,len cand); ≥0.9 → normalized else mismatch |

Helpers: `_norm_str`, `_parse_date` (handles `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `D Mon YYYY`),
`_as_number`, `_canon_bool`.

### Reworked `ExtractionAgreementDimension`
For each doc, take the populated section (`_section_fields`), compare every field via `compare_value`,
tally buckets. Report in `details`:
- `field_agreement` = (exact + normalized) / total  ← the fair headline
- `exact_only` = exact / total  ← shows how much was formatting
- `critical_field_agreement` = (exact+normalized)/total over the **critical fields only**
- `cand_completeness`, `ref_completeness` (unchanged)
- `cand_latency`
- `mismatches`: list of `{case_id, file_id, field, ref, cand}` (capped) for inspection

Critical fields per document type:
- PRESCRIPTION: patient_name, prescription_date, diagnosis_primary, doctor_name
- HOSPITAL_BILL: patient_name, bill_date, total_amount
- LAB_REPORT: patient_name, report_date, test_results
- PHARMACY_BILL: patient_name, bill_date, net_amount
- DENTAL_REPORT: patient_name, diagnosis, procedures_recommended_or_done
- DISCHARGE_SUMMARY: patient_name, discharge_date, final_diagnosis

`DimensionResult.score` = `field_agreement`.

### `stage_compare.py` report
Show extraction as: field-agreement (fair) + exact-only + critical-field agreement. Markdown +
JSON updated.

---

## Testing
- `field_compare`: exact, case/whitespace, containment, fuzzy threshold, date formats, number
  types, bool/gender, list-of-str Jaccard, list-of-dict order-insensitive match, None handling.
- `ExtractionAgreementDimension`: monkeypatched candidate + cached ref → correct bucket tallies,
  critical-field subset, mismatch capture. (Full agreement when only formatting differs.)
- `stage_compare` render includes the new extraction fields.
- No live calls in tests.

## Non-Goals
- Touching classification/requirements/consistency comparison (exact is correct).
- An LLM-judge for extraction (deterministic type-aware matching is the chosen approach).
