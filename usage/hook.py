"""Claude Code hook: link sessions to cases and log token usage per run.

Registered in .claude/settings.json for three events:

- PostToolUse (matcher mcp__aml-bank__.*): reads case_id from the tool input
  and records which session, and which subagent if any, worked on which case.
- SubagentStop: sums the tokens in the subagent's own transcript and writes
  one row for that subagent run, linked to the parent run.
- Stop: sums the tokens in the main transcript since the last Stop and writes
  one row for the top-level run.

Tokens are read from Claude Code's transcripts, never reported by the agent.
Rows go to usage/usage.jsonl. Runs that never touched a case are not logged,
so ordinary development sessions in this repo leave no rows.

The hook never blocks Claude Code: any error is written to usage/hook_errors.log
and the script exits 0. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

USAGE_DIR = Path(os.environ.get("AML_USAGE_DIR", Path(__file__).resolve().parent))
USAGE_LOG = USAGE_DIR / "usage.jsonl"
STATE_DIR = USAGE_DIR / ".state"
ERROR_LOG = USAGE_DIR / "hook_errors.log"
DEBUG_LOG = USAGE_DIR / "hook_debug.jsonl"
BANK_TOOL_PREFIX = "mcp__aml-bank__"
TOP_LEVEL_AGENT = "investigate"


# ---------------------------------------------------------------- state

def _state_path(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_") or "unknown"
    return STATE_DIR / f"{safe}.json"


def load_state(session_id: str) -> dict:
    path = _state_path(session_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"session_id": session_id, "run_id": None, "case_id": None, "agents": {},
            "main_lines_done": 0}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(state["session_id"]).write_text(json.dumps(state, indent=1), encoding="utf-8")


def next_run_id() -> str:
    """Sequential run IDs R-0001, R-0002, ... across the usage log and live sessions."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    counter = STATE_DIR / "run_counter.txt"
    current = int(counter.read_text().strip()) if counter.exists() else _max_logged_run()
    current += 1
    counter.write_text(str(current))
    return f"R-{current:04d}"


def _max_logged_run() -> int:
    best = 0
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            try:
                best = max(best, int(json.loads(line)["run_id"].split("-")[1]))
            except (ValueError, KeyError, IndexError):
                continue
    return best


# ---------------------------------------------------------------- transcripts

