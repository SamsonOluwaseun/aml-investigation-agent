"""Bank tool tests. A tiny hand-built bank, no model, no network."""

import json
import re
import sqlite3
from pathlib import Path

import pytest

from tools import bank_tools, case_store

SCHEMA = """
CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, occupation TEXT,
  declared_income REAL, risk_rating TEXT, country TEXT, onboarded_on TEXT);
CREATE TABLE accounts (account_id TEXT PRIMARY KEY, customer_id TEXT, type TEXT, opened_on TEXT, status TEXT);
CREATE TABLE counterparties (counterparty_account TEXT PRIMARY KEY, name TEXT, country TEXT, bank TEXT);
CREATE TABLE transactions (txn_id TEXT PRIMARY KEY, account_id TEXT, counterparty_account TEXT,
  amount_gbp REAL, direction TEXT, channel TEXT, country TEXT, timestamp TEXT);
CREATE TABLE screening_list (name TEXT, list_type TEXT, country TEXT);
CREATE TABLE adverse_media (name TEXT, headline TEXT, date TEXT);
CREATE TABLE planted_cases (case_id TEXT, customer_id TEXT, typology TEXT, notes TEXT, is_suspicious INTEGER);
CREATE TABLE alerts (case_id TEXT PRIMARY KEY, customer_id TEXT UNIQUE, score REAL, typologies TEXT,
  hits TEXT, status TEXT, window_start TEXT, window_end TEXT, created_at TEXT, updated_at TEXT);
"""


