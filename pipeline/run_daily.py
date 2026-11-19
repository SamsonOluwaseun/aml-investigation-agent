"""Daily batch: validate, load, run rules, create or update alerts, investigate, summarise.

    python pipeline/run_daily.py --day 2026-11-16 [--max-cases 3] [--budget-tokens 1500000] [--no-agent]

1. Validate incoming/transactions_<day>.csv against its .control.json and the
   bank. Any failed check rejects the whole batch: nothing is loaded and the
   script exits with status 2.
2. Load the rows into the transactions table in one database transaction and
   move both files to processed/.
3. Run the typology rules over the rolling 30-day window ending on the day.
4. Alerts are created or updated by the rules (one per customer).
5. Run the investigation agent headless on each new alert until the daily
   token budget is reached. Remaining alerts wait for the next run.
6. Write a run summary to processed/summary_<day>.txt and print it.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from rules import run_rules  # noqa: E402

COLUMNS = ["txn_id", "account_id", "customer_id", "timestamp", "direction", "amount_gbp",
           "channel", "counterparty_account", "counterparty_country", "reference"]
DEFAULT_BUDGET_TOKENS = 1_500_000
AGENT_TIMEOUT_SECONDS = 900


class BatchRejected(Exception):
    """The batch failed validation. Nothing was loaded."""


# ---------------------------------------------------------------- paths

def paths(day: str, incoming: Path, processed: Path) -> dict:
    name = f"transactions_{day}"
    return {
        "csv": incoming / f"{name}.csv",
        "control": incoming / f"{name}.control.json",
        "processed_csv": processed / f"{name}.csv",
        "processed_control": processed / f"{name}.control.json",
        "summary": processed / f"summary_{day}.txt",
    }


# ---------------------------------------------------------------- 1. validate

def validate(conn: sqlite3.Connection, day: str, csv_path: Path, control_path: Path) -> list[dict]:
    """Return the parsed rows, or raise BatchRejected listing every problem found."""
    problems: list[str] = []
    if not csv_path.exists():
        raise BatchRejected(f"missing batch file {csv_path.name}")
    if not control_path.exists():
        raise BatchRejected(f"missing control file {control_path.name}")
    try:
        control = json.loads(control_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BatchRejected(f"control file is not valid JSON: {exc}") from exc

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise BatchRejected(f"columns {reader.fieldnames} do not match {COLUMNS}")
        rows = list(reader)

    if control.get("batch_date") != day:
        problems.append(f"control batch_date {control.get('batch_date')!r} is not {day}")
    if control.get("file") != csv_path.name:
        problems.append(f"control file name {control.get('file')!r} is not {csv_path.name}")
    if control.get("row_count") != len(rows):
        problems.append(f"row count {len(rows)} does not match control {control.get('row_count')}")

    seen: set[str] = set()
    total = Decimal(0)
    accounts = dict(conn.execute("SELECT account_id, customer_id FROM accounts"))
    parties = {r[0] for r in conn.execute("SELECT counterparty_account FROM counterparties")}
    for number, row in enumerate(rows, start=2):  # line 1 is the header
        where = f"line {number} ({row.get('txn_id')})"
        txn = row["txn_id"]
        if not txn:
            problems.append(f"{where}: empty txn_id")
        elif txn in seen:
            problems.append(f"{where}: duplicate txn_id in the batch")
        seen.add(txn)
        try:
            amount = Decimal(row["amount_gbp"])
            if amount <= 0:
                problems.append(f"{where}: amount must be positive")
            total += amount
        except InvalidOperation:
            problems.append(f"{where}: amount {row['amount_gbp']!r} is not a number")
        if row["direction"] not in ("in", "out"):
            problems.append(f"{where}: direction {row['direction']!r}")
        if not row["timestamp"].startswith(day + "T"):
            problems.append(f"{where}: timestamp {row['timestamp']!r} is not on {day}")
        if accounts.get(row["account_id"]) is None:
            problems.append(f"{where}: unknown account {row['account_id']}")
        elif accounts[row["account_id"]] != row["customer_id"]:
            problems.append(f"{where}: account {row['account_id']} does not belong to {row['customer_id']}")
        if row["counterparty_account"] not in parties:
            problems.append(f"{where}: unknown counterparty {row['counterparty_account']!r}")

    try:
        expected_total = Decimal(str(control.get("total_amount_gbp")))
    except InvalidOperation:
        expected_total = None
    if expected_total is None or abs(total - expected_total) > Decimal("0.005"):
        problems.append(f"total £{total} does not match control £{control.get('total_amount_gbp')}")

    if seen:
        placeholders = ",".join("?" * len(seen))
        already = [r[0] for r in conn.execute(
            f"SELECT txn_id FROM transactions WHERE txn_id IN ({placeholders})", sorted(seen))]
        if already:
            problems.append(f"{len(already)} txn_id(s) already loaded, e.g. {already[:3]}")

    if problems:
        shown = problems[:20] + ([f"... and {len(problems) - 20} more"] if len(problems) > 20 else [])
        raise BatchRejected("; ".join(shown))
    return rows


# ---------------------------------------------------------------- 2. load

def load(conn: sqlite3.Connection, rows: list[dict]) -> int:
    with conn:
        conn.executemany(
            "INSERT INTO transactions (txn_id, account_id, counterparty_account, amount_gbp, direction, "
            "channel, country, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["txn_id"], r["account_id"], r["counterparty_account"], float(Decimal(r["amount_gbp"])),
              r["direction"], r["channel"], r["counterparty_country"], r["timestamp"]) for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------- 5. agent

def find_claude() -> str | None:
    return os.environ.get("AML_CLAUDE_BIN") or shutil.which("claude")


def mcp_config_file() -> Path:
    """An MCP config that starts the bank tools with this Python interpreter."""
    config = {"mcpServers": {"aml-bank": {
        "command": sys.executable,
        "args": [str(REPO / "tools" / "server.py")],
        "env": {k: v for k, v in os.environ.items() if k.startswith("AML_")},
    }}}
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(config, handle)
    handle.close()
    return Path(handle.name)


def agent_command(claude: str, case_id: str, mcp_config: Path) -> list[str]:
    """Headless /investigate run. Built-in file and shell tools are switched off,
    so the agent can reach the bank only through the MCP tools."""
    return [
        claude, "-p", f"/investigate {case_id}",
        "--output-format", "json",
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--tools", "Agent",
        "--allowedTools", "Agent,mcp__aml-bank__*",
        "--permission-mode", "dontAsk",
    ]


def run_agent(case_id: str, day: str, mcp_config: Path) -> dict:
    claude = find_claude()
    if claude is None:
        return {"case_id": case_id, "ok": False, "error": "claude CLI not found (set AML_CLAUDE_BIN)"}
    env = dict(os.environ, AML_PIPELINE_DAY=day)
    try:
        done = subprocess.run(agent_command(claude, case_id, mcp_config), cwd=REPO, env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=AGENT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {"case_id": case_id, "ok": False, "error": "timed out"}
    result: dict = {"case_id": case_id, "ok": done.returncode == 0}
    try:
        payload = json.loads(done.stdout)
        result["result"] = (payload.get("result") or "")[:500]
        result["reported_usage"] = payload.get("usage")
        result["ok"] = result["ok"] and not payload.get("is_error")
    except json.JSONDecodeError:
        result["error"] = (done.stderr or done.stdout)[-500:]
    result["saved"] = (REPO / "cases" / f"{case_id}.json").exists() or _cases_dir_has(case_id)
    return result


def _cases_dir_has(case_id: str) -> bool:
    folder = Path(os.environ.get("AML_CASES_DIR", REPO / "cases"))
    return (folder / f"{case_id}.json").exists()


def tokens_spent(day: str, usage_log: Path) -> int:
    """Tokens logged by the usage hook for agent runs started by pipeline runs for this day."""
    if not usage_log.exists():
        return 0
    spent = 0
    for line in usage_log.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("pipeline_day") == day:
            spent += int(row.get("total_tokens") or 0)
    return spent


def _reported_tokens(usage: dict | None) -> int:
    if not usage:
        return 0
    return sum(int(usage.get(k) or 0) for k in
               ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def investigate(case_ids: list[str], day: str, budget: int, max_cases: int | None,
                usage_log: Path, runner=run_agent) -> dict:
    """Run the agent case by case until the budget or the case limit is reached."""
    done, waiting = [], []
    fallback_spent = 0
    mcp_config = mcp_config_file() if runner is run_agent else Path("unused")
    try:
        for case_id in case_ids:
            spent = max(tokens_spent(day, usage_log), fallback_spent)
            if spent >= budget or (max_cases is not None and len(done) >= max_cases):
                waiting.append(case_id)
                continue
            result = runner(case_id, day, mcp_config)
            # If the hook logged nothing (e.g. hooks disabled), count what the CLI reported.
            fallback_spent += _reported_tokens(result.get("reported_usage"))
            done.append(result)
    finally:
        if runner is run_agent:
            mcp_config.unlink(missing_ok=True)
    return {"investigated": done, "waiting": waiting,
            "tokens_spent": max(tokens_spent(day, usage_log), fallback_spent), "budget": budget}


# ---------------------------------------------------------------- 6. summary

def summary_text(day, loaded, rules_summary, alerts, agent) -> str:
    window = rules_summary.get("window") or {}
    if isinstance(window, (list, tuple)):
        window = {"start": window[0], "end": window[1]}
    start = window.get("start") or window.get("window_start")
    end = window.get("end") or window.get("window_end")
    new, updated = rules_summary.get("new", []), rules_summary.get("updated", [])
    lines = [
        f"Batch {day} | {loaded} rows loaded | 0 rejected",
        f"Rules window {start} to {end}",
        f"New alerts: {len(new)} | Updated: {len(updated)} | Open queue: {len(alerts)}",
    ]
    for alert in alerts:
        if alert["case_id"] in new or alert["case_id"] in updated:
            mark = "new" if alert["case_id"] in new else "updated"
            lines.append(f"  {alert['case_id']}  {alert['customer_id']}  {', '.join(alert['typologies']):<22} "
                         f"score {alert['score']:.2f}  ({mark})")
    if agent is None:
        lines.append("Agent: not run (--no-agent)")
    else:
        ok = sum(1 for r in agent["investigated"] if r.get("saved"))
        lines.append(f"Agent: {len(agent['investigated'])} case(s) investigated, {ok} case file(s) saved | "
                     f"tokens {agent['tokens_spent']:,} of {agent['budget']:,} budget (API-equivalent, see usage log)")
        for r in agent["investigated"]:
            status = "saved" if r.get("saved") else f"no case file ({r.get('error') or 'see output'})"
            lines.append(f"  {r['case_id']}: {status}")
        if agent["waiting"]:
            lines.append(f"Waiting for next run (budget or case limit): {', '.join(agent['waiting'])}")
    return "\n".join(lines)


def open_alerts(conn) -> list[dict]:
    rows = conn.execute("SELECT case_id, customer_id, score, typologies FROM alerts WHERE status = 'open' "
                        "ORDER BY score DESC, case_id").fetchall()
    return [{"case_id": r[0], "customer_id": r[1], "score": r[2], "typologies": json.loads(r[3])} for r in rows]


# ---------------------------------------------------------------- main

def run(day: str, db: Path, incoming: Path, processed: Path, usage_log: Path,
        budget: int = DEFAULT_BUDGET_TOKENS, max_cases: int | None = None,
        use_agent: bool = True, runner=run_agent) -> str:
    date.fromisoformat(day)
    files = paths(day, incoming, processed)
    if not files["csv"].exists() and files["processed_csv"].exists():
        raise BatchRejected(f"batch {day} was already processed (see {files['processed_csv']})")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        rows = validate(conn, day, files["csv"], files["control"])
        loaded = load(conn, rows)
    processed.mkdir(parents=True, exist_ok=True)
    shutil.move(files["csv"], files["processed_csv"])
    shutil.move(files["control"], files["processed_control"])

    rules_summary = run_rules.run(db, as_of=day)
    with closing(sqlite3.connect(db)) as conn:
        alerts = open_alerts(conn)

    agent = None
    if use_agent:
        agent = investigate(list(rules_summary.get("new", [])), day, budget, max_cases, usage_log, runner)
    text = summary_text(day, loaded, rules_summary, alerts, agent)
    files["summary"].write_text(text + "\n", encoding="utf-8")
    return text


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the daily AML batch.")
    parser.add_argument("--day", required=True, help="batch date, YYYY-MM-DD")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("AML_BANK_DB", REPO / "bank" / "bank.db")))
    parser.add_argument("--incoming", type=Path, default=REPO / "incoming")
    parser.add_argument("--processed", type=Path, default=REPO / "processed")
    parser.add_argument("--usage-log", type=Path, default=REPO / "usage" / "usage.jsonl")
    parser.add_argument("--budget-tokens", type=int, default=int(os.environ.get("AML_DAILY_TOKEN_BUDGET", DEFAULT_BUDGET_TOKENS)))
    parser.add_argument("--max-cases", type=int, default=None, help="investigate at most this many new alerts")
    parser.add_argument("--no-agent", action="store_true", help="skip the investigation agent")
    args = parser.parse_args(argv)
    try:
        print(run(args.day, args.db, args.incoming, args.processed, args.usage_log,
                  args.budget_tokens, args.max_cases, not args.no_agent))
    except BatchRejected as exc:
        print(f"Batch {args.day} REJECTED, nothing loaded: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