def read_jsonl(path: str | Path, start_line: int = 0) -> tuple[list[dict], int]:
    """Return parsed entries from start_line onwards and the total line count."""
    entries = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for line in lines[start_line:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries, len(lines)


def sum_usage(entries: list[dict], include_sidechain: bool = False) -> dict | None:
    """Add up tokens per model response.

    A single response can be written as several transcript lines (one per
    content block) carrying the same message id and usage, so each message id
    is counted once, using its last line.
    """
    by_message: dict[str, dict] = {}
    times: list[str] = []
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        if entry.get("isSidechain") and not include_sidechain:
            continue
        message = entry.get("message") or {}
        usage = message.get("usage")
        if not usage:
            continue
        key = message.get("id") or entry.get("uuid") or str(len(by_message))
        by_message[key] = {"usage": usage, "model": message.get("model")}
        if entry.get("timestamp"):
            times.append(entry["timestamp"])
    if not by_message:
        return None
    totals = Counter()
    models = Counter()
    for item in by_message.values():
        usage = item["usage"]
        totals["input_tokens"] += int(usage.get("input_tokens") or 0)
        totals["output_tokens"] += int(usage.get("output_tokens") or 0)
        totals["cache_creation_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)
        totals["cache_read_tokens"] += int(usage.get("cache_read_input_tokens") or 0)
        if item["model"] and item["model"] != "<synthetic>":
            models[item["model"]] += 1
    return {
        **{k: totals[k] for k in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")},
        "model": models.most_common(1)[0][0] if models else None,
        "responses": len(by_message),
        "started": min(times) if times else None,
        "ended": max(times) if times else None,
    }


def write_row(row: dict) -> None:
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    with USAGE_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def make_row(run_id, case_id, agent, parent_run, usage, transcript, session_id, agent_id=None) -> dict:
    return {
        "run_id": run_id,
        "task_id": case_id,
        "agent": agent,
        "parent_run": parent_run,
        "model": usage["model"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_creation_tokens": usage["cache_creation_tokens"],
        "cache_read_tokens": usage["cache_read_tokens"],
        "cache_tokens": usage["cache_creation_tokens"] + usage["cache_read_tokens"],
        "total_tokens": usage["input_tokens"] + usage["output_tokens"]
        + usage["cache_creation_tokens"] + usage["cache_read_tokens"],
        "responses": usage["responses"],
        "started": usage["started"],
        "ended": usage["ended"],
        "evidence": str(transcript),
        "session_id": session_id,
        "agent_id": agent_id,
        # Set by pipeline/run_daily.py so it can enforce its daily token budget.
        "pipeline_day": os.environ.get("AML_PIPELINE_DAY"),
    }


# ---------------------------------------------------------------- events

def on_post_tool_use(event: dict) -> None:
    tool = event.get("tool_name") or ""
    if not tool.startswith(BANK_TOOL_PREFIX):
        return
    case_id = (event.get("tool_input") or {}).get("case_id")
    if not case_id or case_id == "QUEUE":
        return
    state = load_state(event["session_id"])
    if state["run_id"] is None:
        state["run_id"] = next_run_id()
    agent_id = event.get("agent_id")
    if agent_id:
        state["agents"].setdefault(agent_id, {"case_id": case_id, "agent_type": event.get("agent_type")})
        state["agents"][agent_id]["case_id"] = case_id
    else:
        state["case_id"] = case_id
    state.setdefault("cases", [])
    if case_id not in state["cases"]:
        state["cases"].append(case_id)
    save_state(state)


def _subagent_transcript(event: dict) -> Path | None:
    path = event.get("agent_transcript_path")
    if path and Path(path).exists():
        return Path(path)
    agent_id = event.get("agent_id")
    main = event.get("transcript_path")
    if agent_id and main:
        candidate = Path(main).with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def on_subagent_stop(event: dict) -> None:
    state = load_state(event["session_id"])
    agent_id = event.get("agent_id")
    known = state["agents"].get(agent_id or "", {})
    case_id = known.get("case_id") or state.get("case_id")
    if not case_id:
        return
    if state["run_id"] is None:
        state["run_id"] = next_run_id()
    transcript = _subagent_transcript(event)
    if transcript is None:
        _log_error(f"SubagentStop without a readable transcript: {json.dumps(event)[:500]}")
        return
    entries, _ = read_jsonl(transcript)
    usage = sum_usage(entries, include_sidechain=True)
    if usage is None:
        return
    agent = event.get("agent_type") or known.get("agent_type") or "subagent"
    write_row(make_row(next_run_id(), case_id, agent, state["run_id"], usage, transcript,
                       event["session_id"], agent_id))
    state["agents"].setdefault(agent_id or "unknown", {})["logged"] = True
    save_state(state)


def on_stop(event: dict) -> None:
    state = load_state(event["session_id"])
    if not state.get("case_id") and not state.get("cases"):
        return
    transcript = event.get("transcript_path")
    if not transcript or not Path(transcript).exists():
        return
    entries, total_lines = read_jsonl(transcript, state.get("main_lines_done", 0))
    usage = sum_usage(entries)
    state["main_lines_done"] = total_lines
    if usage is not None:
        if state["run_id"] is None:
            state["run_id"] = next_run_id()
        case_id = state.get("case_id") or state["cases"][-1]
        write_row(make_row(state["run_id"], case_id, TOP_LEVEL_AGENT, None, usage, transcript,
                           event["session_id"]))
        # A later turn in the same session is a new top-level run.
        state["run_id"] = None
    save_state(state)


HANDLERS = {"PostToolUse": on_post_tool_use, "SubagentStop": on_subagent_stop, "Stop": on_stop}


def _log_error(text: str) -> None:
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    with ERROR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {text}\n")


def main(raw: str) -> None:
    event = json.loads(raw)
    if os.environ.get("AML_HOOK_DEBUG"):
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
    handler = HANDLERS.get(event.get("hook_event_name"))
    if handler and event.get("session_id"):
        handler(event)


if __name__ == "__main__":
    try:
        main(sys.stdin.read())
    except Exception:  # noqa: BLE001 - a logging hook must never break the session
        _log_error(traceback.format_exc())
    sys.exit(0)
