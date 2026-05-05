"""
Policy decision engine — deterministic Python, no LLM.

run_policy_decision() calls all seven policy-rule functions in sequence,
applies the priority rules in code, and returns a PolicyDecision dict.
No LLM is involved; the same inputs always produce the same output.
"""
from __future__ import annotations

import json
import pathlib
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.claims_history import (
    get_ytd_claims_amount as _get_ytd,
    get_same_day_claims_count as _get_same_day_count,
    get_monthly_claims_count as _get_monthly_count,
    get_family_ytd_claims_amount as _get_family_ytd,
)

# ---------------------------------------------------------------------------
# Policy terms — loaded once at module import.
# ---------------------------------------------------------------------------
_POLICY_TERMS_PATH = pathlib.Path(__file__).parent.parent.parent / "policy_terms.json"
if not _POLICY_TERMS_PATH.exists():
    _POLICY_TERMS_PATH = pathlib.Path(__file__).parent.parent.parent.parent / "policy_terms.json"
with open(_POLICY_TERMS_PATH) as _f:
    _PT: dict[str, Any] = json.load(_f)


# ---------------------------------------------------------------------------
# Output schema (still exported so the root agent can embed it in PipelineTrace)
# ---------------------------------------------------------------------------

class RuleFinding(BaseModel):
    check: str
    result: Literal["PASS", "FAIL", "INCONCLUSIVE", "MANUAL_REVIEW"]
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    decision: Literal["APPROVED", "PARTIAL", "REJECTED", "MANUAL_REVIEW"]
    approved_amount: float
    copay_amount: float
    reason: str
    confidence_score: float
    rule_findings: list[RuleFinding]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _member(member_id: str) -> dict[str, Any] | None:
    return next((m for m in _PT.get("members", []) if m.get("member_id") == member_id), None)


def _days_since_join(member_id: str, treatment_date: str) -> int | None:
    m = _member(member_id)
    if not m or not m.get("join_date"):
        return None
    try:
        return (date.fromisoformat(treatment_date) - date.fromisoformat(m["join_date"])).days
    except ValueError:
        return None


def _eligible_from(join_date: str, days: int) -> str:
    from datetime import timedelta
    try:
        return (date.fromisoformat(join_date) + timedelta(days=days)).isoformat()
    except ValueError:
        return "unknown"


def _get_family_member_ids(member_id: str) -> list[str]:
    m = _member(member_id)
    if m is None:
        return [member_id]
    primary_id = m.get("primary_member_id") or member_id
    primary = _member(primary_id) or m
    ids = [primary_id]
    for dep_id in (primary.get("dependents") or []):
        ids.append(dep_id)
    return ids


def _is_network_hospital(hospital_name: str, network_hospitals: list[str]) -> bool:
    _GENERIC = {"hospital", "hospitals", "healthcare", "health", "medical",
                "clinic", "centre", "center", "care", "institute"}
    hosp_lower = hospital_name.lower()
    for network in network_hospitals:
        brand_words = [w for w in network.lower().split() if w not in _GENERIC and len(w) > 2]
        if not brand_words:
            continue
        if re.search(r"\b" + re.escape(brand_words[0]) + r"\b", hosp_lower):
            return True
    return False


def _is_confirmed_condition(term: str, text: str) -> bool:
    text_lower = text.lower()
    pattern = re.compile(r"\b" + re.escape(term.lower()) + r"\b")
    _NEGATIONS = (
        "no ", "not ", "denies ", "without ", "rule out", "r/o ",
        "history of", "family history", "h/o", "risk of", "risk factor",
        "hx of", "no h/o", "no history", "excluded", "unlikely",
        "possible ", "suspected ", "query ",
    )
    for match in pattern.finditer(text_lower):
        prefix = text_lower[max(0, match.start() - 50): match.start()]
        if not any(neg in prefix for neg in _NEGATIONS):
            return True
    return False


# ---------------------------------------------------------------------------
# Priority helper
# ---------------------------------------------------------------------------

_PRIORITY = {"APPROVED": 1, "PARTIAL": 2, "MANUAL_REVIEW": 3, "REJECTED": 4}


def _raise_decision(current: str, candidate: str) -> str:
    """Return the higher-priority decision."""
    return candidate if _PRIORITY.get(candidate, 0) > _PRIORITY.get(current, 0) else current


