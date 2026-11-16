"""Offline acceptance tests against the synthetic bank's answer key."""

from contextlib import closing
import csv
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from bank.generate import daily_demo_customer, generate, generate_day
from rules.run_rules import run
from rules.typologies import band


def collected_case_ids():
    """Discover both parameter groups from a disposable synthetic answer key."""
    with TemporaryDirectory(prefix="rule-case-ids-") as directory:
        path = Path(directory) / "bank.db"
        generate(path)
        with closing(sqlite3.connect(path)) as conn:
            rows = conn.execute(
                "SELECT case_id, is_suspicious FROM planted_cases ORDER BY case_id"
            ).fetchall()
    suspicious = [case_id for case_id, flag in rows if flag]
    look_alikes = [case_id for case_id, flag in rows if not flag]
    assert len(suspicious) == 15
    assert len(look_alikes) == 12
    return suspicious, look_alikes


SUSPICIOUS_CASE_IDS, LOOK_ALIKE_CASE_IDS = collected_case_ids()


@pytest.fixture(scope="module")
def generated_bank(tmp_path_factory):
    path = tmp_path_factory.mktemp("rule-answer-key") / "bank.db"
    generate(path)
    run(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        # Issue #5 explicitly permits these tests, outside eval/, to read
        # planted_cases as an oracle. Production rules must never read it.
        cases = {row["case_id"]: dict(row) for row in conn.execute(
            "SELECT * FROM planted_cases ORDER BY case_id")}
        alerts = {row["customer_id"]: dict(row) for row in conn.execute(
            "SELECT * FROM alerts")}
    assert len(cases) == 27
    assert sum(case["is_suspicious"] for case in cases.values()) == 15
    return path, cases, alerts


@pytest.mark.parametrize("case_id", SUSPICIOUS_CASE_IDS)
def test_planted_suspicious_case(case_id, generated_bank):
    _, cases, alerts = generated_bank
    case = cases[case_id]
    customer = case["customer_id"]
    assert customer in alerts, f"{case_id}: no alert for {customer}"
    alert = alerts[customer]
    assert case["typology"] in json.loads(alert["typologies"]), case
    assert band(alert["score"]) in {"Medium", "High"}, case


@pytest.mark.parametrize("case_id", LOOK_ALIKE_CASE_IDS)
def test_look_alike_case(case_id, generated_bank, record_property):
    _, cases, alerts = generated_bank
    case = cases[case_id]
    alert = alerts.get(case["customer_id"])
    score_band = band(alert["score"]) if alert else "No alert"
    record_property("alerted", alert is not None)
    record_property("score_band", score_band)
    print(f"{case_id}: alerted={alert is not None}; band={score_band}")
    assert not case["is_suspicious"], case
    if score_band == "High":
        # A High look-alike is permitted only within the shared demo budget.
        high = [other_id for other_id in LOOK_ALIKE_CASE_IDS
                if cases[other_id]["customer_id"] in alerts
                and band(alerts[cases[other_id]["customer_id"]]["score"]) == "High"]
        assert len(high) <= 3, high


def test_look_alike_false_alarms(generated_bank, record_property):
    _, cases, alerts = generated_bank
    look_alikes = [case for case in cases.values() if not case["is_suspicious"]]
    alerted = [alerts[case["customer_id"]] for case in look_alikes
               if case["customer_id"] in alerts]
    high = [alert for alert in alerted if band(alert["score"]) == "High"]
    record_property("look_alikes_alerted", len(alerted))
    record_property("look_alikes_high", len(high))
    print(f"Look-alikes: {len(alerted)}/{len(look_alikes)} alert at all; {len(high)} High")
    assert len(high) <= 3, high  # DESIGN.md Step 8 demo false-alarm target.


def test_ordinary_customer_alerts(generated_bank):
    _, cases, alerts = generated_bank
    planted_customers = {case["customer_id"] for case in cases.values()}
    ordinary = sorted(set(alerts) - planted_customers)
    assert len(ordinary) <= 5, ordinary


def test_generated_bank_rules_are_idempotent(generated_bank):
    path, _, _ = generated_bank
    with closing(sqlite3.connect(path)) as conn:
        before = conn.execute("SELECT * FROM alerts ORDER BY case_id").fetchall()
    summary = run(path)
    assert summary["new"] == []
    assert summary["updated"] == []
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT * FROM alerts ORDER BY case_id").fetchall() == before


def load_batch(path, batch):
    """Load only the transaction columns, mapping the CSV country column."""
    with batch.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT INTO transactions (txn_id, account_id, counterparty_account, "
            "amount_gbp, direction, channel, country, timestamp) VALUES (?,?,?,?,?,?,?,?)",
            [(row["txn_id"], row["account_id"], row["counterparty_account"],
              float(row["amount_gbp"]), row["direction"], row["channel"],
              row["counterparty_country"], row["timestamp"]) for row in rows],
        )


def test_daily_structuring_builds_across_days(tmp_path):
    path = tmp_path / "bank.db"
    output = tmp_path / "batches"
    generate(path)
    customer = daily_demo_customer()
    case_id = None
    for day in ("2026-11-16", "2026-11-17", "2026-11-18"):
        generate_day(day, path, output)
        load_batch(path, output / f"transactions_{day}.csv")
        summary = run(path, as_of=day)
        assert summary["window"]["window_end"] == day
        with closing(sqlite3.connect(path)) as conn:
            alert = conn.execute(
                "SELECT case_id, typologies FROM alerts WHERE customer_id=?",
                (customer,),
            ).fetchone()
        if day < "2026-11-18":
            assert alert is None or "structuring" not in json.loads(alert[1]), (day, alert)
        else:
            assert alert is not None
            assert "structuring" in json.loads(alert[1])
            case_id = alert[0]
    run(path, as_of="2026-11-19")
    with closing(sqlite3.connect(path)) as conn:
        alert = conn.execute(
            "SELECT case_id, typologies FROM alerts WHERE customer_id=?", (customer,)
        ).fetchone()
    assert alert[0] == case_id
    assert "structuring" in json.loads(alert[1])


def test_production_rules_do_not_mention_answer_key():
    root = Path(__file__).resolve().parents[1]
    offenders = [str(path.relative_to(root)) for path in sorted(root.rglob("*.py"))
                 if "tests" not in path.relative_to(root).parts
                 and "planted_cases" in path.read_text(encoding="utf-8")]
    assert offenders == [], offenders
