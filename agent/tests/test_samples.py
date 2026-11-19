"""The committed sample outputs in docs/samples stay valid and safe to publish."""

import json
from pathlib import Path

from agent.case_file import validate

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "samples"


def test_sample_case_files_validate():
    files = sorted((SAMPLES / "cases").glob("C-*.json"))
    assert [f.stem for f in files] == ["C-001", "C-016", "C-019"]
    for f in files:
        case = json.loads(f.read_text(encoding="utf-8"))
        assert case["case_id"] == f.stem
        assert validate(case) == [], f.name
        assert all(item["source"] for item in case["evidence"])


def test_sample_usage_log_has_no_local_paths():
    text = (SAMPLES / "usage.sample.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert rows
    assert "C:\\" not in text and "Users" not in text
    for row in rows:
        assert row["task_id"].startswith("C-")
        assert row["total_tokens"] > 0


def test_samples_never_mention_the_answer_key():
    for f in SAMPLES.rglob("*"):
        if f.is_file() and f.suffix in {".json", ".jsonl"}:
            text = f.read_text(encoding="utf-8")
            assert "planted_cases" not in text and "PC-" not in text, f.name
