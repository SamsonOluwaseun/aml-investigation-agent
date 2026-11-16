"""Pure data functions for the AML investigator review screen.

Loads open alert queue, joins with case files and usage logs, resolves source
record citations, and persists investigator decisions to SQLite.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


# Illustrative API-equivalent cost rates per 1,000,000 tokens (USD).
# Kept as a clearly labelled constant representing standard model pricing,
# not money spent on a fixed subscription.
API_EQUIVALENT_RATES_PER_M = {
    "input": 15.00,        # USD per 1M input tokens
    "output": 75.00,       # USD per 1M output tokens
    "cache_write": 18.75,  # USD per 1M cache creation tokens
    "cache_read": 1.50,    # USD per 1M cache read tokens
}

API_EQUIVALENT_LABEL = (
    "Illustrative API-equivalent estimate based on standard model rates, "
    "not money spent on a subscription."
)

ALLOWED_DECISIONS = ("Escalate", "Request more information", "Dismiss")

# Risk order ranking for sorting the investigation queue:
# High > Medium > Low > not investigated yet
RISK_ORDER = {
    "High": 0,
    "Medium": 1,
    "Low": 2,
    "Not investigated yet": 3,
}


def get_db_connection(db_path: str | Path, read_only: bool = True) -> sqlite3.Connection:
    """Return an SQLite connection, defaulting to read-only URI mode."""
    p = Path(db_path)
    if str(db_path) == ":memory:":
        conn = sqlite3.connect(":memory:")
    elif read_only:
        uri = f"{p.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(p.resolve()))
    conn.row_factory = sqlite3.Row
    return conn


def calculate_api_cost(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Calculate illustrative API-equivalent cost in USD from token counts."""
    cost = (
        (input_tokens * API_EQUIVALENT_RATES_PER_M["input"])
        + (output_tokens * API_EQUIVALENT_RATES_PER_M["output"])
        + (cache_write_tokens * API_EQUIVALENT_RATES_PER_M["cache_write"])
        + (cache_read_tokens * API_EQUIVALENT_RATES_PER_M["cache_read"])
    ) / 1_000_000.0
    return round(cost, 4)


def load_usage_stats(usage_log_path: str | Path) -> Dict[str, Dict[str, Any]]:
    """Parse usage.jsonl and aggregate token counts and API-equivalent cost per case."""
    path = Path(usage_log_path)
    stats: Dict[str, Dict[str, Any]] = {}
    if not path.is_file():
        return stats

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            case_id = row.get("task_id")
            if not case_id:
                continue

            if case_id not in stats:
                stats[case_id] = {
                    "case_id": case_id,
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "runs_count": 0,
                    "api_cost_usd": 0.0,
                }

            entry = stats[case_id]
            entry["total_tokens"] += int(row.get("total_tokens") or 0)
            entry["input_tokens"] += int(row.get("input_tokens") or 0)
            entry["output_tokens"] += int(row.get("output_tokens") or 0)
            entry["cache_creation_tokens"] += int(row.get("cache_creation_tokens") or 0)
            entry["cache_read_tokens"] += int(row.get("cache_read_tokens") or 0)
            entry["runs_count"] += 1

    for entry in stats.values():
        entry["api_cost_usd"] = calculate_api_cost(
            input_tokens=entry["input_tokens"],
            output_tokens=entry["output_tokens"],
            cache_write_tokens=entry["cache_creation_tokens"],
            cache_read_tokens=entry["cache_read_tokens"],
        )

    return stats


