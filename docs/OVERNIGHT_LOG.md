# Overnight build log

## Summary

_In progress. Final summary is written here when the run finishes or stops._

## Decisions for Oluwaseun

- **Codex cannot commit.** Codex 0.169.0 runs in the `workspace-write` sandbox, which blocks writes to `.git`. Codex does the work and Claude Code commits it on the issue branch, with commit messages prefixed `Codex:`. The alternative (`--dangerously-bypass-approvals-and-sandbox`) would remove all sandboxing, so I did not use it.
- **Python environment.** pytest was not installed system-wide. A local `.venv` (git-ignored) was created from `requirements.txt` and is used for all test runs.
- **Log commits.** This log is committed straight to `develop` (never `main`) from a separate worktree, so it does not clash with feature branches.
- **No pull requests could be opened.** The `gh` CLI on this machine is signed in as `SamlyticsDS`, which has read-only access to `SamsonOluwaseun/aml-investigation-agent` (`createPullRequest` failed with "must be a collaborator"). Git pushes work through a different stored credential, which I deliberately did not extract. So each finished branch is pushed and then merged into `develop` locally with `git merge --no-ff`, and **the merge commit message is the pull request description** (criteria and how each was met). All issue branches remain on GitHub, so you can open real PRs afterwards if you want the history in GitHub's UI. To fix this for next time: add `SamlyticsDS` as a collaborator, or run `gh auth login` as `SamsonOluwaseun`.
- **Issues are created by `SamlyticsDS`.** Issue creation works on a public repo without write access. Issues cannot be closed by that account, so they stay open after merge, and you may want to close #2 onwards.
- **pytest temp folder.** Codex's sandbox created `%TEMP%\pytest-of-SamlyticsAI` with permissions the normal user cannot read, which breaks `tmp_path`. My test runs set `PYTEST_DEBUG_TEMPROOT` to a scratch folder. If plain `pytest` fails on your machine with `PermissionError` on that folder, delete it.
- **Root `pytest.ini`** added (`pythonpath = .`, `-p no:cacheprovider`) so `pytest` works from the repo root. The cache is off because OneDrive was refusing the cache folder.
- **Answer-key IDs are `PC-###`** and alert IDs are `C-###`, so they cannot be confused. `planted_cases` has an extra `is_suspicious` column (1 = planted case, 0 = look-alike). The scorecard joins on `customer_id`.
- **Daily batch values follow the bank, not the sample file.** `data/sample/transactions_2026-11-16.csv` uses accounts (`AC-1102`) and channels (`cash_branch`) that do not exist in the generated bank. Item 2 files use the same columns but the bank's own IDs and vocabulary, so they load and the rules see them. The sample file stays as an illustration. The pipeline will be tested with generated day files.
- **Rule tests read the answer key.** Item 4 must check every planted case is caught, which needs the answer key. Only `rules/tests/` reads `planted_cases` as a test oracle; rule code never does, and a guard test enforces that.
- **Agent test budget.** You asked for no more than 3 cases when testing the agent in items 6 and 8. I treated that as 3 in total: case 1 (C-001, a planted sanctions case), case 2 (a structuring look-alike), case 3 (one new alert through the pipeline).
- **How the agent is kept away from the answer key.** In headless runs, `--tools Agent` removes every built-in file, search and shell tool, so the only way into the data is the MCP bank tools. Subagents list only bank tools in their `tools:` frontmatter, and a test enforces this. In an interactive session the main agent could still read files if it ignored the skill's instructions, so for demos use the headless command or keep to `/investigate`.
- **`list_alerts` takes `case_id` too.** Every tool must take `case_id` first, but listing the queue is not about one case, so `list_alerts` takes the reserved case ID `QUEUE`.

## Log

### Setup (2026-11-16)
- Created `develop` from `main` and pushed it.
- Issue #2 (item 1) was already open. Codex had finished a first pass on `issue-2-fake-bank`, uncommitted because of the sandbox.

### Item 1: Fake bank generator, issue #2, merged
- Owner: Codex. Branch `issue-2-fake-bank`, merged into `develop` as `7a73d09` (the merge message is the PR description).
- Review round 1 sent back: planted IDs clashed with alert IDs; planted customers were CU-0001 to CU-0027 in label order and listed in the README; no XZ payments despite the notes; no fan-out; identical copies of every pattern; every customer rated Low; cash shared a counterparty with transfers; README had a BOM.
- Review round 2 sent back: suspicious fan cases had become all fan-out; cash-business look-alikes declared £30k to £94k income against about £450k of cash.
- Result: all 7 criteria met. `pytest bank` 1 passed (double-run identical dump). One known nit left: fan-out club look-alikes have no inbound money.

### Item 2: Daily batch files, issue #3, merged
- Owner: Codex. Branch `issue-3-daily-batch`, merged as `1883a3e`. No review round needed.
- `--day` writes the CSV and control file using the bank's own IDs. A demo structuring customer adds 2 cash deposits a day and crosses the 5-in-14-days threshold on day 3. `pytest bank` 9 passed.

### Item 3: Typology rules, issue #4, merged
- Owner: Codex. Branch `issue-4-typology-rules`, merged as `81c1155`. No review round needed.
- I checked it independently on a fresh bank: 15/15 planted cases alerted with the right typology, all High; 3/12 look-alikes alerted, all Low; 0 ordinary customers alerted; reruns idempotent.

### Item 4: Rule tests, issue #5, merged
- Owner: Codex. Branch `issue-5-rule-tests`, merged as `18ffdd2`. One review round: the per-case test skipped 12 of 27 parameters. It now collects exactly 15 + 12 cases.
- `pytest rules bank` 46 passed, 0 skipped, in about 8 seconds.

### Item 5: Bank tools (MCP server), issue #6, merged
- Owner: Claude Code. Branch `issue-6-bank-tools`, merged as `57e5239`.
- Built on mcp 2.3.0 (`MCPServer`). Eight case-scoped tools with a read-only DB connection, result caps, audit lines and no route to the answer key. 13 tests.
- Live check (agent case 1 of 3): headless `/investigate C-001` on the work branch. 14 audited tool calls, saved a valid case file (High, Escalate, 9 cited claims, none dropped), 140 seconds. Usage: top-level run 102k tokens, subagents 45k / 14k / 17k, handoff amplification 1.75.
