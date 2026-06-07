"""Type-aware field comparison for fair extraction agreement.

`compare_value(field, a, b)` returns one of: "exact" | "normalized" | "mismatch".
- exact: identical raw values
- normalized: semantically equal after type-aware normalization (case/date/number/order/fuzzy)
- mismatch: genuinely different
"""

from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

_FUZZY = 0.9
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y")


def _norm_str(s: str) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", str(s).lower())).strip()


def _as_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", v)
        if m:
            return float(v)
    return None


def _parse_date(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _canon_genderish(v: Any) -> str | None:
    s = str(v).strip().lower()
    if s in ("m", "male"):
        return "m"
    if s in ("f", "female"):
        return "f"
    if s in ("true", "false"):
        return s
    return None


def _string_match(a: str, b: str) -> str:
    if a == b:
        return "exact"
    na, nb = _norm_str(a), _norm_str(b)
    if not na and not nb:
        return "normalized"
    if na == nb:
        return "normalized"
    if na and nb and (na in nb or nb in na):
        return "normalized"
    if na and nb and SequenceMatcher(None, na, nb).ratio() >= _FUZZY:
        return "normalized"
    return "mismatch"


def _list_of_str_match(a: list, b: list) -> str:
    if not a and not b:
        return "exact"
    sa, sb = {_norm_str(x) for x in a}, {_norm_str(x) for x in b}
    if not sa and not sb:
        return "normalized"
    jacc = len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0
    return "normalized" if jacc >= _FUZZY else "mismatch"


def _item_key(d: dict) -> str:
    for k in ("medicine_name", "description", "test_name", "name"):
        if d.get(k):
            return _norm_str(d[k])
    for v in d.values():  # first string-ish field
        if isinstance(v, str) and v.strip():
            return _norm_str(v)
    return ""


def _dict_field_agreement(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    ok = sum(1 for k in keys if compare_value(k, a.get(k), b.get(k)) != "mismatch")
    return ok / len(keys)


def _list_of_dict_match(a: list, b: list) -> str:
    if not a and not b:
        return "exact"
    if not a or not b:
        return "mismatch"
    remaining = list(b)
    matched_scores: list[float] = []
    for ref_item in a:
        rk = _item_key(ref_item)
        best, best_score = None, -1.0
        for cand_item in remaining:
            if _string_match(rk, _item_key(cand_item)) != "mismatch":
                score = _dict_field_agreement(ref_item, cand_item)
                if score > best_score:
                    best, best_score = cand_item, score
        if best is not None and best_score >= 0.7:
            matched_scores.append(best_score)
            remaining.remove(best)
    coverage = len(matched_scores) / max(len(a), len(b))
    return "normalized" if coverage >= _FUZZY else "mismatch"


def compare_value(field: str, a: Any, b: Any) -> str:
    if a is None and b is None:
        return "exact"
    if a is None or b is None:
        return "mismatch"

    # numbers
    na, nb = _as_number(a), _as_number(b)
    if na is not None and nb is not None:
        if type(a) is type(b) and a == b:
            return "exact"
        return "normalized" if abs(na - nb) < 1e-2 else "mismatch"

    # lists
    if isinstance(a, list) and isinstance(b, list):
        if a and isinstance(a[0], dict) or b and isinstance(b[0], dict):
            return _list_of_dict_match(a, b)
        return _list_of_str_match(a, b)

    # bool / gender-ish
    ca, cb = _canon_genderish(a), _canon_genderish(b)
    if ca is not None and cb is not None:
        if a == b:
            return "exact"
        return "normalized" if ca == cb else "mismatch"

    # dates (by field name hint or parseability)
    if "date" in field.lower() or (_parse_date(a) and _parse_date(b)):
        da, db = _parse_date(a), _parse_date(b)
        if da and db:
            if a == b:
                return "exact"
            return "normalized" if da == db else "mismatch"

    # strings (fallback)
    return _string_match(str(a), str(b))
