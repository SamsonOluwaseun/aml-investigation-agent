"""Usage hook tests with synthetic transcripts. No model, no network."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def assistant(msg_id, model="claude-test", inp=10, out=5, cc=100, cr=1000, ts="2026-11-16T10:00:00Z", **extra):
    return {"type": "assistant", "timestamp": ts, **extra,
            "message": {"id": msg_id, "model": model,
                        "usage": {"input_tokens": inp, "output_tokens": out,
                                  "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr}}}


def write_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


@pytest.fixture
def hook(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_USAGE_DIR", str(tmp_path / "usage"))
    monkeypatch.setenv("AML_PIPELINE_DAY", "2026-11-16")
    sys.path.insert(0, str(REPO))
    import usage.hook as module
    return importlib.reload(module)


def rows(hook):
    return [json.loads(line) for line in hook.USAGE_LOG.read_text(encoding="utf-8").splitlines()]


def test_sum_usage_counts_each_message_once(hook):
    entries = [assistant("m1"), assistant("m1"), assistant("m2", inp=1, out=2, cc=0, cr=0, ts="2026-11-16T10:05:00Z"),
               {"type": "user", "message": {"content": "hi"}},
               assistant("side", **{"isSidechain": True})]
    usage = hook.sum_usage(entries)
    assert usage["input_tokens"] == 11 and usage["output_tokens"] == 7
    assert usage["cache_creation_tokens"] == 100 and usage["cache_read_tokens"] == 1000
    assert usage["responses"] == 2 and usage["model"] == "claude-test"
    assert usage["started"] == "2026-11-16T10:00:00Z" and usage["ended"] == "2026-11-16T10:05:00Z"


def test_full_run_links_subagents_to_parent(hook, tmp_path):
    main = tmp_path / "sess" / "abc.jsonl"
    write_jsonl(main, [assistant("a1"), assistant("a2")])
    sub = tmp_path / "sess" / "abc" / "subagents" / "agent-x1.jsonl"
    write_jsonl(sub, [assistant("s1", inp=50, out=20, cc=0, cr=0, **{"isSidechain": True})])

    base = {"session_id": "abc", "transcript_path": str(main)}
    hook.main(json.dumps({**base, "hook_event_name": "PostToolUse", "tool_name": "mcp__aml-bank__get_alert",
                          "tool_input": {"case_id": "C-007"}}))
    hook.main(json.dumps({**base, "hook_event_name": "PostToolUse", "tool_name": "mcp__aml-bank__get_customer",
                          "tool_input": {"case_id": "C-007", "customer_id": "CU-0001"},
                          "agent_id": "x1", "agent_type": "evidence-gatherer"}))
    # No agent_transcript_path given: the hook falls back to <session>/subagents/agent-<id>.jsonl
    hook.main(json.dumps({**base, "hook_event_name": "SubagentStop", "agent_id": "x1",
                          "agent_type": "evidence-gatherer"}))
    hook.main(json.dumps({**base, "hook_event_name": "Stop"}))

    logged = rows(hook)
    assert [r["agent"] for r in logged] == ["evidence-gatherer", "investigate"]
    sub_row, main_row = logged
    assert sub_row["task_id"] == main_row["task_id"] == "C-007"
    assert sub_row["parent_run"] == main_row["run_id"] and main_row["parent_run"] is None
    assert sub_row["input_tokens"] == 50 and sub_row["output_tokens"] == 20
    assert main_row["input_tokens"] == 20 and main_row["total_tokens"] == 2 * (10 + 5 + 100 + 1000)
    assert main_row["pipeline_day"] == "2026-11-16"
    for column in ("run_id", "task_id", "agent", "parent_run", "model", "input_tokens", "output_tokens",
                   "cache_creation_tokens", "cache_read_tokens", "started", "ended", "evidence"):
        assert column in main_row


def test_real_payload_shape(hook, tmp_path):
    """Field names as sent by Claude Code 2.1.325 (captured with AML_HOOK_DEBUG=1)."""
    main = tmp_path / "s9.jsonl"
    write_jsonl(main, [assistant("a1")])
    sub = tmp_path / "elsewhere" / "agent-q.jsonl"
    write_jsonl(sub, [assistant("s1", inp=7, out=3, cc=0, cr=0)])
    common = {"session_id": "s9", "transcript_path": str(main), "cwd": str(tmp_path), "permission_mode": "dontAsk",
              "prompt_id": "p1", "effort": "high"}
    hook.main(json.dumps({**common, "hook_event_name": "PostToolUse", "tool_name": "mcp__aml-bank__get_customer",
                          "mcp_server": "aml-bank", "tool_use_id": "t1", "duration_ms": 12,
                          "tool_input": {"case_id": "C-016", "customer_id": "CU-0331"},
                          "agent_id": "q", "agent_type": "typology-analyst"}))
    hook.main(json.dumps({**common, "hook_event_name": "SubagentStop", "agent_id": "q", "agent_type": "typology-analyst",
                          "agent_transcript_path": str(sub), "stop_hook_active": False,
                          "last_assistant_message": "done"}))
    (row,) = rows(hook)
    assert row["task_id"] == "C-016" and row["agent"] == "typology-analyst" and row["output_tokens"] == 3
    assert row["evidence"] == str(sub) and row["parent_run"]


def test_second_stop_only_counts_new_lines(hook, tmp_path):
    main = tmp_path / "s2.jsonl"
    write_jsonl(main, [assistant("a1")])
    base = {"session_id": "s2", "transcript_path": str(main)}
    hook.main(json.dumps({**base, "hook_event_name": "PostToolUse", "tool_name": "mcp__aml-bank__get_alert",
                          "tool_input": {"case_id": "C-001"}}))
    hook.main(json.dumps({**base, "hook_event_name": "Stop"}))
    with main.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(assistant("a2", inp=1, out=1, cc=0, cr=0)) + "\n")
    hook.main(json.dumps({**base, "hook_event_name": "Stop"}))
    first, second = rows(hook)
    assert first["run_id"] != second["run_id"]
    assert second["input_tokens"] == 1


def test_sessions_without_cases_are_not_logged(hook, tmp_path):
    main = tmp_path / "dev.jsonl"
    write_jsonl(main, [assistant("a1")])
    hook.main(json.dumps({"session_id": "dev", "transcript_path": str(main), "hook_event_name": "PostToolUse",
                          "tool_name": "Read", "tool_input": {"file_path": "x"}}))
    hook.main(json.dumps({"session_id": "dev", "transcript_path": str(main), "hook_event_name": "Stop"}))
    assert not hook.USAGE_LOG.exists()


def test_hook_never_fails(tmp_path):
    env = {"AML_USAGE_DIR": str(tmp_path), "PATH": ""}
    done = subprocess.run([sys.executable, str(REPO / "usage" / "hook.py")], input="not json",
                          capture_output=True, text=True, env={**env, "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert done.returncode == 0
    assert (tmp_path / "hook_errors.log").exists()