# ---------------------------------------------------------------------------
# Policy-rule functions (pure Python, no LLM)
# ---------------------------------------------------------------------------

def check_dependent_coverage(
    member_id: str,
    patient_member_id: str | None,
    relationship_claim_type: str,
) -> dict[str, Any]:
    if relationship_claim_type.upper() != "DEPENDENT" or not patient_member_id:
        m = _member(member_id)
        return {
            "check": "DEPENDENT_COVERAGE", "result": "PASS",
            "detail": "Self-claim — patient is the primary member.",
            "patient_name": m.get("name") if m else None,
            "relationship": "SELF", "is_covered_relationship": True,
        }

    patient = _member(patient_member_id)
    if patient is None:
        return {
            "check": "DEPENDENT_COVERAGE", "result": "FAIL",
            "detail": f"Patient '{patient_member_id}' not found in policy roster.",
            "patient_name": None, "relationship": None, "is_covered_relationship": False,
        }

    if patient.get("primary_member_id") != member_id:
        return {
            "check": "DEPENDENT_COVERAGE", "result": "FAIL",
            "detail": (
                f"Patient '{patient_member_id}' ({patient.get('name')}) is not registered "
                f"as a dependent of member '{member_id}'."
            ),
            "patient_name": patient.get("name"),
            "relationship": patient.get("relationship"), "is_covered_relationship": False,
        }

    floater_cfg: dict = _PT.get("coverage", {}).get("family_floater", {})
    covered_rels = [r.upper() for r in floater_cfg.get("covered_relationships", [])]
    patient_rel = (patient.get("relationship") or "").upper()
    if patient_rel == "CHILD":
        patient_rel = "CHILDREN"

    if patient_rel not in covered_rels:
        return {
            "check": "DEPENDENT_COVERAGE", "result": "FAIL",
            "detail": (
                f"Patient's relationship '{patient_rel}' is not covered under the family floater. "
                f"Covered: {', '.join(covered_rels)}."
            ),
            "patient_name": patient.get("name"),
            "relationship": patient_rel, "is_covered_relationship": False,
        }

    return {
        "check": "DEPENDENT_COVERAGE", "result": "PASS",
        "detail": f"Patient '{patient.get('name')}' ({patient_rel}) is a covered dependent of '{member_id}'.",
        "patient_name": patient.get("name"),
        "relationship": patient_rel, "is_covered_relationship": True,
    }


def check_member_eligibility(member_id: str, treatment_date: str) -> dict[str, Any]:
    m = _member(member_id)
    if m is None:
        return {
            "check": "MEMBER_ELIGIBILITY", "result": "FAIL",
            "detail": f"Member '{member_id}' not found in policy roster.",
            "member_name": None, "join_date": None, "days_since_join": None,
        }

    join_date = m.get("join_date")
    if not join_date:
        return {
            "check": "MEMBER_ELIGIBILITY", "result": "INCONCLUSIVE",
            "detail": "Join date missing — cannot verify initial waiting period.",
            "member_name": m.get("name"), "join_date": None, "days_since_join": None,
        }

    days = _days_since_join(member_id, treatment_date)
    if days is None:
        return {
            "check": "MEMBER_ELIGIBILITY", "result": "INCONCLUSIVE",
            "detail": "Date parse error — cannot compute waiting period.",
            "member_name": m.get("name"), "join_date": join_date, "days_since_join": None,
        }

    required = int(_PT.get("waiting_periods", {}).get("initial_waiting_period_days", 30))
    if days < required:
        return {
            "check": "MEMBER_ELIGIBILITY", "result": "FAIL",
            "detail": (
                f"Initial waiting period of {required} days not met. "
                f"Treatment is {days} day(s) after join date {join_date}. "
                f"Eligible from {_eligible_from(join_date, required)}."
            ),
            "member_name": m.get("name"), "join_date": join_date, "days_since_join": days,
        }

    return {
        "check": "MEMBER_ELIGIBILITY", "result": "PASS",
        "detail": f"Member found. {days} days since join — initial waiting period satisfied.",
        "member_name": m.get("name"), "join_date": join_date, "days_since_join": days,
    }


