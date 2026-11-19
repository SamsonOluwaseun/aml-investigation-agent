# usage/

Token usage logging. Claude Code hooks read the session transcripts and write one row per agent run to `usage.jsonl`, linked to the case and the parent run. The agent never reports its own usage.

**Owner:** Claude Code · **Build plan:** item 7 · **Design:** Step 7

Costs worked out from this log are API-equivalent estimates, not money spent on a subscription.

## How it works

[`hook.py`](hook.py) is registered in `.claude/settings.json` for three events:

| Event | What the hook does |
| --- | --- |
| `PostToolUse` on `mcp__aml-bank__.*` | Reads `case_id` from the tool input and records which session, and which subagent if any, is working on which case (`usage/.state/<session>.json`) |
| `SubagentStop` | Reads the subagent's own transcript, adds up its tokens and writes one row, with `parent_run` set to the top-level run |
| `Stop` | Reads the main transcript since the last Stop, adds up its tokens and writes the top-level row |

Each model response can appear as several transcript lines with the same message ID and usage, so each message ID is counted once. Sessions that never call a bank tool with a case ID are not logged, so ordinary development sessions in this repo add nothing. The hook always exits 0. Errors go to `usage/hook_errors.log`. Set `AML_HOOK_DEBUG=1` to also save every raw hook payload to `usage/hook_debug.jsonl`.

## Columns

One JSON object per line, matching the Agent Runs sheet in the token tracker:

| Column | Example |
| --- | --- |
| `run_id` | `R-0004` |
| `task_id` | `C-001` (the case) |
| `agent` | `investigate` (top level), `evidence-gatherer`, `typology-analyst`, `case-writer` |
| `parent_run` | `R-0001` for subagents, `null` for the top-level run |
| `model` | from the transcript |
| `input_tokens`, `output_tokens` | per run |
| `cache_creation_tokens`, `cache_read_tokens`, `cache_tokens` | per run |
| `total_tokens` | all four added together |
| `started`, `ended` | first and last response timestamps |
| `evidence` | transcript path |
| `session_id`, `agent_id`, `responses`, `pipeline_day` | extra fields for joining and budgeting |

Handoff amplification for a case = sum of `total_tokens` over all rows for the case ÷ `total_tokens` of its top-level `investigate` row.

## Tests

```bash
pytest usage    # synthetic transcripts, no model
```

`usage.jsonl`, `hook_debug.jsonl`, `hook_errors.log` and `.state/` are git-ignored.
