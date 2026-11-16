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

### Item 2: Daily batch files, issue #3
- Owner: Codex. Branch `issue-3-daily-batch`. In progress.

### Item 5 groundwork
- While Codex worked, I drafted the MCP server (`tools/`) on a local branch `wip-tools`. 12 tests pass against a hand-built bank. It becomes item 5's branch when that item starts.