def check_waiting_periods(member_id: str, treatment_date: str, diagnosis: str) -> dict[str, Any]:
    waiting_cfg: dict = _PT.get("waiting_periods", {})
    specific: dict[str, int] = waiting_cfg.get("specific_conditions", {})
    pre_existing_days: int = int(waiting_cfg.get("pre_existing_conditions_days", 365))

    days = _days_since_join(member_id, treatment_date)
    m = _member(member_id)
    join_date = m.get("join_date", "") if m else ""

    if not diagnosis:
        if days is not None and days < pre_existing_days:
            return {
                "check": "WAITING_PERIOD", "result": "INCONCLUSIVE",
                "detail": (
                    f"No diagnosis provided. Member enrolled {days} day(s) ago; "
                    f"pre-existing conditions require {pre_existing_days} days. "
                    "Cannot confirm whether this is a pre-existing condition without medical history."
                ),
                "matched_condition": "PRE_EXISTING_CONDITIONS",
                "required_days": pre_existing_days, "days_since_join": days,
                "eligible_from": _eligible_from(join_date, pre_existing_days),
                "pre_existing_flag": True,
            }
        return {
            "check": "WAITING_PERIOD", "result": "PASS",
            "detail": "No diagnosis — no condition-specific waiting period to check.",
            "matched_condition": None, "required_days": None,
            "days_since_join": days, "eligible_from": None, "pre_existing_flag": False,
        }

    # Specific condition check (whole-word, negation-aware)
    matched_condition: str | None = None
    required_days: int | None = None
    for condition, req_days in specific.items():
        display = condition.replace("_", " ")
        tokens = [display] + [t for t in display.split() if len(t) > 3]
        if any(_is_confirmed_condition(t, diagnosis) for t in tokens):
            matched_condition = condition
            required_days = req_days
            break

    if matched_condition is not None:
        if days is None:
            return {
                "check": "WAITING_PERIOD", "result": "INCONCLUSIVE",
                "detail": (
                    f"Diagnosis matches '{matched_condition}' (requires {required_days} days) "
                    "but dates unavailable."
                ),
                "matched_condition": matched_condition, "required_days": required_days,
                "days_since_join": None, "eligible_from": None, "pre_existing_flag": False,
            }
        if days < required_days:
            return {
                "check": "WAITING_PERIOD", "result": "FAIL",
                "detail": (
                    f"Condition '{matched_condition}' requires a {required_days}-day waiting period. "
                    f"Only {days} day(s) since join. "
                    f"Eligible from {_eligible_from(join_date, required_days)}."
                ),
                "matched_condition": matched_condition, "required_days": required_days,
                "days_since_join": days,
                "eligible_from": _eligible_from(join_date, required_days),
                "pre_existing_flag": False,
            }
        return {
            "check": "WAITING_PERIOD", "result": "PASS",
            "detail": (
                f"Condition '{matched_condition}' waiting period of {required_days} days satisfied "
                f"({days} days since join)."
            ),
            "matched_condition": matched_condition, "required_days": required_days,
            "days_since_join": days, "eligible_from": None, "pre_existing_flag": False,
        }

    # General pre-existing conditions gate
    if days is not None and days < pre_existing_days:
        return {
            "check": "WAITING_PERIOD", "result": "INCONCLUSIVE",
            "detail": (
                f"Member enrolled {days} day(s) ago. Pre-existing conditions require "
                f"{pre_existing_days} days. Cannot confirm from documents whether this "
                "condition pre-dates enrolment — manual verification required."
            ),
            "matched_condition": "PRE_EXISTING_CONDITIONS",
            "required_days": pre_existing_days, "days_since_join": days,
            "eligible_from": _eligible_from(join_date, pre_existing_days),
            "pre_existing_flag": True,
        }

    return {
        "check": "WAITING_PERIOD", "result": "PASS",
        "detail": "Diagnosis does not match any condition-specific waiting period.",
        "matched_condition": None, "required_days": None,
        "days_since_join": days, "eligible_from": None, "pre_existing_flag": False,
    }


