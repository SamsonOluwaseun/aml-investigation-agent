"""Tests for the AML investigator review screen data functions and Streamlit app.

All tests use temporary in-memory or directory copies, ensuring bank/bank.db
is never modified.
"""

from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Generator
import pytest

from ui.data import (
    API_EQUIVALENT_RATES_PER_M,
    calculate_api_cost,
    ensure_decisions_table,
    list_decisions,
    load_case,
    load_queue,
    load_usage_stats,
    lookup_source,
    save_decision,
)


def create_test_db(db_path: Path) -> None:
    """Populate a temporary SQLite database with test schema and records."""
    with closing(sqlite3.connect(str(db_path))) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE customers (
                    customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, occupation TEXT NOT NULL,
                    declared_income REAL NOT NULL CHECK(declared_income > 0),
                    risk_rating TEXT NOT NULL, country TEXT NOT NULL, onboarded_on TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE accounts (
                    account_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
                    type TEXT NOT NULL, opened_on TEXT NOT NULL, status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE counterparties (
                    counterparty_account TEXT PRIMARY KEY, name TEXT NOT NULL,
                    country TEXT NOT NULL, bank TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE transactions (
                    txn_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts,
                    counterparty_account TEXT NOT NULL REFERENCES counterparties,
                    amount_gbp REAL NOT NULL CHECK(amount_gbp > 0),
                    direction TEXT NOT NULL CHECK(direction IN ('in', 'out')),
                    channel TEXT NOT NULL, country TEXT NOT NULL, timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE screening_list (
                    name TEXT NOT NULL, list_type TEXT NOT NULL, country TEXT NOT NULL,
                    PRIMARY KEY(name, list_type)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE adverse_media (
                    name TEXT NOT NULL, headline TEXT NOT NULL, date TEXT NOT NULL,
                    PRIMARY KEY(name, headline, date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE alerts (
                    case_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL UNIQUE REFERENCES customers,
                    score REAL NOT NULL,
                    typologies TEXT NOT NULL,
                    hits TEXT NOT NULL,
                    status TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Insert sample data
            conn.execute(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("CU-0001", "Alice Smith", "Engineer", 85000.0, "Low", "GB", "2024-01-15"),
            )
            conn.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                ("FAKE-AC-0001-1", "CU-0001", "current", "2024-01-15", "active"),
            )
            conn.execute(
                "INSERT INTO counterparties VALUES (?, ?, ?, ?)",
                ("FAKE-EXT-101", "Global Trade Ltd", "GB", "Demo Bank"),
            )
            conn.execute(
                "INSERT INTO counterparties VALUES (?, ?, ?, ?)",
                ("FAKE-CASH-BRANCH", "Cash Deposit Branch", "GB", "Demo Bank"),
            )
            conn.execute(
                "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("T-1001", "FAKE-AC-0001-1", "FAKE-EXT-101", 9500.0, "out", "transfer", "GB", "2026-10-01T10:00:00"),
            )
            conn.execute(
                "INSERT INTO screening_list VALUES (?, ?, ?)",
                ("Global Trade Ltd", "sanctions", "GB"),
            )
            conn.execute(
                "INSERT INTO adverse_media VALUES (?, ?, ?)",
                ("Global Trade Ltd", "Company investigated for money laundering", "2026-09-20"),
            )


def test_sort_order():
    """Verify queue is sorted High > Medium > Low > not investigated, then score descending, then case_id."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        db_path = tdp / "bank.db"
        cases_dir = tdp / "cases"
        cases_dir.mkdir()
        usage_path = tdp / "usage.jsonl"
        usage_path.write_text("", encoding="utf-8")

        create_test_db(db_path)

        # Create alerts
        alerts_data = [
            ("C-001", "CU-0001", 0.90, '["structuring"]', "open"),
            ("C-002", "CU-0002", 0.98, '["high_risk_link"]', "open"),
            ("C-003", "CU-0003", 0.85, '["rapid_pass_through"]', "open"),
            ("C-004", "CU-0004", 0.95, '["fan_in_fan_out"]', "open"),
            ("C-005", "CU-0005", 0.70, '["structuring"]', "open"),
            ("C-006", "CU-0006", 0.99, '["structuring"]', "open"),  # no case file
            ("C-007", "CU-0007", 0.50, '["structuring"]', "open"),  # no case file
            ("C-008", "CU-0008", 0.50, '["structuring"]', "open"),  # no case file
            ("C-009", "CU-0009", 0.99, '["structuring"]', "closed"), # closed -> excluded
        ]

        with closing(sqlite3.connect(str(db_path))) as conn:
            with conn:
                for row in alerts_data:
                    # add dummy customer
                    conn.execute(
                        "INSERT OR IGNORE INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (row[1], f"Name {row[1]}", "Occ", 50000.0, "Low", "GB", "2024-01-01"),
                    )
                    conn.execute(
                        """
                        INSERT INTO alerts (case_id, customer_id, score, typologies, hits, status,
                                            window_start, window_end, created_at, updated_at)
                        VALUES (?, ?, ?, ?, '[]', ?, '2026-09-01', '2026-10-01', '2026-10-01', '2026-10-01')
                        """,
                        row,
                    )

        # Create case files
        (cases_dir / "C-001.json").write_text(json.dumps({"case_id": "C-001", "risk_rating": "High"}), encoding="utf-8")
        (cases_dir / "C-002.json").write_text(json.dumps({"case_id": "C-002", "risk_rating": "High"}), encoding="utf-8")
        (cases_dir / "C-003.json").write_text(json.dumps({"case_id": "C-003", "risk_rating": "Medium"}), encoding="utf-8")
        (cases_dir / "C-004.json").write_text(json.dumps({"case_id": "C-004", "risk_rating": "Medium"}), encoding="utf-8")
        (cases_dir / "C-005.json").write_text(json.dumps({"case_id": "C-005", "risk_rating": "Low"}), encoding="utf-8")
        # C-006, C-007, C-008 have no case files

        queue = load_queue(db_path, cases_dir, usage_path)
        assert len(queue) == 8  # C-009 is closed so excluded

        ordered_case_ids = [item["case_id"] for item in queue]
        expected_order = [
            "C-002",  # High, score 0.98
            "C-001",  # High, score 0.90
            "C-004",  # Medium, score 0.95
            "C-003",  # Medium, score 0.85
            "C-005",  # Low, score 0.70
            "C-006",  # Not investigated, score 0.99
            "C-007",  # Not investigated, score 0.50 (tie-break C-007 < C-008)
            "C-008",  # Not investigated, score 0.50
        ]
        assert ordered_case_ids == expected_order

        # Verify not investigated labels
        assert queue[5]["risk_rating"] == "Not investigated yet"
        assert queue[6]["risk_rating"] == "Not investigated yet"
        assert queue[7]["risk_rating"] == "Not investigated yet"


def test_token_totals_and_api_cost():
    """Verify sum of tokens across runs and the illustrative API-equivalent cost calculation."""
    with tempfile.TemporaryDirectory() as td:
        usage_path = Path(td) / "usage.jsonl"
        lines = [
            json.dumps({
                "run_id": "R-1",
                "task_id": "C-001",
                "total_tokens": 1000,
                "input_tokens": 500,
                "output_tokens": 100,
                "cache_creation_tokens": 200,
                "cache_read_tokens": 200,
            }),
            json.dumps({
                "run_id": "R-2",
                "task_id": "C-001",
                "total_tokens": 2000,
                "input_tokens": 1500,
                "output_tokens": 200,
                "cache_creation_tokens": 100,
                "cache_read_tokens": 200,
            }),
            json.dumps({
                "run_id": "R-3",
                "task_id": "C-002",
                "total_tokens": 500,
                "input_tokens": 400,
                "output_tokens": 100,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
            }),
        ]
        usage_path.write_text("\n".join(lines), encoding="utf-8")

        stats = load_usage_stats(usage_path)
        assert "C-001" in stats
        c1 = stats["C-001"]
        assert c1["total_tokens"] == 3000
        assert c1["input_tokens"] == 2000
        assert c1["output_tokens"] == 300
        assert c1["cache_creation_tokens"] == 300
        assert c1["cache_read_tokens"] == 400

        # Calculation check:
        # 2000 * 15 = 30000
        # 300 * 75 = 22500
        # 300 * 18.75 = 5625
        # 400 * 1.50 = 600
        # sum = 58725 / 1,000,000 = 0.058725 -> round 4 -> 0.0587
        assert c1["api_cost_usd"] == 0.0587

        # Direct calculate_api_cost test
        cost = calculate_api_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_write_tokens=1_000_000,
            cache_read_tokens=1_000_000,
        )
        assert cost == round(15.00 + 75.00 + 18.75 + 1.50, 4)


def test_source_lookup_for_each_id_kind():
    """Verify source ID resolution for transactions, customers, accounts, counterparties, screening and adverse media."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "bank.db"
        create_test_db(db_path)

        # Transaction lookup: T-...
        tx_res = lookup_source(db_path, "T-1001")
        assert tx_res["found"] is True
        assert tx_res["kind"] == "transaction"
        assert len(tx_res["records"]) == 1
        assert tx_res["records"][0]["txn_id"] == "T-1001"
        assert tx_res["records"][0]["amount_gbp"] == 9500.0

        # Customer lookup: CU-...
        cu_res = lookup_source(db_path, "CU-0001")
        assert cu_res["found"] is True
        assert cu_res["kind"] == "customer"
        assert cu_res["records"][0]["customer_id"] == "CU-0001"
        assert cu_res["records"][0]["name"] == "Alice Smith"

        # Account lookup: FAKE-AC-...
        ac_res = lookup_source(db_path, "FAKE-AC-0001-1")
        assert ac_res["found"] is True
        assert ac_res["kind"] == "account"
        assert ac_res["records"][0]["account_id"] == "FAKE-AC-0001-1"

        # Counterparty lookup: FAKE-EXT-...
        cp_res = lookup_source(db_path, "FAKE-EXT-101")
        assert cp_res["found"] is True
        assert cp_res["kind"] == "counterparty"
        assert cp_res["records"][0]["name"] == "Global Trade Ltd"

        # Counterparty lookup: FAKE-CASH-BRANCH
        cash_res = lookup_source(db_path, "FAKE-CASH-BRANCH")
        assert cash_res["found"] is True
        assert cash_res["kind"] == "counterparty"
        assert cash_res["records"][0]["name"] == "Cash Deposit Branch"

        # Screening list lookup: SL-1
        sl_res = lookup_source(db_path, "SL-1")
        assert sl_res["found"] is True
        assert sl_res["kind"] == "screening_list"
        assert sl_res["records"][0]["rowid"] == 1
        assert sl_res["records"][0]["list_type"] == "sanctions"

        # Adverse media lookup: AM-1
        am_res = lookup_source(db_path, "AM-1")
        assert am_res["found"] is True
        assert am_res["kind"] == "adverse_media"
        assert am_res["records"][0]["rowid"] == 1
        assert "investigated" in am_res["records"][0]["headline"]

        # Unknown / non-existent lookups
        unk_res = lookup_source(db_path, "T-999999")
        assert unk_res["found"] is False
        assert unk_res["records"] == []

        empty_res = lookup_source(db_path, "")
        assert empty_res["found"] is False


def test_decision_validation():
    """Verify save_decision validates decision enum, non-empty reason, and non-empty investigator."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "bank.db"
        create_test_db(db_path)

        # Invalid decision option
        with pytest.raises(ValueError, match="Invalid decision"):
            save_decision(db_path, "C-001", "Approve", "Reason", "Investigator")

        with pytest.raises(ValueError, match="Invalid decision"):
            save_decision(db_path, "C-001", "Close", "Reason", "Investigator")

        # Missing / whitespace reason
        with pytest.raises(ValueError, match="reason must not be empty"):
            save_decision(db_path, "C-001", "Escalate", "", "Investigator")

        with pytest.raises(ValueError, match="reason must not be empty"):
            save_decision(db_path, "C-001", "Escalate", "   \t\n  ", "Investigator")

        # Missing / whitespace investigator name
        with pytest.raises(ValueError, match="Investigator name must not be empty"):
            save_decision(db_path, "C-001", "Escalate", "Valid reason", "")

        with pytest.raises(ValueError, match="Investigator name must not be empty"):
            save_decision(db_path, "C-001", "Escalate", "Valid reason", "   ")

        # Empty case_id
        with pytest.raises(ValueError, match="case_id must not be empty"):
            save_decision(db_path, "", "Escalate", "Valid reason", "Investigator")


def test_saving_writes_person_and_time():
    """Verify saving a decision creates the decisions table and records investigator and ISO 8601 UTC time."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "bank.db"
        create_test_db(db_path)

        # Ensure table creation is idempotent
        ensure_decisions_table(db_path)
        ensure_decisions_table(db_path)

        # Save first decision
        saved_1 = save_decision(
            db_path=db_path,
            case_id="C-001",
            decision="Escalate",
            reason="Confirmed high-risk sanctions link.",
            investigator="Jane Doe",
            suggested_action="Escalate",
        )
        assert saved_1["decision_id"] == 1
        assert saved_1["decided_at"] is not None

        history = list_decisions(db_path, "C-001")
        assert len(history) == 1
        record = history[0]
        assert record["decision_id"] == 1
        assert record["case_id"] == "C-001"
        assert record["decision"] == "Escalate"
        assert record["reason"] == "Confirmed high-risk sanctions link."
        assert record["investigator"] == "Jane Doe"
        assert record["suggested_action"] == "Escalate"
        assert record["decided_at"] == saved_1["decided_at"]

        # Check ISO 8601 UTC timestamp format
        dt = datetime.fromisoformat(record["decided_at"])
        assert dt is not None

        # Save second decision for same case
        saved_2 = save_decision(
            db_path=db_path,
            case_id="C-001",
            decision="Request more information",
            reason="Need bank statement clarification.",
            investigator="John Smith",
        )
        assert saved_2["decision_id"] == 2
        assert saved_2["decided_at"] is not None

        # Check newest first
        history = list_decisions(db_path, "C-001")
        assert len(history) == 2
        assert history[0]["decision_id"] == 2
        assert history[0]["decision"] == "Request more information"
        assert history[0]["investigator"] == "John Smith"
        assert history[0]["decided_at"] == saved_2["decided_at"]
        assert history[1]["decision_id"] == 1
        assert history[1]["decided_at"] == saved_1["decided_at"]

        # Save third decision with explicit decided_at
        custom_time = "2026-11-01T10:00:00+00:00"
        saved_3 = save_decision(
            db_path=db_path,
            case_id="C-001",
            decision="Dismiss",
            reason="Legitimate business transaction verified.",
            investigator="Jane Doe",
            decided_at=custom_time,
        )
        assert saved_3["decision_id"] == 3
        assert saved_3["decided_at"] == custom_time

        history = list_decisions(db_path, "C-001")
        assert history[0]["decided_at"] == custom_time

        # Decisions for another case
        assert list_decisions(db_path, "C-999") == []


def test_no_file_in_ui_mentions_answer_key():
    """Verify that no file in ui/ mentions the planted cases answer key table."""
    forbidden = "".join(["planted", "_", "cases"])
    ui_dir = Path(__file__).resolve().parents[1]

    offenders = []
    for path in sorted(ui_dir.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".md", ".json", ".html", ".css"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if forbidden in text:
                offenders.append(str(path.relative_to(ui_dir)))

    assert offenders == [], f"Files in ui/ mention answer key: {offenders}"


def test_app_decision_radio_has_no_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that the investigator decision radio button in ui/app.py starts with no default selection."""
    from streamlit.testing.v1 import AppTest

    # Set up isolated temporary database, cases directory, and usage log
    db_path = tmp_path / "bank.db"
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    usage_path = tmp_path / "usage.jsonl"
    usage_path.write_text("", encoding="utf-8")

    create_test_db(db_path)

    # Insert an open alert so the app queue renders the case review view
    with closing(sqlite3.connect(str(db_path))) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO alerts (case_id, customer_id, score, typologies, hits, status,
                                    window_start, window_end, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "C-001",
                    "CU-0001",
                    0.95,
                    '["structuring"]',
                    "[]",
                    "open",
                    "2026-09-01",
                    "2026-10-01",
                    "2026-10-01",
                    "2026-10-01",
                ),
            )

    # Write a test case file
    case_data = {
        "case_id": "C-001",
        "customer_id": "CU-0001",
        "risk_rating": "High",
        "summary": "Sample case summary for AppTest.",
        "suggested_action": "Escalate",
        "evidence": [
            {
                "claim": "Customer executed rapid transfer.",
                "source": ["T-1001"],
            }
        ],
        "innocent_explanations": ["Routine business expense"],
        "gaps": ["No tax declaration on file"],
    }
    (cases_dir / "C-001.json").write_text(json.dumps(case_data), encoding="utf-8")

    # Point the app at the temporary paths via environment variables
    monkeypatch.setenv("AML_BANK_DB", str(db_path))
    monkeypatch.setenv("AML_CASES_DIR", str(cases_dir))
    monkeypatch.setenv("AML_USAGE_LOG", str(usage_path))

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    at = AppTest.from_file(str(app_path))
    at.run()

    assert not at.exception

    # Filter radios related to decision
    decision_radios = [r for r in at.radio if "decision" in (r.key or "").lower() or "Decision" in r.label]
    assert len(decision_radios) >= 1, "Expected at least one decision radio button"

    for radio in decision_radios:
        assert radio.value is None, f"Decision radio {radio.key} should not have a preselected default"


def test_app_launch_sys_path_isolated():
    """Verify ui/app.py top imports succeed when launched directly where only ui/ is on sys.path.

    Regression test for launch bug: `streamlit run ui/app.py` puts only ui/ on sys.path,
    not repository root. In an isolated subprocess (-I), executing top of app.py up to
    '# Page Configuration' should succeed without ModuleNotFoundError.
    """
    import subprocess
    import sys

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    ui_dir = app_path.parent
    repo_root = app_path.parents[1]

    runner_script = f"""
import sys
from pathlib import Path

repo_root = Path({repr(str(repo_root))}).resolve()
ui_dir = Path({repr(str(ui_dir))}).resolve()
app_path = Path({repr(str(app_path))}).resolve()

# Simulate streamlit run ui/app.py: repo root is not on sys.path, but ui/ is
sys.path = [p for p in sys.path if Path(p).resolve() != repo_root]
if str(ui_dir) not in sys.path:
    sys.path.insert(0, str(ui_dir))

app_text = app_path.read_text(encoding="utf-8")
top_code = app_text.split("# Page Configuration")[0]

globs = {{"__file__": str(app_path), "__name__": "__main__"}}
exec(top_code, globs)
"""

    result = subprocess.run(
        [sys.executable, "-I", "-c", runner_script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Isolated import test failed (code {result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

