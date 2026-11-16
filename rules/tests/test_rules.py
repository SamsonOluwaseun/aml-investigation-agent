"""Focused offline checks on small hand-built banks."""
import json
import sqlite3

import pytest

from rules.run_rules import run
from rules.typologies import band, structuring, rapid_pass_through, fan_in_fan_out, high_risk_link


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE customers(customer_id TEXT PRIMARY KEY);
    CREATE TABLE accounts(account_id TEXT PRIMARY KEY, customer_id TEXT);
    CREATE TABLE counterparties(counterparty_account TEXT PRIMARY KEY, name TEXT, country TEXT);
    CREATE TABLE transactions(txn_id TEXT PRIMARY KEY, account_id TEXT,
      counterparty_account TEXT, amount_gbp REAL, direction TEXT, channel TEXT,
      country TEXT, timestamp TEXT);
    CREATE TABLE screening_list(name TEXT, list_type TEXT, country TEXT);
    INSERT INTO customers VALUES ('CU-1'), ('CU-2');
    INSERT INTO accounts VALUES ('AC-1','CU-1'), ('AC-2','CU-2');
    INSERT INTO counterparties VALUES ('CASH','FAKE Cash','GB'),
      ('LISTED','fake LISTED','GB'), ('SIMILAR','FAKE Listed Supplies','GB'),
      ('COUNTRY','FAKE Elsewhere','XZ');
    INSERT INTO screening_list VALUES ('FAKE Listed','sanctions','GB');
    """)
    yield conn, path
    conn.close()


def payment(conn, txn, when, amount=9000, direction="in", channel="cash",
            party="CASH", account="AC-1", country="GB"):
    conn.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)",
                 (txn, account, party, amount, direction, channel, country, when))


def test_structuring_boundaries_and_history(db):
    conn, _ = db
    for i, day in enumerate((1, 3, 5, 7, 14)):
        payment(conn, f"T-{i}", f"2026-10-{day:02d}T10:00:00")
    hit, = structuring(conn, "2026-10-01", "2026-10-30")
    assert hit["score"] == .78
    assert hit["txn_ids"] == [f"T-{i}" for i in range(5)]
    for i, day in enumerate((1, 3, 5, 7, 14)):
        payment(conn, f"H-{i}", f"2026-09-{day:02d}T10:00:00")
    assert band(structuring(conn, "2026-10-01", "2026-10-30")[0]["score"]) == "Low"
    conn.execute("UPDATE transactions SET timestamp='2026-10-15T00:00:00' WHERE txn_id='T-4'")
    assert structuring(conn, "2026-10-01", "2026-10-30") == []


def test_pass_through_48_hours_and_bills(db):
    conn, _ = db
    payment(conn, "IN", "2026-10-01T09:00:00", 10000, channel="transfer")
    payment(conn, "OUT", "2026-10-03T09:00:00", 8000, "out", "transfer")
    assert rapid_pass_through(conn, "2026-10-01", "2026-10-30")[0]["txn_ids"] == ["IN", "OUT"]
    conn.execute("UPDATE transactions SET timestamp='2026-10-03T09:00:01' WHERE txn_id='OUT'")
    assert rapid_pass_through(conn, "2026-10-01", "2026-10-30") == []
    conn.execute("UPDATE transactions SET timestamp='2026-10-01T10:00:00', channel='direct_debit' WHERE txn_id='OUT'")
    assert rapid_pass_through(conn, "2026-10-01", "2026-10-30") == []


def test_fan_directions_and_history(db):
    conn, _ = db
    for i in range(10):
        payment(conn, f"T-{i}", "2026-10-05T12:00:00", 500,
                "in" if i < 5 else "out", "transfer", f"FAKE-{i}")
    assert fan_in_fan_out(conn, "2026-10-01", "2026-10-30") == []
    conn.execute("UPDATE transactions SET direction='in'")
    assert len(fan_in_fan_out(conn, "2026-10-01", "2026-10-30")) == 1
    for i in range(10):
        payment(conn, f"H-{i}", "2026-09-05T12:00:00", 500, "in", "transfer", f"FAKE-{i}")
    assert fan_in_fan_out(conn, "2026-10-01", "2026-10-30") == []


def test_screening_exact_country_and_window(db):
    conn, _ = db
    payment(conn, "SIMILAR", "2026-10-02T10:00:00", party="SIMILAR")
    payment(conn, "OLD", "2026-09-30T23:59:59", party="LISTED")
    payment(conn, "FUTURE", "2026-10-31T00:00:00", party="LISTED")
    assert high_risk_link(conn, "2026-10-01", "2026-10-30") == []
    payment(conn, "COUNTRY", "2026-10-30T23:59:59", party="COUNTRY")
    assert high_risk_link(conn, "2026-10-01", "2026-10-30")[0]["score"] == .8
    payment(conn, "EXACT", "2026-10-02T10:00:00", party="LISTED")
    hit, = high_risk_link(conn, "2026-10-01", "2026-10-30")
    assert hit["score"] == .98
    assert hit["txn_ids"] == ["COUNTRY", "EXACT"]


def test_alert_ids_updates_and_idempotence(db):
    conn, path = db
    payment(conn, "COUNTRY", "2026-10-01T10:00:00", country="XZ")
    payment(conn, "EXACT", "2026-10-01T10:00:00", party="LISTED", account="AC-2")
    conn.commit()
    first = run(path, "2026-10-30")
    assert first["new"] == ["C-001", "C-002"]
    assert first["changes"][0]["customer_id"] == "CU-2"
    assert first["window"] == {"window_start": "2026-10-01", "window_end": "2026-10-30"}
    before = conn.execute("SELECT * FROM alerts ORDER BY case_id").fetchall()
    assert len(run(path, "2026-10-30")["unchanged"]) == 2
    assert conn.execute("SELECT * FROM alerts ORDER BY case_id").fetchall() == before
    payment(conn, "MORE", "2026-10-30T12:00:00", party="LISTED")
    conn.commit()
    assert run(path, "2026-10-31")["updated"] == ["C-002"]
    row = conn.execute("SELECT created_at,updated_at,hits FROM alerts WHERE case_id='C-002'").fetchone()
    assert row[:2] == ("2026-10-30", "2026-10-31")
    assert "customer_id" not in json.loads(row[2])[0]
    assert run(path, "2027-01-01")["open_queue"] == 2
    assert band(.75) == "High"
    assert band(.5) == "Medium"