def load_case(cases_dir: str | Path, case_id: str) -> Optional[Dict[str, Any]]:
    """Load and parse the JSON case file for case_id, or return None if absent."""
    case_file_path = Path(cases_dir) / f"{case_id}.json"
    if not case_file_path.is_file():
        return None
    with open(case_file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_decisions_table(db_path: str | Path) -> None:
    """Ensure the decisions table exists in the bank database."""
    conn = get_db_connection(db_path, read_only=False)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id INTEGER PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('Escalate', 'Request more information', 'Dismiss')),
                    reason TEXT NOT NULL,
                    investigator TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    suggested_action TEXT
                )
                """
            )
    finally:
        conn.close()


def save_decision(
    db_path: str | Path,
    case_id: str,
    decision: str,
    reason: str,
    investigator: str,
    suggested_action: Optional[str] = None,
    decided_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate and record an investigator decision into the database.

    Returns a dict containing 'decision_id' and 'decided_at'.
    """
    if not case_id or not str(case_id).strip():
        raise ValueError("case_id must not be empty")

    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"Invalid decision: '{decision}'. Must be one of {ALLOWED_DECISIONS}")

    if not reason or not reason.strip():
        raise ValueError("Decision reason must not be empty")

    if not investigator or not investigator.strip():
        raise ValueError("Investigator name must not be empty")

    if decided_at is None:
        decided_at = datetime.now(timezone.utc).isoformat()

    ensure_decisions_table(db_path)
    conn = get_db_connection(db_path, read_only=False)
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO decisions (case_id, decision, reason, investigator, decided_at, suggested_action)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id.strip(),
                    decision,
                    reason.strip(),
                    investigator.strip(),
                    decided_at,
                    suggested_action,
                ),
            )
            return {
                "decision_id": cur.lastrowid,
                "decided_at": decided_at,
            }
    finally:
        conn.close()


