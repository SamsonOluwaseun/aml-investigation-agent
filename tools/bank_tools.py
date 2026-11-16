"""Read-only bank queries behind the MCP tools.

Every function takes ``case_id`` first, checks it against the alert queue,
writes one audit line and returns a small JSON-ready dict. The evaluation
answer key is never queried here: every SQL statement is a fixed string in
this module, and a test checks that its table name appears nowhere in it.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MAX_TRANSACTIONS = 200
MAX_COUNTERPARTIES = 50
MAX_ALERTS = 50
QUEUE = "QUEUE"  # case_id used for queue-level calls such as list_alerts
CASE_ID_PATTERN = re.compile(r"^C-\d{3,}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ToolError(ValueError):
    """Raised for bad arguments. The message is returned to the agent."""


def db_path() -> Path:
    return Path(os.environ.get("AML_BANK_DB", REPO / "bank" / "bank.db"))


def audit_path() -> Path:
    return Path(os.environ.get("AML_AUDIT_LOG", REPO / "tools" / "audit.jsonl"))


def cases_dir() -> Path:
    return Path(os.environ.get("AML_CASES_DIR", REPO / "cases"))


def _connect() -> sqlite3.Connection:
    path = db_path()
    if not path.exists():
        raise ToolError(f"Bank database not found at {path}. Run python bank/generate.py first.")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


AUDIT_ARG_LIMIT = 200  # characters kept per argument; a saved case file is not copied into the audit log


def _short(value):
    text = value if isinstance(value, str) else json.dumps(value)
    return value if len(text) <= AUDIT_ARG_LIMIT else f"{text[:AUDIT_ARG_LIMIT]}... ({len(text)} chars)"


def _audit(case_id: str, tool: str, args: dict, result: dict | None = None, error: str | None = None) -> None:
    line = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_id": case_id,
        "tool": tool,
        "args": {key: _short(value) for key, value in args.items()},
    }
    if error is not None:
        line["error"] = error
    elif result is not None:
        line["returned"] = {k: v for k, v in result.items() if k in ("returned", "total", "truncated", "saved")}
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")


def _alert_row(conn: sqlite3.Connection, case_id: str) -> sqlite3.Row:
    if not CASE_ID_PATTERN.match(case_id or ""):
        raise ToolError(f"Unknown case_id {case_id!r}. Case IDs look like C-001.")
    try:
        row = conn.execute(
            "SELECT case_id, customer_id, score, typologies, hits, status, window_start, window_end "
            "FROM alerts WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise ToolError("The alerts table does not exist yet. Run python rules/run_rules.py first.") from exc
    if row is None:
        raise ToolError(f"No alert with case_id {case_id}.")
    return row


def _case_accounts(conn: sqlite3.Connection, customer_id: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT account_id FROM accounts WHERE customer_id = ?", (customer_id,))}


def _tool(name: str):
    """Wrap a tool body: open the DB, audit the call, turn errors into results."""

    def decorate(body):
        def wrapper(case_id: str, **kwargs):
            try:
                with closing(_connect()) as conn:
                    if not (name == "list_alerts" and case_id == QUEUE):
                        alert = _alert_row(conn, case_id)
                    else:
                        alert = None
                    result = body(conn, alert, **kwargs)
            except ToolError as exc:
                _audit(case_id, name, kwargs, error=str(exc))
                return {"error": str(exc)}
            _audit(case_id, name, kwargs, result=result)
            return result

        wrapper.__name__ = name
        wrapper.__doc__ = body.__doc__
        return wrapper

    return decorate


@_tool("list_alerts")
def list_alerts(conn, alert, limit: int = 20):
    """Open alerts in the queue, highest score first. Use case_id "QUEUE"."""
    limit = max(1, min(int(limit), MAX_ALERTS))
    total = conn.execute("SELECT count(*) FROM alerts WHERE status = 'open'").fetchone()[0]
    rows = conn.execute(
        "SELECT case_id, customer_id, score, typologies FROM alerts WHERE status = 'open' "
        "ORDER BY score DESC, case_id LIMIT ?",
        (limit,),
    ).fetchall()
    alerts = [
        {"case_id": r["case_id"], "customer_id": r["customer_id"], "score": r["score"],
         "typologies": json.loads(r["typologies"])}
        for r in rows
    ]
    return {"total": total, "returned": len(alerts), "truncated": total > len(alerts), "alerts": alerts}


@_tool("get_alert")
def get_alert(conn, alert):
    """The rule hits for this case and the transaction IDs that triggered them."""
    return {
        "case_id": alert["case_id"],
        "customer_id": alert["customer_id"],
        "score": alert["score"],
        "typologies": json.loads(alert["typologies"]),
        "hits": json.loads(alert["hits"]),
        "status": alert["status"],
        "window": {"from": alert["window_start"], "to": alert["window_end"]},
    }


@_tool("get_customer")
def get_customer(conn, alert, customer_id: str):
    """KYC profile for the customer on this case."""
    if customer_id != alert["customer_id"]:
        raise ToolError(f"{customer_id} is not the customer on {alert['case_id']}.")
    row = conn.execute(
        "SELECT customer_id, name, occupation, declared_income, risk_rating, country, onboarded_on "
        "FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    return {"customer": dict(row), "source": customer_id}


@_tool("get_accounts")
def get_accounts(conn, alert, customer_id: str):
    """Accounts held by the customer on this case, with opening dates."""
    if customer_id != alert["customer_id"]:
        raise ToolError(f"{customer_id} is not the customer on {alert['case_id']}.")
    rows = conn.execute(
        "SELECT account_id, type, opened_on, status FROM accounts WHERE customer_id = ? ORDER BY account_id",
        (customer_id,),
    ).fetchall()
    return {"customer_id": customer_id, "returned": len(rows), "accounts": [dict(r) for r in rows]}


def _check_account(conn, alert, account_id: str) -> None:
    if account_id not in _case_accounts(conn, alert["customer_id"]):
        raise ToolError(f"{account_id} is not an account of the customer on {alert['case_id']}.")


def _check_dates(date_from: str, date_to: str) -> tuple[str, str]:
    for value in (date_from, date_to):
        if not DATE_PATTERN.match(value or ""):
            raise ToolError(f"Dates must be YYYY-MM-DD, got {value!r}.")
    if date_from > date_to:
        raise ToolError("date_from is after date_to.")
    return date_from, date_to + "T23:59:59"


@_tool("get_transactions")
def get_transactions(conn, alert, account_id: str, date_from: str, date_to: str):
    """Transactions on one of the case customer's accounts in a date range (inclusive), at most 200."""
    _check_account(conn, alert, account_id)
    start, end = _check_dates(date_from, date_to)
    totals = conn.execute(
        "SELECT count(*), "
        "coalesce(sum(CASE WHEN direction='in' THEN amount_gbp END), 0), "
        "coalesce(sum(CASE WHEN direction='out' THEN amount_gbp END), 0) "
        "FROM transactions WHERE account_id = ? AND timestamp BETWEEN ? AND ?",
        (account_id, start, end),
    ).fetchone()
    rows = conn.execute(
        "SELECT txn_id, timestamp, direction, amount_gbp, channel, counterparty_account, country "
        "FROM transactions WHERE account_id = ? AND timestamp BETWEEN ? AND ? "
        "ORDER BY timestamp, txn_id LIMIT ?",
        (account_id, start, end, MAX_TRANSACTIONS),
    ).fetchall()
    return {
        "account_id": account_id,
        "from": date_from,
        "to": date_to,
        "total": totals[0],
        "returned": len(rows),
        "truncated": totals[0] > len(rows),
        "sum_in_gbp": round(totals[1], 2),
        "sum_out_gbp": round(totals[2], 2),
        "transactions": [dict(r) for r in rows],
    }


