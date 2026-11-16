import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

SPEC = importlib.util.spec_from_file_location("scorecard", Path(__file__).parents[1] / "score.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.fixture
def inputs(tmp_path):
    db = tmp_path / "bank.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE planted_cases (case_id, customer_id, typology, notes, is_suspicious);
            CREATE TABLE alerts (case_id, customer_id, status);
            CREATE TABLE customers (customer_id);
            CREATE TABLE accounts (account_id);
            CREATE TABLE transactions (txn_id);
            CREATE TABLE counterparties (counterparty_account);
            CREATE TABLE screening_list (name);
            CREATE TABLE adverse_media (name);
            INSERT INTO transactions VALUES ('T-20261116-0001');
            INSERT INTO customers VALUES ('CU-0001');
            INSERT INTO accounts VALUES ('FAKE-AC-0001-1');
            INSERT INTO counterparties VALUES ('FAKE-EXT-001'), ('FAKE-CASH-BRANCH');
            INSERT INTO screening_list VALUES ('FAKE screening');
            INSERT INTO adverse_media VALUES ('FAKE media');
        """)
        conn.executemany("INSERT INTO planted_cases VALUES (?, ?, 'structuring', 'PRIVATE NOTES', 1)",
                         [(f"PC-{i:03}", f"CU-{i:04}") for i in range(1, 16)])
        conn.execute("INSERT INTO planted_cases VALUES ('PC-099', 'CU-0099', 'structuring', 'PRIVATE NOTES', 0)")
        conn.executemany("INSERT INTO alerts VALUES (?, ?, 'open')", [("C-888", "CU-0001"), ("C-002", "CU-0002"), ("C-099", "CU-0099")])
    cases = tmp_path / "cases"
    cases.mkdir()
    return db, cases, tmp_path / "usage.jsonl"


def write_case(case_id, cases, customer, risk="High", typologies=None, sources=None):
    (cases / f"{case_id}.json").write_text(json.dumps({
        "case_id": case_id, "customer_id": customer, "risk_rating": risk,
        "suggested_action": "Escalate",
        "typologies": ["structuring"] if typologies is None else typologies,
        "evidence": [{"claim": "Synthetic claim", "source": sources or []}],
        "saved_at": "2026-11-16T12:00:00+00:00",
    }), encoding="utf-8")


def test_six_measures(inputs):
    db, cases, usage = inputs
    sources = ['T-20261116-0001', 'CU-0001', 'FAKE-AC-0001-1', 'FAKE-EXT-001',
               'FAKE-CASH-BRANCH', 'SL-1', 'AM-1', 'T-missing', 'unknown', 'SL-99']
    write_case("C-888", cases, "CU-0001", sources=sources)
    write_case("C-002", cases, "CU-0002", risk="Low", typologies=[])
    write_case("C-099", cases, "CU-0099")
    rows = [dict(task_id="C-888", agent=agent, parent_run=parent, total_tokens=tokens)
            for agent, parent, tokens in [('investigate', None, 100), ('child', 'R-1', 200),
                                          ('investigate', None, 50), ('investigate', 'R-1', 50)]]
    usage.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    report = module.score(*inputs)
    assert report['catch_rate'] == {'caught': 1, 'out_of': 15, 'partial': True}
    assert report['right_typology']['correct'] == 1
    assert report['false_alarms'] == 1
    assert report['coverage']['suspicious'] == {'total': 15, 'alerted': 2, 'investigated': 2}
    assert report['coverage']['look_alikes']['investigated'] == 1
    assert report['citations']['existing'] == 7
    assert report['citations']['total'] == 10
    assert len(report['citations']['missing']) == 3
    assert report['per_case']['C-888']['amplification'] == pytest.approx(400 / 150)
    assert report['per_case']['C-002']['total_tokens'] == 0
    assert report['per_case']['C-002']['amplification'] is None
    assert report['tokens']['mean'] == 400
    assert report['tokens']['median'] == 400
    assert report['tokens']['count'] == 1
    output = module.render(report, markdown=True)
    assert 'PRIVATE NOTES' not in output and 'PC-' not in output and 'CU-' not in output
    assert 'investigated 3 of 3 open alerts' in output
    assert 'Generated on: 2026-11-16' in output
    assert 'Missing source: C-888: T-missing' in output


def test_empty_inputs(inputs):
    report = module.score(*inputs)
    assert report['catch_rate']['caught'] == report['right_typology']['correct'] == 0
    assert report['catch_rate']['partial']
    assert report['citations']['share'] == 0
    assert report['tokens'] == {'count': 0, 'mean': 0, 'median': 0}
    assert report['per_case'] == {}
    assert 'Usage log missing' in module.render(report)
    assert 'investigated 0 of 3 open alerts' in module.render(report)


def test_complete_coverage_and_no_alert(inputs):
    db, cases, usage = inputs
    for i in range(1, 16):
        write_case(f'C-{i:03}', cases, f'CU-{i:04}')
    report = module.score(*inputs)
    assert not report['catch_rate']['partial']
    assert report['catch_rate']['caught'] == 2  # Unalerted planted cases are not caught.
    assert report['right_typology']['correct'] == 15
    assert 'Right typology | 15/15 | >= 12/15 | yes' in module.render(report)


def test_usage_only_and_zero_top_level(inputs):
    db, cases, usage = inputs
    usage.write_text(json.dumps(dict(task_id='C-777', agent='child', parent_run='R-1', total_tokens=30)), encoding='utf-8')
    report = module.score(*inputs)
    assert report['tokens']['mean'] == 30
    assert report['per_case']['C-777']['amplification'] is None
    assert report['generated_on'].startswith('unavailable')


def test_render_structure_outcomes_and_met(inputs):
    db, cases, usage = inputs
    write_case("C-001", cases, "CU-0001")
    write_case("C-099", cases, "CU-0099", risk="Low")
    write_case("C-999", cases, "CU-0999")
    report = module.score(*inputs)
    output = module.render(report, markdown=True)
    assert output.startswith("# Evaluation scorecard\n")
    assert "## Measures\n\n| Measure | Result | Target | Met |" in output
    assert "| --- | --- | --- | --- |" in output
    assert "## Per case" in output and "## Notes" in output
    case_lines = [line for line in output.splitlines() if line.startswith("- C-")]
    assert len(case_lines) == 3
    look_alike = next(line for line in case_lines if "C-099" in line)
    assert "look-alike" in look_alike and "not a false alarm" in look_alike
    assert "right typology" not in look_alike
    assert "risk_rating Low; suggested_action Escalate" in look_alike
    assert "no usage logged" in look_alike
    assert any("not in answer key" in line and "not scored" in line for line in case_lines)
    measures = {parts[1].strip(): parts[4].strip() for line in output.splitlines()
                if line.startswith("| ") and (parts := line.split("|"))[1].strip()
                in {"Catch rate", "False alarms", "Citation check", "Right typology", "Tokens per case", "Handoff amplification"}}
    assert measures == {"Catch rate": "partial", "False alarms": "yes", "Citation check": "no",
                        "Right typology": "partial", "Tokens per case": "recorded", "Handoff amplification": "recorded"}
    assert not module.render(report).startswith("#")
    write_case("C-099", cases, "CU-0099", risk="High")
    assert "; false alarm;" in module.render(module.score(*inputs))