@pytest.fixture
def bank(tmp_path, monkeypatch):
    db = tmp_path / "bank.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?)", [
        ("CU-0001", "FAKE Customer 0001", "Synthetic nurse", 36000, "Low", "GB", "2024-01-01"),
        ("CU-0002", "FAKE Customer 0002", "Synthetic teacher", 30000, "Low", "GB", "2024-01-01"),
    ])
    conn.executemany("INSERT INTO accounts VALUES (?,?,?,?,?)", [
        ("FAKE-AC-0001-1", "CU-0001", "current", "2024-01-01", "active"),
        ("FAKE-AC-0002-1", "CU-0002", "current", "2024-01-01", "active"),
    ])
    conn.executemany("INSERT INTO counterparties VALUES (?,?,?,?)", [
        ("FAKE-CASH-BRANCH", "FAKE Cash Deposit", "GB", "FAKE Bank"),
        ("FAKE-EXT-098", "FAKE Nebula Trading", "GB", "FAKE Bank"),
    ])
    rows = [(f"T-{n:07d}", "FAKE-AC-0001-1", "FAKE-CASH-BRANCH", 9000 + n, "in", "cash", "GB",
             f"2026-10-{n:02d}T10:00:00") for n in range(1, 29)]
    rows.append(("T-0000099", "FAKE-AC-0002-1", "FAKE-EXT-098", 500, "out", "transfer", "GB", "2026-10-03T10:00:00"))
    conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT INTO screening_list VALUES ('FAKE Nebula Trading', 'sanctions', 'GB')")
    conn.execute("INSERT INTO adverse_media VALUES ('FAKE Nebula Trading', 'FICTIONAL headline', '2026-10-01')")
    conn.execute("INSERT INTO planted_cases VALUES ('PC-001', 'CU-0001', 'structuring', 'SECRET-ANSWER-KEY', 1)")
    hits = [{"typology": "structuring", "score": 0.9, "txn_ids": ["T-0000001", "T-0000002"]}]
    conn.execute("INSERT INTO alerts VALUES ('C-001','CU-0001',0.9,?,?,'open','2026-09-29','2026-10-28','x','x')",
                 (json.dumps(["structuring"]), json.dumps(hits)))
    conn.execute("INSERT INTO alerts VALUES ('C-002','CU-0002',0.6,?,?,'open','2026-09-29','2026-10-28','x','x')",
                 (json.dumps(["high_risk_link"]), json.dumps([])))
    conn.commit()
    conn.close()
    monkeypatch.setenv("AML_BANK_DB", str(db))
    monkeypatch.setenv("AML_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("AML_CASES_DIR", str(tmp_path / "cases"))
    return tmp_path


def audit_lines(bank):
    return [json.loads(line) for line in (bank / "audit.jsonl").read_text().splitlines()]


def test_list_alerts_sorted_and_audited(bank):
    result = bank_tools.list_alerts("QUEUE")
    assert [a["case_id"] for a in result["alerts"]] == ["C-001", "C-002"]
    assert audit_lines(bank)[-1]["case_id"] == "QUEUE"
    assert audit_lines(bank)[-1]["tool"] == "list_alerts"


def test_every_tool_audits_with_case_id(bank):
    calls = [
        lambda: bank_tools.get_alert("C-001"),
        lambda: bank_tools.get_customer("C-001", customer_id="CU-0001"),
        lambda: bank_tools.get_accounts("C-001", customer_id="CU-0001"),
        lambda: bank_tools.get_transactions("C-001", account_id="FAKE-AC-0001-1", date_from="2026-10-01", date_to="2026-10-31"),
        lambda: bank_tools.get_counterparties("C-001", account_id="FAKE-AC-0001-1"),
        lambda: bank_tools.screen_name("C-001", name="FAKE Nebula Trading"),
    ]
    for call in calls:
        assert "error" not in call()
    lines = audit_lines(bank)
    assert len(lines) == len(calls)
    assert all(line["case_id"] == "C-001" for line in lines)


def test_unknown_case_is_refused_and_audited(bank):
    assert "error" in bank_tools.get_alert("C-999")
    assert "error" in bank_tools.get_alert("PC-001")
    assert audit_lines(bank)[-1]["error"]


def test_scope_limited_to_case_customer(bank):
    assert "error" in bank_tools.get_customer("C-001", customer_id="CU-0002")
    assert "error" in bank_tools.get_transactions("C-001", account_id="FAKE-AC-0002-1",
                                                  date_from="2026-10-01", date_to="2026-10-31")


def test_transactions_capped(bank, monkeypatch):
    monkeypatch.setattr(bank_tools, "MAX_TRANSACTIONS", 5)
    result = bank_tools.get_transactions("C-001", account_id="FAKE-AC-0001-1", date_from="2026-10-01", date_to="2026-10-31")
    assert result["returned"] == 5 and result["total"] == 28 and result["truncated"]
    assert result["sum_in_gbp"] == sum(9000 + n for n in range(1, 29))


def test_default_cap_is_200():
    assert bank_tools.MAX_TRANSACTIONS == 200


def test_screen_name_exact_and_close(bank):
    exact = bank_tools.screen_name("C-002", name="FAKE Nebula Trading")
    assert exact["screening"][0]["match"] == "exact"
    close = bank_tools.screen_name("C-002", name="FAKE Nebula Trading Supplies")
    assert close["screening"][0]["match"] == "close"


def test_read_tools_cannot_write(bank):
    with pytest.raises(sqlite3.OperationalError):
        with bank_tools._connect() as conn:
            conn.execute("DELETE FROM alerts")


def test_answer_key_never_reachable(bank):
    """No SQL in the tools mentions the answer key, and no result contains it."""
    for module in (bank_tools, case_store):
        source = Path(module.__file__).read_text()
        assert "planted" not in source.lower()
    outputs = [
        bank_tools.list_alerts("QUEUE"),
        bank_tools.get_alert("C-001"),
        bank_tools.get_customer("C-001", customer_id="CU-0001"),
        bank_tools.screen_name("C-001", name="FAKE Customer 0001"),
        bank_tools.get_transactions("C-001", account_id="FAKE-AC-0001-1", date_from="2026-01-01", date_to="2026-12-31"),
    ]
    assert "SECRET-ANSWER-KEY" not in json.dumps(outputs)
    assert "PC-001" not in json.dumps(outputs)


def good_case(**overrides):
    case = {
        "case_id": "C-001", "customer_id": "CU-0001", "risk_rating": "High",
        "typologies": ["structuring"], "summary": "Repeated cash deposits just under £10,000.",
        "evidence": [
            {"claim": "Cash deposits of £9,001 and £9,002", "source": ["T-0000001", "T-0000002"]},
            {"claim": "An uncited claim", "source": []},
            {"claim": "A claim citing a made-up record", "source": ["T-9999999"]},
        ],
        "innocent_explanations": ["Could be business takings"], "gaps": ["No source of funds"],
        "suggested_action": "Escalate", "status": "Final",
    }
    case.update(overrides)
    return case


def test_save_case_file_drops_uncited_claims(bank):
    result = case_store.save_case_file("C-001", case_json=json.dumps(good_case()))
    assert result["saved"] and result["evidence_kept"] == 1
    saved = json.loads((bank / "cases" / "C-001.json").read_text(encoding="utf-8"))
    assert saved["status"] == "Draft for human review"
    assert [e["source"] for e in saved["evidence"]] == [["T-0000001", "T-0000002"]]


def test_audit_does_not_copy_whole_case_file(bank):
    case_store.save_case_file("C-001", case_json=json.dumps(good_case()))
    line = audit_lines(bank)[-1]
    assert line["tool"] == "save_case_file" and line["returned"]["saved"] is True
    assert len(line["args"]["case_json"]) < 260


def test_save_case_file_rejects_mismatch(bank):
    assert "error" in case_store.save_case_file("C-001", case_json=json.dumps(good_case(case_id="C-002")))
    assert "error" in case_store.save_case_file("C-001", case_json=json.dumps(good_case(customer_id="CU-0002")))
    assert "error" in case_store.save_case_file("C-001", case_json="not json")
    assert not (bank / "cases" / "C-001.json").exists()


def test_server_registers_eight_tools_with_case_id_first():
    import asyncio
    from tools import server

    tools = asyncio.run(server.server.list_tools())
    names = {t.name for t in tools}
    assert names == {"list_alerts", "get_alert", "get_customer", "get_accounts", "get_transactions",
                     "get_counterparties", "screen_name", "save_case_file"}
    for tool in tools:
        assert next(iter(tool.input_schema["properties"])) == "case_id"
        assert re.match(r"^\w+$", tool.name)
