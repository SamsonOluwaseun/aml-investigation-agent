"""save_case_file: the only tool that writes. Stores a cleaned draft case file."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from tools.bank_tools import ToolError, _tool, cases_dir

DRAFT_STATUS = "Draft for human review"

# Which table a cited source ID must exist in. A pattern with a group looks up
# the group (the rowid behind SL-/AM- IDs); otherwise the whole ID is used.
SOURCE_KINDS = [
    (re.compile(r"^T-\d+(?:-\d+)?$"), "SELECT 1 FROM transactions WHERE txn_id = ?"),
    (re.compile(r"^CU-\d+$"), "SELECT 1 FROM customers WHERE customer_id = ?"),
    (re.compile(r"^FAKE-AC-[\w-]+$"), "SELECT 1 FROM accounts WHERE account_id = ?"),
    (re.compile(r"^FAKE-(?:EXT|CASH)[\w-]*$"), "SELECT 1 FROM counterparties WHERE counterparty_account = ?"),
    (re.compile(r"^SL-(\d+)$"), "SELECT 1 FROM screening_list WHERE rowid = ?"),
    (re.compile(r"^AM-(\d+)$"), "SELECT 1 FROM adverse_media WHERE rowid = ?"),
]


def source_exists(conn, source: str) -> bool:
    for pattern, sql in SOURCE_KINDS:
        match = pattern.match(source)
        if match:
            key = match.group(1) if pattern.groups else source
            return conn.execute(sql, (key,)).fetchone() is not None
    return False


def _schema_errors(case: dict) -> list[str]:
    """Validate against agent/case_file.schema.json once item 6 provides it."""
    try:
        from agent.case_file import validate
    except ImportError:
        return []
    return validate(case)


def clean_case_file(conn, case_id: str, case: dict) -> tuple[dict, list[str]]:
    """Check a case file and drop anything that is not backed by a record.

    Returns the cleaned file and a list of notes on what was changed.
    Raises ToolError if the file cannot be saved at all.
    """
    notes: list[str] = []
    if not isinstance(case, dict):
        raise ToolError("The case file must be a JSON object.")
    if case.get("case_id") != case_id:
        raise ToolError(f"case_id in the file ({case.get('case_id')!r}) does not match {case_id}.")

    kept = []
    for index, item in enumerate(case.get("evidence") or []):
        if not isinstance(item, dict):
            notes.append(f"evidence[{index}] dropped: not an object")
            continue
        sources = item.get("source")
        if isinstance(sources, str):
            sources = [sources]
        sources = [s for s in (sources or []) if isinstance(s, str) and s.strip()]
        if not sources:
            notes.append(f"evidence[{index}] dropped: no source ID")
            continue
        missing = [s for s in sources if not source_exists(conn, s)]
        if missing:
            notes.append(f"evidence[{index}] dropped: unknown source IDs {missing}")
            continue
        kept.append({"claim": item.get("claim"), "source": sources})
    case = dict(case)
    case["evidence"] = kept
    if case.get("status") != DRAFT_STATUS:
        notes.append(f"status set to {DRAFT_STATUS!r}")
        case["status"] = DRAFT_STATUS

    errors = _schema_errors(case)
    if errors:
        raise ToolError("Case file failed the schema check: " + "; ".join(errors))
    return case, notes


@_tool("save_case_file")
def save_case_file(conn, alert, case_json: str):
    """Store the finished case file as a draft for human review. Uncited claims are dropped."""
    try:
        case = json.loads(case_json) if isinstance(case_json, str) else case_json
    except json.JSONDecodeError as exc:
        raise ToolError(f"case_json is not valid JSON: {exc}") from exc
    case, notes = clean_case_file(conn, alert["case_id"], case)
    if case.get("customer_id") != alert["customer_id"]:
        raise ToolError(f"customer_id must be {alert['customer_id']} for {alert['case_id']}.")
    if not case["evidence"]:
        raise ToolError("No evidence claim survived the citation check, so nothing was saved. " + "; ".join(notes))
    case["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    folder = cases_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{alert['case_id']}.json"
    path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"saved": True, "path": str(path), "evidence_kept": len(case["evidence"]), "notes": notes}
