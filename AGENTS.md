# AGENTS.md

Instructions for Codex, Antigravity and any other coding agent working in this repository.

## What this project is

An AML investigation agent on a synthetic bank. Rules detect, an AI agent gathers cited evidence, a human decides, and every step's token usage is logged. The full design is in `docs/DESIGN.md` and the task list is in `docs/BUILD_PLAN.md`. Read both before starting a task.

## Who owns what

| Agent | Folders |
| --- | --- |
| Codex | `bank/`, `rules/`, `eval/` |
| Antigravity | `ui/` |
| Claude Code | `agent/`, `tools/`, `usage/`, `pipeline/`, `.claude/`, `.mcp.json`, and reviews all pull requests |

Only change files in your own folders. If a task needs a change elsewhere, say so in the pull request instead of making it.

## Ground rules

- Python 3.11+, SQLite, standard library where possible. No paid services.
- Synthetic data only. Never add real names, account numbers, sort codes or bank data.
- Fixed random seeds, so every clone produces the same data.
- Every function that touches a case takes `case_id` as its first argument.
- Rule thresholds are demo values. Keep them in one config file and label them as such.
- The `planted_cases` table is the answer key. Only `eval/` may read it.
- Tests run with `pytest`, with no model and no network.
- Each folder keeps a README saying what it does and how to run it.

## Working on a task

1. Pick your next unchecked item in `docs/BUILD_PLAN.md`.
2. Work on a branch named `issue-<number>-<short-name>`.
3. Meet every acceptance criterion.
4. When you finish, add a short completion note to the pull request: what was asked, what changed, files touched, tests run and their result. Do not estimate your own token usage. That is measured separately.
