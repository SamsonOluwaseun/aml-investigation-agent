# Overnight build log

## Summary

**Update 2026-11-19:** item 11 (issue [#12](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/12)) is merged into `develop` as well, apart from the repo topics, which need the repo owner. See the item 11 entry at the end of the log.

**Finished.** Items 1 to 10 are built, reviewed and merged into `develop`. Item 11 was not started overnight, as you asked. `main` is untouched (`9bacbb5`). The full suite passes on a clean `develop` checkout with no generated data: **105 tests passed**.

### Items completed

| Item | Owner (who actually did it) | Issue | Branch | Merged into develop | Review rounds |
| --- | --- | --- | --- | --- | --- |
| 1. Fake bank generator | Codex | [#2](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/2) | `issue-2-fake-bank` | `7a73d09` | 2 |
| 2. Daily batch files | Codex | [#3](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/3) | `issue-3-daily-batch` | `1883a3e` | 0 |
| 3. Typology rules | Codex | [#4](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/4) | `issue-4-typology-rules` | `81c1155` | 0 |
| 4. Rule tests | Codex | [#5](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/5) | `issue-5-rule-tests` | `18ffdd2` | 1 |
| 5. Bank tools (MCP server) | Claude Code | [#6](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/6) | `issue-6-bank-tools` | `57e5239` | – |
| 6. Investigation skill and subagents | Claude Code | [#7](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/7) | `issue-7-investigate-skill` | `76b9d64` | – (one criterion left for you) |
| 7. Usage logging hooks | Claude Code | [#8](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/8) | `issue-8-usage-hooks` | `f99fab2` | – |
| 8. Daily pipeline | Claude Code | [#9](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/9) | `issue-9-daily-pipeline` | `4a5c725` | – |
| 9. Investigator review screen | **Antigravity** (headless `agy` CLI) | [#10](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/10) | `issue-10-review-screen`, `issue-10-review-screen-fix` | `0c96fb9`, `0c93e07` | 2 |
| 10. Evaluation scorecard | Codex | [#11](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues/11) | `issue-11-scorecard` | `97a1e81` | 1 |

### Pull requests

**None were opened**, because the `gh` account on this machine (`SamlyticsDS`) has read-only access to the repo. Every branch was pushed, then merged locally with `--no-ff`, and **each merge commit message is that item's pull request description**, listing every criterion and how it was met. Run `git log --merges develop` to read them. All branches are still on GitHub if you want real PRs for the record. See the first decision below.

### Left open

- **Item 6, interactive run not verified.** The headless runs work. Please run `/investigate C-001` once in an interactive Claude Code session (venv active, approve the `aml-bank` tools) and tick the last box in `docs/BUILD_PLAN.md`.
- **Issues #2 to #11 are still open.** `SamlyticsDS` cannot close them.
- **Item 11** is yours: README setup steps, sample outputs, demo GIF, CONTRIBUTING.md and topics.

### Decisions for you to check

Listed in full in the next section. The ones most worth a look:
1. Merging locally because no PRs could be opened, and how to fix the `gh` account.
2. Codex's sandbox can't commit, so Claude Code commits Codex's work under `Codex:` messages. Antigravity's headless mode can't run commands, so Claude Code ran its tests.
3. The agent test budget was 3 cases in total: C-001 (planted), C-016 (look-alike) and C-019 (daily pipeline).
4. The daily batch files use the bank's IDs, not the illustrative IDs in `data/sample/`.

### Results worth knowing

- Rules on a fresh bank: 15/15 planted cases alerted with the right typology, all High. 0/12 look-alikes High. 0 ordinary customers alerted.
- Agent: C-001 (planted sanctions case) was rated **High, Escalate**. C-016 (a cash-business look-alike) was rated **Medium, Request more information**, reasoning from its long history and declared income. C-019 (the daily demo pattern) was rated **Medium, Request more information**. 121 of 121 cited IDs exist.
- Tokens per case: about 173k to 179k (API-equivalent), around 140 seconds per case. Handoff amplification is 1.72 to 1.75 (subagents add about 75% on top of the main run).
- `eval/scorecard.md` is committed, generated from those three runs. Catch rate and typology are marked *partial*, because only 1 of 15 planted cases was investigated.

### What to do next

1. Fix GitHub access (add `SamlyticsDS` as a collaborator, or `gh auth login` as `SamsonOluwaseun`). Then open a PR `develop → main` when you're happy, and close issues #2 to #11.
2. Do the interactive `/investigate C-001` check (item 6).
3. If you want a full scorecard, run all 19 alerts: `python pipeline/run_daily.py` handles new alerts only, so loop `claude -p "/investigate C-0NN"` (the README in `agent/` has the exact flags). Expect about 175k tokens per case.
4. Start item 11. The three case files and usage rows from tonight are copies outside the repo, because `cases/` and `usage/*.jsonl` are git-ignored. Regenerate them with the steps in `pipeline/README.md`, or tell me to add sample copies under `docs/samples/`.
5. Clean-up when you're done: the extra worktrees next to the repo (`aml-develop`, `aml-work`, `aml-ui`, `aml-eval`) and the local `wip-tools` branch can be removed with `git worktree remove <path>` and `git branch -D wip-tools`.

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

### Item 6: Investigation skill and subagents, issue #7, merged (one criterion left for you)
- Owner: Claude Code. Branch `issue-7-investigate-skill`, merged as `76b9d64`.
- Agent case 2 of 3: headless `/investigate C-016`, a structuring look-alike (a declared cash market business). Result: **Medium, Request more information**, 8/8 claims kept. The reasoning weighed 51 historical deposits and the declared income. The main agent also caught an unsupported figure from the analyst and removed it. So the agent can tell innocent activity from suspicious, not just confirm it.
- **Not verified: the interactive run.** Nobody was at the keyboard, so the criterion "Works interactively on one case" is left unticked. To check: open the repo in Claude Code with the venv active, run `/investigate C-001` and approve the bank tools.

### Item 7: Usage logging hooks, issue #8, merged
- Owner: Claude Code. Branch `issue-8-usage-hooks`, merged as `f99fab2`.
- Verified against the real payloads from Claude Code 2.1.325 (captured with `AML_HOOK_DEBUG=1`). Subagent tool calls carry `agent_id` and `agent_type`, and `SubagentStop` gives `agent_transcript_path`. The top-level row matched the CLI's own reported usage exactly.

### Item 8: Daily pipeline, issue #9, merged
- Owner: Claude Code. Branch `issue-9-daily-pipeline`, merged as `4a5c725`.
- Agent case 3 of 3: three daily batches with the agent on and `--max-cases 1`. Days 1 and 2 had no new alerts. Day 3 raised C-019 (the demo structuring customer), which was investigated and saved (Medium, Request more information). The budget counter read 172,759 tokens, exactly the four hook rows.
- Finding: the agent flagged deposits dated 17 and 18 November as "after the pack was prepared", because the demo batch dates were later than the real date. For demos, use batch dates on or before the day you run them.
- My mistake: clearing `cases/` before this run deleted the C-016 case file.

### Item 10: Evaluation scorecard, issue #11, merged (before item 9)
- Owner: Codex. Branch `issue-11-scorecard`, merged as `97a1e81`. It ran in parallel with item 9 in its own worktree and merged first, because the two don't depend on each other.
- Review round 1: the token mean counted cases without usage as 0; the per-case lines were split and showed a "right typology" for look-alikes; the output wasn't real Markdown; the Met column said "partial" for record-only measures.
- `eval/scorecard.md` was generated from the three real runs. 5 tests.

### Item 9: Investigator review screen, issue #10, merged
- Owner: **Antigravity**, run headless with `agy -p`. The brief was passed as a file, because PowerShell split long quoted prompts. `--mode auto` is not available on this account, and headless mode auto-denies commands, so Antigravity wrote the code and I ran every test and check.
- Review round 1: `streamlit run ui/app.py` crashed on `from ui.data import`, because only `ui/` is on the import path (reproduced in an isolated interpreter). It was fixed with a regression test. The success message now shows the stored time.
- Review round 2 (after merge): one test needed the real `bank/bank.db`, so it failed on a clean clone. It's now self-contained and merged as `0c93e07`.
- Verified in Streamlit's AppTest: the decision radio has no default; saving without a reason is refused; a saved row has the person, UTC time and suggested action; clicking `T-0054092` opens the transaction.
- Decision: I did not use `--dangerously-skip-permissions` to let Antigravity run commands. It would have approved every tool with no limit.
- Mistake: I deleted `cases/C-016.json` while clearing old outputs. I recreated it byte for byte from the run output (it validates, and all 25 cited transactions exist). Copies of all three case files and the usage logs are kept outside the repo.

### Item 11: Publish and present, issue #12, merged (2026-11-19)

- Branch `issue-12-publish`. Orchestrated by Claude Code, with Codex on the docs and Antigravity on the demo recording.
- **Codex** wrote the full README quick start (every command checked against the argparse definitions), `CONTRIBUTING.md` and `docs/samples/README.md`. My review changes: kept the item 6 note in the status table, said the C-016 usage rows were not kept, added "never push to or merge into `main`", and allowed `planted_cases` in tests as well as `eval/`.
- **Claude Code** added the samples: the three case files in `docs/samples/cases/` and the C-001 and C-019 usage rows in `docs/samples/usage.sample.jsonl`, with local transcript paths replaced by `<local transcript>`. The C-016 usage rows were never saved, so they are missing. `agent/tests/test_samples.py` checks that the case files validate and that the samples hold no local paths or answer-key IDs. `.gitignore` now ignores only the root `/cases/`, so the samples can be committed.
- **Clean clone:** I cloned the pushed branch from GitHub and ran README steps 1 to 10, except the Claude Code step, to save tokens. The first try failed at `pip install` with `WinError 3`, because the deep scratchpad path plus streamlit's nested files passed Windows' 260-character limit. At a shorter path every step passed: 108 tests, the bank, rules, three batches with `--no-agent` (C-019 raised), the review screen health check, and the scorecard. The README now has a short-path tip for Windows.
- **Antigravity** wrote `scripts/make_demo_gif.py`, which drives headless Edge or Chrome over the DevTools protocol and saves a five-frame GIF, plus `docs/demo/README.md` and offline tests. The first headless run stopped at once, because it tried a terminal command, which headless mode refuses. The retry told it to only read and write files. Review round 1 (Antigravity): my brief named tornado, but streamlit 1.67 no longer ships it, so it switched to `websockets` (which streamlit needs), imported lazily, and the log files are now closed so the temporary folder is removed. Fixes I made myself after round 1: JavaScript value setting didn't reach Streamlit, so the save step failed. The script now types through `Input.insertText` with focus emulation and presses Enter. I also hid the sidebar, which showed local file paths including the Windows username, and Streamlit's Deploy toolbar. I checked all five frames by eye. The source `bank.db` hash was unchanged.
- **Repo topics: not done.** `gh repo edit --add-topic` returned HTTP 404, because `SamlyticsDS` has no admin rights. Run as the repo owner: `gh repo edit SamsonOluwaseun/aml-investigation-agent --add-topic aml,anti-money-laundering,ai-agents,claude-code,mcp,synthetic-data,llm,python,streamlit`
- Tests: full suite 118 passed (105 before, plus 3 sample tests and 10 demo script tests).

### Clean-up and GitHub access (2026-11-19)

- Removed the extra worktrees (`aml-develop`, `aml-work`, `aml-ui`, `aml-eval`, `aml-pub`) and deleted the local `wip-tools` branch, after checking that none had uncommitted work and that `develop` contains everything on `wip-tools`. The main checkout is now on `develop`.
- `SamlyticsDS` now has write access. Closed issues #2, #3, #4, #5, #6, #8, #9, #10 and #11 with the merge commit for each. Left #7 open (interactive `/investigate` check) and #12 open (repo topics). Topics still return HTTP 404 with write access, because they need admin rights.
- Opened a pull request from `develop` to `main` for review. It is not merged.