def check_exclusions(
    claim_category: str,
    diagnosis: str,
    procedures: str,
    line_items_json: str,
) -> dict[str, Any]:
    exclusions: dict[str, Any] = _PT.get("exclusions", {})
    cat_key = claim_category.lower()
    cat_config: dict[str, Any] = _PT.get("opd_categories", {}).get(cat_key, {})

    all_exclusions = (
        exclusions.get("conditions", [])
        + (exclusions.get("dental_exclusions", []) if cat_key == "dental" else [])
        + (exclusions.get("vision_exclusions", []) if cat_key == "vision" else [])
        + cat_config.get("excluded_procedures", [])
        + cat_config.get("excluded_items", [])
    )

    def _check_text(text: str) -> str | None:
        for excl in all_exclusions:
            tokens = sorted([t for t in excl.lower().split() if len(t) > 4], key=len, reverse=True)
            if tokens and _is_confirmed_condition(tokens[0], text):
                return excl
        return None

    combined_text = f"{diagnosis or ''} {procedures or ''}"
    diag_exclusion = _check_text(combined_text)

    excluded_items: list[dict[str, Any]] = []
    covered_amount: float | None = None

    try:
        line_items: list[dict[str, Any]] = json.loads(line_items_json) if line_items_json else []
    except (json.JSONDecodeError, TypeError):
        line_items = []

    if line_items:
        covered_amount = 0.0
        for item in line_items:
            desc = str(item.get("description", ""))
            amt = float(item.get("amount", 0) or 0)
            excl_match = _check_text(desc)
            if excl_match:
                excluded_items.append({"description": desc, "amount": amt, "reason": excl_match})
            else:
                covered_amount += amt

    if excluded_items:
        excluded_total = sum(i["amount"] for i in excluded_items)
        return {
            "check": "EXCLUSIONS", "result": "FAIL",
            "detail": (
                f"{len(excluded_items)} line item(s) excluded totalling ₹{excluded_total:,.0f}: "
                + "; ".join(
                    f"'{i['description']}' (₹{i['amount']:,.0f}) — {i['reason']}"
                    for i in excluded_items
                )
            ),
            "excluded_items": excluded_items, "covered_amount": covered_amount, "full_exclusion": False,
        }

    if diag_exclusion and not line_items:
        return {
            "check": "EXCLUSIONS", "result": "FAIL",
            "detail": f"Diagnosis/procedure matches excluded condition: '{diag_exclusion}'.",
            "excluded_items": [], "covered_amount": None, "full_exclusion": True,
        }

    return {
        "check": "EXCLUSIONS", "result": "PASS",
        "detail": "No exclusions matched.",
        "excluded_items": [], "covered_amount": covered_amount, "full_exclusion": False,
    }


def check_pre_authorization(
    claim_category: str,
    tests_ordered_json: str,
    claimed_amount: float,
    has_pre_authorization: bool,
) -> dict[str, Any]:
    cat_key = claim_category.lower()
    cat_config: dict[str, Any] = _PT.get("opd_categories", {}).get(cat_key, {})

    requires_pre_auth_flag: bool = cat_config.get("requires_pre_auth", False)
    pre_auth_threshold: float = float(cat_config.get("pre_auth_threshold", float("inf")))
    high_value_tests: list[str] = [t.lower() for t in cat_config.get("high_value_tests_requiring_pre_auth", [])]

    try:
        tests_ordered: list[str] = json.loads(tests_ordered_json) if tests_ordered_json else []
    except (json.JSONDecodeError, TypeError):
        tests_ordered = []

    triggered_by: list[str] = []
    if requires_pre_auth_flag:
        triggered_by.append("category requires pre-authorization")
    if claimed_amount > pre_auth_threshold:
        triggered_by.append(
            f"claimed amount ₹{claimed_amount:,.0f} exceeds threshold ₹{pre_auth_threshold:,.0f}"
        )
    for test in tests_ordered:
        if any(hvt in test.lower() for hvt in high_value_tests):
            triggered_by.append(f"high-value test '{test}' requires pre-authorization")

    if not triggered_by:
        return {
            "check": "PRE_AUTHORIZATION", "result": "PASS",
            "detail": "Pre-authorization not required.", "pre_auth_required": False, "triggered_by": [],
        }
    if has_pre_authorization:
        return {
            "check": "PRE_AUTHORIZATION", "result": "PASS",
            "detail": f"Pre-authorization required and confirmed. Triggered by: {'; '.join(triggered_by)}.",
            "pre_auth_required": True, "triggered_by": triggered_by,
        }
    return {
        "check": "PRE_AUTHORIZATION", "result": "FAIL",
        "detail": (
            f"Pre-authorization required but not obtained. Triggered by: {'; '.join(triggered_by)}. "
            "Please obtain pre-authorization and resubmit."
        ),
        "pre_auth_required": True, "triggered_by": triggered_by,
    }


