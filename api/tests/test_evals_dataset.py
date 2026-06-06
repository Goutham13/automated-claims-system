import json

from evals import dataset


def test_resolve_by_file_name_then_file_id(tmp_path, monkeypatch):
    case_dir = tmp_path / "mock_claim_documents" / "TC001"
    case_dir.mkdir(parents=True)
    (case_dir / "rx.jpg").write_bytes(b"x")
    (case_dir / "F008_bill.jpg").write_bytes(b"x")
    monkeypatch.setattr(dataset, "MOCK_DIR", tmp_path / "mock_claim_documents")
    # by file_name
    p = dataset.resolve_doc_file("TC001", {"file_id": "F001", "file_name": "rx.jpg"})
    assert p and p.name == "rx.jpg"
    # by file_id prefix (no file_name)
    p2 = dataset.resolve_doc_file("TC001", {"file_id": "F008"})
    assert p2 and p2.name == "F008_bill.jpg"
    # missing
    assert dataset.resolve_doc_file("TC001", {"file_id": "F999"}) is None


def test_load_cases_joins_fixture_text(tmp_path, monkeypatch):
    tc = {"version": 1, "test_cases": [{
        "case_id": "TC001", "case_name": "Case", "description": "",
        "input": {"claim_category": "CONSULTATION",
                  "documents": [{"file_id": "F001", "actual_type": "PRESCRIPTION", "file_name": "rx.jpg"}]},
        "expected": {"decision": None}}]}
    (tmp_path / "test_cases.json").write_text(json.dumps(tc))
    fx = tmp_path / "evals" / "fixtures" / "TC001"
    fx.mkdir(parents=True)
    (fx / "F001.txt").write_text("PRESCRIPTION TEXT")
    monkeypatch.setattr(dataset, "TEST_CASES", tmp_path / "test_cases.json")
    monkeypatch.setattr(dataset, "FIXTURES", tmp_path / "evals" / "fixtures")
    cases = dataset.load_cases()
    assert len(cases) == 1
    doc = cases[0].documents[0]
    assert doc.actual_type == "PRESCRIPTION"
    assert doc.ocr_text == "PRESCRIPTION TEXT"
    assert cases[0].claim_category == "CONSULTATION"
