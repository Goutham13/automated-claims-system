from evals.field_compare import compare_value


def test_none_handling():
    assert compare_value("x", None, None) == "exact"
    assert compare_value("x", None, "v") == "mismatch"
    assert compare_value("x", "v", None) == "mismatch"


def test_numbers():
    assert compare_value("total_amount", 4200, 4200) == "exact"
    assert compare_value("total_amount", 4200, 4200.0) == "normalized"
    assert compare_value("total_amount", 4200, "4200") == "normalized"
    assert compare_value("total_amount", 4200, 4300) == "mismatch"


def test_dates():
    assert compare_value("bill_date", "2024-11-01", "2024-11-01") == "exact"
    assert compare_value("bill_date", "2024-11-01", "01/11/2024") == "normalized"
    assert compare_value("bill_date", "2024-11-01", "2024-12-01") == "mismatch"


def test_strings_case_and_containment_and_fuzzy():
    assert compare_value("patient_name", "Rajesh Kumar", "Rajesh Kumar") == "exact"
    assert compare_value("diagnosis_primary", "Viral Fever", "viral fever") == "normalized"
    assert compare_value("medicine", "Paracetamol", "Tab Paracetamol") == "normalized"  # containment
    assert compare_value("patient_name", "Rajesh Kumar", "Arjun Mehta") == "mismatch"


def test_gender_canonicalization():
    assert compare_value("patient_gender", "M", "Male") == "normalized"
    assert compare_value("patient_gender", "M", "F") == "mismatch"


def test_list_of_strings_jaccard():
    assert compare_value("diagnosis_secondary", ["Fever", "Cough"], ["cough", "fever"]) == "normalized"
    assert compare_value("diagnosis_secondary", [], []) == "exact"
    assert compare_value("diagnosis_secondary", ["Fever"], ["Diabetes"]) == "mismatch"


def test_list_of_dicts_order_insensitive():
    ref = [{"medicine_name": "Tab Paracetamol", "strength_or_dosage": "650mg"},
           {"medicine_name": "Tab Vitamin C", "strength_or_dosage": "500mg"}]
    cand_reordered = [{"medicine_name": "tab vitamin c", "strength_or_dosage": "500mg"},
                      {"medicine_name": "tab paracetamol", "strength_or_dosage": "650mg"}]
    assert compare_value("medicines", ref, cand_reordered) == "normalized"
    cand_wrong = [{"medicine_name": "Aspirin", "strength_or_dosage": "100mg"}]
    assert compare_value("medicines", ref, cand_wrong) == "mismatch"
