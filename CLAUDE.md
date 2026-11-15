# CLAUDE.md

Instructions for Claude Code working in this repository.

## What this project is

An AML investigation agent on a synthetic bank. Rules detect, the agent gathers cited evidence, a human decides, and every step's token usage is logged. The full design is in `docs/DESIGN.md` and the task list is in `docs/BUILD_PLAN.md`. Read both before starting a task.

## Your role

You own orchestration, the investigation agent, the bank tools, usage logging and the daily pipeline: `agent/`, `tools/`, `usage/`, `pipeline/`, `.claude/`, `.mcp.json`. You also review pull requests from Codex (`bank/`, `rules/`, `eval/`) and Antigravity (`ui/`) against the acceptance criteria in `docs/BUILD_PLAN.md`.

## Ground rules

- Python 3.11+, SQLite, standard library where possible. No paid services.
- Synthetic data only. Never add real names, account numbers, sort codes or bank data.
- Every function and tool that touches a case takes `case_id` as its first argument.
- Detection is done by the rules in `rules/`. The agent never decides what is suspicious and never makes the final decision.
- Every claim in a case file cites at least one transaction or record ID.
- Never expose the `planted_cases` table through tools or prompts. It is the answer key.
- Keep tool results small. Summarise rather than dumping raw rows.
- Each folder keeps a README saying what it does and how to run it.

## Working on a task

1. Pick the next unchecked item in `docs/BUILD_PLAN.md`.
2. Work on a branch named `issue-<number>-<short-name>`.
3. Meet every acceptance criterion and add tests where the item calls for them.
4. Update the folder README and the status table in the root README.
5. Open a pull request that lists the criteria and how each was met.