def check_coverage_limits(
    member_id: str,
    claim_category: str,
    claimed_amount: float,
    bill_total_amount: float | None,
    hospital_name: str | None,
    covered_bill_amount: float | None,
    patient_member_id: str | None = None,
) -> dict[str, Any]:
    coverage: dict[str, Any] = _PT.get("coverage", {})
    cat_key = claim_category.lower()
    cat_config: dict[str, Any] = _PT.get("opd_categories", {}).get(cat_key, {})
    network_hospitals: list[str] = _PT.get("network_hospitals", [])

    floater_cfg: dict[str, Any] = coverage.get("family_floater", {})
    floater_enabled: bool = bool(floater_cfg.get("enabled", False))
    combined_limit: float = float(floater_cfg.get("combined_limit", float("inf")))

    sub_limit: float = float(cat_config.get("sub_limit", float("inf")))
    copay_pct: float = float(cat_config.get("copay_percent", 0))
    network_discount_pct: float = float(cat_config.get("network_discount_percent", 0))
    per_claim_limit: float = float(coverage.get("per_claim_limit", float("inf")))
    annual_opd_limit: float = float(coverage.get("annual_opd_limit", float("inf")))

    ytd: float = _get_ytd(member_id)
    remaining_individual: float = max(0.0, annual_opd_limit - ytd)

    family_ids = _get_family_member_ids(patient_member_id or member_id)
    family_ytd: float = _get_family_ytd(family_ids) if floater_enabled else ytd
    remaining_family: float = max(0.0, combined_limit - family_ytd) if floater_enabled else float("inf")
    remaining_annual: float = min(remaining_individual, remaining_family)

    base_amount: float = (
        covered_bill_amount if covered_bill_amount is not None
        else (bill_total_amount if bill_total_amount is not None else claimed_amount)
    )

    effective_rejection_limit = max(sub_limit, per_claim_limit)
    if claimed_amount > effective_rejection_limit:
        return {
            "check": "COVERAGE_LIMITS", "result": "FAIL",
            "detail": f"Claimed ₹{claimed_amount:,.0f} exceeds per-claim limit ₹{effective_rejection_limit:,.0f}.",
            "base_amount": base_amount, "effective_base": 0.0, "in_network": False,
            "network_discount_percent": 0, "copay_percent": copay_pct,
            "eligible_amount": 0.0, "approved_amount": 0.0, "copay_amount": 0.0,
            "ytd_amount": ytd, "family_ytd_amount": family_ytd,
            "remaining_annual": remaining_annual, "remaining_family": remaining_family,
        }

    if remaining_annual <= 0:
        msg = (
            f"Annual OPD limit ₹{annual_opd_limit:,.0f} exhausted (YTD: ₹{ytd:,.0f})."
            if remaining_individual <= 0
            else (
                f"Family floater combined limit ₹{combined_limit:,.0f} exhausted "
                f"(family YTD: ₹{family_ytd:,.0f}, members: {', '.join(family_ids)})."
            )
        )
        return {
            "check": "COVERAGE_LIMITS", "result": "FAIL", "detail": msg,
            "base_amount": base_amount, "effective_base": 0.0, "in_network": False,
            "network_discount_percent": 0, "copay_percent": copay_pct,
            "eligible_amount": 0.0, "approved_amount": 0.0, "copay_amount": 0.0,
            "ytd_amount": ytd, "family_ytd_amount": family_ytd,
            "remaining_annual": 0.0, "remaining_family": remaining_family,
        }

    in_network = _is_network_hospital(hospital_name, network_hospitals) if hospital_name else False

    if in_network and network_discount_pct > 0:
        effective_base = round(base_amount * (1 - network_discount_pct / 100), 2)
    else:
        effective_base = min(base_amount, sub_limit)

    eligible = round(min(effective_base, remaining_annual), 2)
    copay = round(eligible * (copay_pct / 100), 2)
    approved = round(eligible - copay, 2)

    network_note = (
        f" In-network: {network_discount_pct}% discount applied (₹{base_amount:,.0f} → ₹{effective_base:,.0f})."
        if in_network and network_discount_pct > 0
        else (f" Non-network: capped at sub-limit ₹{sub_limit:,.0f}." if not in_network and base_amount > sub_limit else "")
    )
    floater_note = (
        f" Family floater: ₹{family_ytd:,.0f} used by {len(family_ids)} member(s) of ₹{combined_limit:,.0f}."
        if floater_enabled else ""
    )

    return {
        "check": "COVERAGE_LIMITS", "result": "PASS",
        "detail": (
            f"Base: ₹{base_amount:,.0f}.{network_note}"
            f" Eligible: ₹{eligible:,.0f} (annual remaining: ₹{remaining_annual:,.0f}).{floater_note}"
            f" Approved: ₹{approved:,.0f} after ₹{copay:,.0f} co-pay ({copay_pct}%)."
        ),
        "base_amount": base_amount, "effective_base": effective_base,
        "in_network": in_network, "network_discount_percent": network_discount_pct if in_network else 0,
        "copay_percent": copay_pct, "eligible_amount": eligible,
        "approved_amount": approved, "copay_amount": copay,
        "ytd_amount": ytd, "family_ytd_amount": family_ytd,
        "remaining_annual": remaining_annual, "remaining_family": remaining_family,
    }