def list_decisions(db_path: str | Path, case_id: str) -> List[Dict[str, Any]]:
    """List all recorded decisions for a case, newest first."""
    if not Path(db_path).is_file() and str(db_path) != ":memory:":
        return []

    conn = get_db_connection(db_path, read_only=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decisions'")
        if not cur.fetchone():
            return []

        cur.execute(
            """
            SELECT decision_id, case_id, decision, reason, investigator, decided_at, suggested_action
            FROM decisions
            WHERE case_id = ?
            ORDER BY decision_id DESC
            """,
            (case_id,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def load_queue(
    db_path: str | Path,
    cases_dir: str | Path,
    usage_path: str | Path,
) -> List[Dict[str, Any]]:
    """Load open alerts joined with case files and usage logs.

    Sorted High > Medium > Low > not investigated, then score descending, then case_id.
    """
    if not Path(db_path).is_file() and str(db_path) != ":memory:":
        return []

    usage_data = load_usage_stats(usage_path)

    conn = get_db_connection(db_path, read_only=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT case_id, customer_id, score, typologies, hits, status,
                   window_start, window_end, created_at, updated_at
            FROM alerts
            WHERE status = 'open'
            """
        )
        alert_rows = [dict(row) for row in cur.fetchall()]

        # Check if decisions table exists to pull latest decision
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decisions'")
        has_decisions = bool(cur.fetchone())
        decisions_map: Dict[str, str] = {}
        if has_decisions:
            cur.execute("SELECT case_id, decision, decision_id FROM decisions ORDER BY decision_id ASC")
            for d_row in cur.fetchall():
                decisions_map[d_row["case_id"]] = d_row["decision"]
    finally:
        conn.close()

    queue: List[Dict[str, Any]] = []
    for alert in alert_rows:
        cid = alert["case_id"]
        case_file = load_case(cases_dir, cid)

        if case_file:
            risk_rating = case_file.get("risk_rating", "Not investigated yet")
            suggested_action = case_file.get("suggested_action")
            summary = case_file.get("summary", "")
            has_case_file = True
        else:
            risk_rating = "Not investigated yet"
            suggested_action = None
            summary = ""
            has_case_file = False

        try:
            typologies = json.loads(alert.get("typologies", "[]"))
        except (json.JSONDecodeError, TypeError):
            typologies = []

        try:
            hits = json.loads(alert.get("hits", "[]"))
        except (json.JSONDecodeError, TypeError):
            hits = []

        usage_entry = usage_data.get(cid, {})
        total_tokens = usage_entry.get("total_tokens", 0)
        api_cost_usd = usage_entry.get("api_cost_usd", 0.0)

        decision_status = decisions_map.get(cid, "Pending")

        queue.append({
            "case_id": cid,
            "customer_id": alert["customer_id"],
            "score": float(alert.get("score") or 0.0),
            "risk_rating": risk_rating,
            "typologies": typologies,
            "hits": hits,
            "status": alert.get("status", "open"),
            "window_start": alert.get("window_start", ""),
            "window_end": alert.get("window_end", ""),
            "has_case_file": has_case_file,
            "case_file": case_file,
            "suggested_action": suggested_action,
            "summary": summary,
            "total_tokens": total_tokens,
            "api_cost_usd": api_cost_usd,
            "decision_status": decision_status,
        })

    def sort_key(item: Dict[str, Any]) -> tuple:
        risk_rank = RISK_ORDER.get(item["risk_rating"], 3)
        return (risk_rank, -item["score"], item["case_id"])

    queue.sort(key=sort_key)
    return queue


def lookup_source(db_path: str | Path, source_id: str) -> Dict[str, Any]:
    """Look up any cited source ID and return its record(s).

    Handles:
    - T-... -> transactions
    - CU-... -> customers
    - FAKE-AC-... -> accounts
    - FAKE-EXT-..., FAKE-CASH-... -> counterparties
    - SL-n -> screening_list by rowid n
    - AM-n -> adverse_media by rowid n
    """
    sid = str(source_id).strip()
    if not sid:
        return {"source_id": sid, "kind": "unknown", "records": [], "found": False}

    if not Path(db_path).is_file() and str(db_path) != ":memory:":
        return {"source_id": sid, "kind": "unknown", "records": [], "found": False}

    conn = get_db_connection(db_path, read_only=True)
    try:
        cur = conn.cursor()

        if sid.startswith("T-"):
            cur.execute(
                """
                SELECT txn_id, account_id, counterparty_account, amount_gbp,
                       direction, channel, country, timestamp
                FROM transactions
                WHERE txn_id = ?
                """,
                (sid,),
            )
            records = [dict(r) for r in cur.fetchall()]
            return {
                "source_id": sid,
                "kind": "transaction",
                "records": records,
                "found": len(records) > 0,
            }

        if sid.startswith("CU-"):
            cur.execute(
                """
                SELECT customer_id, name, occupation, declared_income,
                       risk_rating, country, onboarded_on
                FROM customers
                WHERE customer_id = ?
                """,
                (sid,),
            )
            records = [dict(r) for r in cur.fetchall()]
            return {
                "source_id": sid,
                "kind": "customer",
                "records": records,
                "found": len(records) > 0,
            }

        if sid.startswith("FAKE-AC-"):
            cur.execute(
                """
                SELECT account_id, customer_id, type, opened_on, status
                FROM accounts
                WHERE account_id = ?
                """,
                (sid,),
            )
            records = [dict(r) for r in cur.fetchall()]
            return {
                "source_id": sid,
                "kind": "account",
                "records": records,
                "found": len(records) > 0,
            }

        if sid.startswith("FAKE-EXT-") or sid.startswith("FAKE-CASH"):
            cur.execute(
                """
                SELECT counterparty_account, name, country, bank
                FROM counterparties
                WHERE counterparty_account = ?
                """,
                (sid,),
            )
            records = [dict(r) for r in cur.fetchall()]
            return {
                "source_id": sid,
                "kind": "counterparty",
                "records": records,
                "found": len(records) > 0,
            }

        if sid.startswith("SL-"):
            try:
                row_id = int(sid[3:])
            except ValueError:
                return {"source_id": sid, "kind": "screening_list", "records": [], "found": False}

            cur.execute(
                """
                SELECT rowid, name, list_type, country
                FROM screening_list
                WHERE rowid = ?
                """,
                (row_id,),
            )
            records = [dict(r) for r in cur.fetchall()]
            return {
                "source_id": sid,
                "kind": "screening_list",
                "records": records,
                "found": len(records) > 0,
            }

        if sid.startswith("AM-"):
            try:
                row_id = int(sid[3:])
            except ValueError:
                return {"source_id": sid, "kind": "adverse_media", "records": [], "found": False}

            cur.execute(
                """
                SELECT rowid, name, headline, date
                FROM adverse_media
                WHERE rowid = ?
                """,
                (row_id,),
            )
            records = [dict(r) for r in cur.fetchall()]
            return {
                "source_id": sid,
                "kind": "adverse_media",
                "records": records,
                "found": len(records) > 0,
            }

        # Fallback check across tables if prefix is not standard
        cur.execute("SELECT * FROM counterparties WHERE counterparty_account = ?", (sid,))
        records = [dict(r) for r in cur.fetchall()]
        if records:
            return {"source_id": sid, "kind": "counterparty", "records": records, "found": True}

        return {"source_id": sid, "kind": "unknown", "records": [], "found": False}
    finally:
        conn.close()