@_tool("get_counterparties")
def get_counterparties(conn, alert, account_id: str):
    """Who this account pays and is paid by, with counts, totals and first and last dates."""
    _check_account(conn, alert, account_id)
    rows = conn.execute(
        "SELECT t.counterparty_account, c.name, c.country, c.bank, count(*) AS txn_count, "
        "round(coalesce(sum(CASE WHEN t.direction='in' THEN t.amount_gbp END), 0), 2) AS total_in_gbp, "
        "round(coalesce(sum(CASE WHEN t.direction='out' THEN t.amount_gbp END), 0), 2) AS total_out_gbp, "
        "substr(min(t.timestamp), 1, 10) AS first_seen, substr(max(t.timestamp), 1, 10) AS last_seen "
        "FROM transactions t LEFT JOIN counterparties c USING (counterparty_account) "
        "WHERE t.account_id = ? GROUP BY t.counterparty_account "
        "ORDER BY total_in_gbp + total_out_gbp DESC, t.counterparty_account",
        (account_id,),
    ).fetchall()
    shown = rows[:MAX_COUNTERPARTIES]
    return {
        "account_id": account_id,
        "total": len(rows),
        "returned": len(shown),
        "truncated": len(rows) > len(shown),
        "counterparties": [dict(r) for r in shown],
    }


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


@_tool("screen_name")
def screen_name(conn, alert, name: str):
    """Exact and close matches on the fake sanctions/PEP list and fake adverse media.

    A close match is not a hit: compare the full name, country and account
    before treating it as one.
    """
    if not name or len(name) > 200:
        raise ToolError("Give a name between 1 and 200 characters.")
    matches = []
    for row in conn.execute("SELECT rowid, name, list_type, country FROM screening_list"):
        score = 1.0 if row["name"].casefold() == name.casefold() else _similar(row["name"], name)
        if score >= 0.75 or name.casefold() in row["name"].casefold() or row["name"].casefold() in name.casefold():
            matches.append({
                "source": f"SL-{row['rowid']}", "list": row["list_type"], "listed_name": row["name"],
                "country": row["country"], "match": "exact" if score == 1.0 else "close",
                "similarity": round(score, 2),
            })
    media = []
    for row in conn.execute("SELECT rowid, name, headline, date FROM adverse_media"):
        score = 1.0 if row["name"].casefold() == name.casefold() else _similar(row["name"], name)
        if score >= 0.75 or name.casefold() in row["name"].casefold() or row["name"].casefold() in name.casefold():
            media.append({
                "source": f"AM-{row['rowid']}", "name": row["name"], "headline": row["headline"],
                "date": row["date"], "match": "exact" if score == 1.0 else "close",
                "similarity": round(score, 2),
            })
    return {"name": name, "returned": len(matches) + len(media), "screening": matches, "adverse_media": media}
