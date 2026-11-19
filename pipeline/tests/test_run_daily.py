"""Daily pipeline tests: a generated bank, generated day files, a fake agent. No model, no network."""

import json
import sqlite3
from pathlib import Path

import pytest

from bank.generate import generate, generate_day
from pipeline import run_daily


@pytest.fixture(scope="module")
def base_bank(tmp_path_factory):
    folder = tmp_path_factory.mktemp("bank")
    db = folder / "bank.db"
    generate(db)
    return db


@pytest.fixture
def setup(tmp_path, base_bank):
    db = tmp_path / "bank.db"
    db.write_bytes(base_bank.read_bytes())
    incoming, processed = tmp_path / "incoming", tmp_path / "processed"
    return {"db": db, "incoming": incoming, "processed": processed, "usage": tmp_path / "usage.jsonl"}


def run(s, day, **kwargs):
    return run_daily.run(day, s["db"], s["incoming"], s["processed"], s["usage"], **kwargs)


def count(db, sql, *args):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, args).fetchone()[0]


def test_three_days_build_an_alert_and_move_files(setup):
    for day in ("2026-11-16", "2026-11-17", "2026-11-18"):
        generate_day(day, path=setup["db"], out=setup["incoming"])
    texts = [run(setup, day, use_agent=False) for day in ("2026-11-16", "2026-11-17", "2026-11-18")]
    assert "New alerts: 1" in texts[2] and "structuring" in texts[2]
    assert "Rules window 2026-10-20 to 2026-11-18" in texts[2]
    assert count(setup["db"], "SELECT count(*) FROM transactions WHERE txn_id LIKE 'T-20261118-%'") > 0
    assert not list(setup["incoming"].glob("*.csv"))
    assert (setup["processed"] / "transactions_2026-11-18.csv").exists()
    assert (setup["processed"] / "summary_2026-11-18.txt").read_text(encoding="utf-8").startswith("Batch 2026-11-18")


def tamper(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.mark.parametrize("change", ["amount", "duplicate", "row_count", "column", "account"])
def test_failed_check_rejects_whole_batch(setup, change):
    generate_day("2026-11-16", path=setup["db"], out=setup["incoming"])
    csv_path = setup["incoming"] / "transactions_2026-11-16.csv"
    control = setup["incoming"] / "transactions_2026-11-16.control.json"
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    if change == "amount":
        fields = lines[1].split(",")
        fields[5] = f"{float(fields[5]) + 1:.2f}"
        lines[1] = ",".join(fields)
    elif change == "duplicate":
        lines[2] = lines[1]
    elif change == "row_count":
        data = json.loads(control.read_text())
        data["row_count"] += 1
        control.write_text(json.dumps(data))
    elif change == "column":
        lines[0] = lines[0].replace("reference", "memo")
    elif change == "account":
        lines[1] = lines[1].replace(lines[1].split(",")[1], "FAKE-AC-9999-1", 1)
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    loaded_before = count(setup["db"], "SELECT count(*) FROM transactions")
    with pytest.raises(run_daily.BatchRejected):
        run(setup, "2026-11-16", use_agent=False)
    assert count(setup["db"], "SELECT count(*) FROM transactions") == loaded_before
    assert csv_path.exists() and not setup["processed"].exists()


def test_same_day_twice_is_rejected(setup):
    generate_day("2026-11-16", path=setup["db"], out=setup["incoming"])
    run(setup, "2026-11-16", use_agent=False)
    with pytest.raises(run_daily.BatchRejected, match="already processed"):
        run(setup, "2026-11-16", use_agent=False)


def test_agent_stops_at_token_budget(setup):
    calls = []

    def fake_agent(case_id, day, mcp_config):
        calls.append(case_id)
        with setup["usage"].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"run_id": f"R-{len(calls)}", "task_id": case_id,
                                     "total_tokens": 400_000, "pipeline_day": day}) + "\n")
        return {"case_id": case_id, "ok": True, "saved": True}

    result = run_daily.investigate(["C-001", "C-002", "C-003", "C-004"], "2026-11-16", 1_000_000, None,
                                   setup["usage"], runner=fake_agent)
    assert calls == ["C-001", "C-002", "C-003"]  # 1.2M spent after the third; the fourth waits
    assert result["waiting"] == ["C-004"] and result["tokens_spent"] == 1_200_000


def test_budget_counts_reported_usage_when_hooks_log_nothing(setup):
    calls = []

    def fake_agent(case_id, day, mcp_config):
        calls.append(case_id)
        return {"case_id": case_id, "ok": True, "saved": True,
                "reported_usage": {"input_tokens": 300_000, "output_tokens": 0}}

    result = run_daily.investigate(["C-001", "C-002", "C-003"], "2026-11-16", 500_000, None,
                                   setup["usage"], runner=fake_agent)
    assert calls == ["C-001", "C-002"] and result["waiting"] == ["C-003"]


def test_max_cases_limit(setup):
    result = run_daily.investigate(["C-001", "C-002"], "2026-11-16", 10**9, 1, setup["usage"],
                                   runner=lambda c, d, m: {"case_id": c, "ok": True, "saved": False})
    assert [r["case_id"] for r in result["investigated"]] == ["C-001"] and result["waiting"] == ["C-002"]


def test_agent_command_has_no_file_or_shell_tools():
    command = run_daily.agent_command("claude", "C-001", Path("mcp.json"))
    tools = command[command.index("--tools") + 1]
    assert tools == "Agent"
    assert "/investigate C-001" in command and "--strict-mcp-config" in command
