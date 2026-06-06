import json

from evals import run as runmod


def test_write_and_load_result(tmp_path):
    result = {"model": "m", "created_at": "t", "dimensions": {}}
    p = runmod.write_result(result, tmp_path, baseline=True)
    assert p.exists()
    base = tmp_path / "baseline.json"
    assert base.exists()
    assert json.loads(base.read_text())["model"] == "m"


def test_write_result_sanitizes_model_name(tmp_path):
    result = {"model": "qwen2.5vl:7b", "created_at": "t", "dimensions": {}}
    p = runmod.write_result(result, tmp_path)
    assert ":" not in p.name and "/" not in p.name
    assert not (tmp_path / "baseline.json").exists()  # baseline not requested
