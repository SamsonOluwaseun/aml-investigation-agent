# Build plan

Work through these in order. Each item is sized to be one GitHub issue and one pull request. Create the issue, then work on a branch named `issue-<number>-<short-name>` so the issue number becomes the Task ID in the token tracker.

Details for every item are in [DESIGN.md](DESIGN.md).

## Phase 1: Data and rules (no model needed)

### 1. Fake bank generator
**Owner:** Codex · **Folder:** `bank/` · **Design:** Step 2

- [x] `bank/generate.py` creates `bank/bank.db` with the seven tables in Step 2
- [x] Fixed random seed: two runs produce identical databases
- [x] About 500 customers, 6 months of normal transactions
- [x] 15 planted cases across the four typologies, recorded in `planted_cases`
- [x] 10 to 15 innocent look-alikes, also recorded so the scorecard can count false alarms
- [x] Prints a summary: customers, accounts, transactions, planted cases
- [x] All names obviously fake

### 2. Daily batch files
**Owner:** Codex · **Folder:** `bank/` · **Design:** How this maps to production

- [x] `bank/generate.py --day YYYY-MM-DD` writes `incoming/transactions_<date>.csv` plus a `.control.json` (row count, total amount)
- [x] Same columns as `data/sample/transactions_2026-11-16.csv`
- [x] Running three consecutive days shows a planted pattern building up

### 3. Typology rules
**Owner:** Codex · **Folder:** `rules/` · **Design:** Step 3

- [x] One function per typology: structuring, rapid pass-through, fan-in/fan-out, high-risk link
- [x] Each returns hits with `customer_id`, `typology`, `score`, `txn_ids`
- [x] `rules/run_rules.py` writes one alert per customer to an `alerts` table, with a `case_id`
- [x] Thresholds in one config file, labelled as demo values
- [x] Rules run over a rolling 30-day window

### 4. Rule tests
**Owner:** Codex · **Folder:** `rules/tests/` · **Design:** Step 3

- [x] Every planted case raises an alert
- [x] Most look-alikes do not raise a High score
- [x] `pytest` passes with no model and no network

## Phase 2: The agent

### 5. Bank tools (MCP server)
**Owner:** Claude Code · **Folder:** `tools/` · **Design:** Step 4

- [x] `tools/server.py` exposes the eight tools in Step 4 using the MCP Python SDK
- [x] Every tool takes `case_id` first and writes a line to `tools/audit.jsonl`
- [x] Read-only except `save_case_file`
- [x] `planted_cases` is never reachable through any tool
- [x] Results capped (for example 200 transactions per call)
- [x] Registered in `.mcp.json` at the repo root

### 6. Investigation skill and subagents
**Owner:** Claude Code · **Folder:** `.claude/`, `agent/` · **Design:** Step 5

- [x] `.claude/skills/investigate/SKILL.md` runs the three subagents in order
- [x] `.claude/agents/evidence-gatherer.md`, `typology-analyst.md`, `case-writer.md`
- [x] `agent/case_file.schema.json` matches the case file in Step 5
- [x] Output validated against the schema before saving
- [x] Claims without a source ID are dropped
- [ ] Works interactively on one case, then headless with `claude -p` (headless verified on C-001 and C-016; the interactive run is left for Oluwaseun)

### 7. Usage logging hooks
**Owner:** Claude Code · **Folder:** `usage/`, `.claude/settings.json` · **Design:** Step 7

- [x] `PostToolUse` hook on the bank tools records session to case mapping
- [x] `SubagentStop` and `Stop` hooks read the transcript and sum tokens
- [x] One row per run in `usage/usage.jsonl` with the columns in Step 7
- [x] Parent run recorded so subagent runs link to the main run

### 8. Daily pipeline
**Owner:** Claude Code · **Folder:** `pipeline/` · **Design:** How this maps to production

- [x] `pipeline/run_daily.py` validates, loads, runs rules, creates or updates alerts, runs the agent and writes a summary
- [x] Rejects the whole batch on a failed check
- [x] Moves processed files to `processed/`
- [x] Stops calling the agent when a daily token budget is reached

## Phase 3: Human review and measurement

### 9. Investigator review screen
**Owner:** Antigravity · **Folder:** `ui/` · **Design:** Step 6

- [x] Queue sorted by risk rating then score, showing typology and token cost
- [x] Case view with clickable source IDs that open the transactions
- [x] Decision buttons (Escalate, Request more information, Dismiss) with a required reason
- [x] Suggested action shown but not preselected
- [x] Decisions saved to a `decisions` table with person and time

### 10. Evaluation scorecard
**Owner:** Codex · **Folder:** `eval/` · **Design:** Step 8

- [x] `eval/score.py` prints the six measures in Step 8
- [x] Reads case files, the answer key and the usage log
- [x] Writes `eval/scorecard.md` for committing as sample output

## Phase 4: Share it

### 11. Publish and present
**Owner:** You · **Design:** Step 10 and Presenting it to your community

- [x] README setup steps tested on a clean clone (2026-11-19: fresh clone of the branch, steps 1 to 10 except the Claude Code step; 108 tests passed)
- [x] Sample case files, scorecard and usage log committed (`docs/samples/`, `eval/scorecard.md`)
- [x] Demo GIF or recording (`docs/demo/demo.gif`, rebuilt with `scripts/make_demo_gif.py`)
- [x] CONTRIBUTING.md
- [x] Repo topics added (by the repo owner on 2026-11-19)
