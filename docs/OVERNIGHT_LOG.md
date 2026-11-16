# Overnight build log

## Summary

_In progress. Final summary is written here when the run finishes or stops._

## Decisions for Oluwaseun

- **Codex cannot commit.** Codex 0.169.0 runs in the `workspace-write` sandbox, which blocks writes to `.git`. Codex does the work and Claude Code commits it on the issue branch, with commit messages prefixed `Codex:`. The alternative (`--dangerously-bypass-approvals-and-sandbox`) would remove all sandboxing, so I did not use it.
- **Python environment.** pytest was not installed system-wide. A local `.venv` (git-ignored) was created from `requirements.txt` and is used for all test runs.
- **Log commits.** This log is committed straight to `develop` (never `main`) from a separate worktree, so it does not clash with feature branches.

## Log

### Setup (2026-11-16)
- Created `develop` from `main` and pushed it.
- Issue #2 (item 1) was already open. Codex had finished a first pass on `issue-2-fake-bank`, uncommitted because of the sandbox.