def check_fraud_signals(
    member_id: str,
    treatment_date: str,
    claimed_amount: float,
    claims_history: list[dict] | None = None,
) -> dict[str, Any]:
    thresholds: dict[str, Any] = _PT.get("fraud_thresholds", {})
    same_day_limit: int = int(thresholds.get("same_day_claims_limit", 2))
    monthly_limit: int = int(thresholds.get("monthly_claims_limit", 6))
    high_value_threshold: float = float(thresholds.get("auto_manual_review_above", 25000))

    signals: list[str] = []

    # Use intake-supplied claims_history when available; fall back to DB lookup.
    if claims_history:
        same_day_count = sum(
            1 for c in claims_history
            if str(c.get("date", "")).startswith(treatment_date)
        )
    else:
        same_day_count = _get_same_day_count(member_id, treatment_date)

    if same_day_count > same_day_limit:
        signals.append(f"Same-day claims: {same_day_count} on {treatment_date} (limit: {same_day_limit}).")

    monthly_count: int | None = None
    try:
        d = date.fromisoformat(treatment_date)
        monthly_count = _get_monthly_count(member_id, d.year, d.month)
        if monthly_count > monthly_limit:
            signals.append(f"Monthly claims: {monthly_count} in {d.strftime('%B %Y')} (limit: {monthly_limit}).")
    except ValueError:
        pass

    if claimed_amount > high_value_threshold:
        signals.append(
            f"High-value claim: ₹{claimed_amount:,.0f} exceeds auto-review threshold ₹{high_value_threshold:,.0f}."
        )

    if signals:
        return {
            "check": "FRAUD_SIGNALS", "result": "MANUAL_REVIEW",
            "detail": "Fraud/abuse signals detected: " + " | ".join(signals),
            "signals": signals, "same_day_count": same_day_count, "monthly_count": monthly_count,
        }
    return {
        "check": "FRAUD_SIGNALS", "result": "PASS",
        "detail": "No fraud or abuse signals detected.",
        "signals": [], "same_day_count": same_day_count, "monthly_count": monthly_count,
    }


# ---------------------------------------------------------------------------
# Extraction-field parser
# ---------------------------------------------------------------------------

def _parse_extraction_fields(extracted_docs: list[dict]) -> dict[str, Any]:
    """Derive the fields needed for policy checks from a list of DocumentExtractionResult dicts."""
    diagnosis: str | None = None
    procedures_list: list[str] = []
    hospital_name: str | None = None
    bill_total_amount: float | None = None
    line_items: list[dict] = []
    tests_ordered_names: list[str] = []

    for doc in extracted_docs:
        presc = doc.get("prescription") or {}
        bill = doc.get("hospital_bill") or {}
        pharmacy = doc.get("pharmacy_bill") or {}
        dental = doc.get("dental_report") or {}
        discharge = doc.get("discharge_summary") or {}

        if diagnosis is None:
            diagnosis = (
                presc.get("diagnosis_primary")
                or dental.get("diagnosis")
                or discharge.get("final_diagnosis")
            )

        if hospital_name is None:
            hospital_name = bill.get("hospital_name") or presc.get("hospital_or_clinic_name")

        if bill_total_amount is None:
            raw = bill.get("total_amount") or pharmacy.get("net_amount")
            if raw is not None:
                try:
                    bill_total_amount = float(raw)
                except (TypeError, ValueError):
                    pass

        if not line_items:
            line_items = [i for i in (bill.get("line_items") or []) if i]

        for t in (presc.get("tests_ordered") or []):
            name = (t or {}).get("test_name")
            if name and name not in tests_ordered_names:
                tests_ordered_names.append(name)
                procedures_list.append(name)

    return {
        "diagnosis": diagnosis or "",
        "procedures": ", ".join(procedures_list),
        "hospital_name": hospital_name,
        "bill_total_amount": bill_total_amount,
        "line_items_json": json.dumps([
            {"description": i.get("description", ""), "amount": i.get("amount", 0)}
            for i in line_items
        ]),
        "tests_ordered_json": json.dumps(tests_ordered_names),
    }


# ---------------------------------------------------------------------------
# Reason builder
# ---------------------------------------------------------------------------

def _build_reason(
    findings: list[dict],
    decision: str,
    approved_amount: float,
    copay_amount: float,
) -> str:
    failed = [f for f in findings if f["result"] == "FAIL"]
    if failed:
        return "; ".join(f["detail"] for f in failed)

    manual = [f for f in findings if f["result"] == "MANUAL_REVIEW"]
    inconclusive = [f for f in findings if f["result"] == "INCONCLUSIVE"]

    if decision == "MANUAL_REVIEW":
        triggers = [f["detail"] for f in (manual + inconclusive)]
        return "Routed to manual review: " + "; ".join(triggers[:3])

    if decision == "PARTIAL":
        excl = next((f for f in findings if f["check"] == "EXCLUSIONS"), None)
        excl_note = " Some items excluded from coverage." if excl else ""
        return (
            f"Claim partially approved: ₹{approved_amount:,.0f} after ₹{copay_amount:,.0f} co-pay.{excl_note}"
        )

    # APPROVED
    cov = next((f for f in findings if f["check"] == "COVERAGE_LIMITS"), None)
    network_note = ""
    if cov and cov.get("in_network"):
        disc = cov.get("network_discount_percent", 0)
        if disc:
            network_note = f" In-network discount of {disc}% applied."
    return (
        f"All policy checks passed. ₹{approved_amount:,.0f} approved after ₹{copay_amount:,.0f} co-pay.{network_note}"
    )


# ---------------------------------------------------------------------------
# Main deterministic orchestrator — registered as a function tool in root agent
# ---------------------------------------------------------------------------

def run_policy_decision(
    member_id: str,
    policy_id: str,
    claim_category: str,
    treatment_date: str,
    claimed_amount: float,
    has_pre_authorization: bool,
    relationship_claim_type: str,
    patient_member_id: str | None,
    extracted_documents_json: str,
    claims_history_json: str = "[]",
) -> dict[str, Any]:
    """
    Run all seven policy-rule checks in sequence and return a PolicyDecision dict.

    This is a deterministic Python function — no LLM is involved. The same inputs
    always produce the same output.

    Args:
        member_id: Employee's policy ID, e.g. 'EMP001'.
        policy_id: Policy identifier.
        claim_category: CONSULTATION | DIAGNOSTIC | PHARMACY | DENTAL | VISION | ALTERNATIVE_MEDICINE.
        treatment_date: Treatment date in YYYY-MM-DD.
        claimed_amount: Amount claimed by the member.
        has_pre_authorization: True if the member obtained pre-authorization.
        relationship_claim_type: 'SELF' or 'DEPENDENT'.
        patient_member_id: Dependent's member ID if relationship_claim_type is DEPENDENT, else None.
        extracted_documents_json: JSON-serialised list of DocumentExtractionResult objects
            from the DOCUMENT_EXTRACTION stage.

    Returns:
        dict matching the PolicyDecision schema with keys: decision, approved_amount,
        copay_amount, reason, confidence_score, rule_findings.
    """
    # Parse claims history (prior claims supplied by the intake input)
    try:
        claims_history: list[dict] = json.loads(claims_history_json) if claims_history_json else []
    except (json.JSONDecodeError, TypeError):
        claims_history = []

    # Parse extraction results
    try:
        extracted_docs: list[dict] = json.loads(extracted_documents_json) if extracted_documents_json else []
    except (json.JSONDecodeError, TypeError):
        extracted_docs = []

    fields = _parse_extraction_fields(extracted_docs)
    diagnosis: str = fields["diagnosis"]
    procedures: str = fields["procedures"]
    hospital_name: str | None = fields["hospital_name"]
    bill_total_amount: float | None = fields["bill_total_amount"]
    line_items_json: str = fields["line_items_json"]
    tests_ordered_json: str = fields["tests_ordered_json"]

    decision = "APPROVED"
    approved_amount = 0.0
    copay_amount = 0.0
    covered_bill_amount: float | None = None
    findings: list[dict] = []

    # --- Tool 0: Dependent coverage ---
    r = check_dependent_coverage(member_id, patient_member_id, relationship_claim_type)
    findings.append(r)
    if r["result"] == "FAIL":
        decision = _raise_decision(decision, "REJECTED")

    # --- Tool 1: Member eligibility ---
    r = check_member_eligibility(member_id, treatment_date)
    findings.append(r)
    if r["result"] == "FAIL":
        decision = _raise_decision(decision, "REJECTED")

    # Short-circuit: if already REJECTED, run remaining tools for trace but skip amount logic
    rejected_early = decision == "REJECTED"

    # --- Tool 2: Waiting periods ---
    r = check_waiting_periods(member_id, treatment_date, diagnosis)
    findings.append(r)
    if r["result"] == "FAIL":
        decision = _raise_decision(decision, "REJECTED")
    elif r["result"] == "INCONCLUSIVE" and r.get("pre_existing_flag"):
        decision = _raise_decision(decision, "MANUAL_REVIEW")

    # --- Tool 3: Exclusions ---
    r = check_exclusions(claim_category, diagnosis, procedures, line_items_json)
    findings.append(r)
    if r["result"] == "FAIL":
        if r.get("full_exclusion"):
            decision = _raise_decision(decision, "REJECTED")
        else:
            covered_bill_amount = r.get("covered_amount")
            decision = _raise_decision(decision, "PARTIAL")

    # --- Tool 4: Pre-authorization ---
    r = check_pre_authorization(claim_category, tests_ordered_json, claimed_amount, has_pre_authorization)
    findings.append(r)
    if r["result"] == "FAIL":
        decision = _raise_decision(decision, "REJECTED")

    # --- Tool 5: Coverage limits ---
    r = check_coverage_limits(
        member_id, claim_category, claimed_amount,
        bill_total_amount, hospital_name, covered_bill_amount,
        patient_member_id,
    )
    findings.append(r)
    if r["result"] == "FAIL":
        decision = _raise_decision(decision, "REJECTED")
    elif decision not in ("REJECTED",) and not rejected_early:
        approved_amount = float(r.get("approved_amount", 0.0))
        copay_amount = float(r.get("copay_amount", 0.0))

    # --- Tool 6: Fraud signals ---
    r = check_fraud_signals(member_id, treatment_date, claimed_amount, claims_history)
    findings.append(r)
    if r["result"] == "MANUAL_REVIEW":
        decision = _raise_decision(decision, "MANUAL_REVIEW")

    # Zero out amounts on rejection
    if decision == "REJECTED":
        approved_amount = 0.0
        copay_amount = 0.0

    # Confidence score
    inconclusive_count = sum(1 for f in findings if f["result"] == "INCONCLUSIVE")
    confidence_score = round(max(0.3, 1.0 - 0.15 * inconclusive_count), 2)
    if confidence_score <= 0.45 and decision not in ("REJECTED",):
        decision = _raise_decision(decision, "MANUAL_REVIEW")

    reason = _build_reason(findings, decision, approved_amount, copay_amount)

    return PolicyDecision(
        decision=decision,
        approved_amount=approved_amount,
        copay_amount=copay_amount,
        reason=reason,
        confidence_score=confidence_score,
        rule_findings=[
            RuleFinding(
                check=f["check"],
                result=f["result"],
                detail=f["detail"],
                data={k: v for k, v in f.items() if k not in ("check", "result", "detail")},
            )
            for f in findings
        ],
    ).model_dump()
