# Contributing

Follow the [quick start](README.md#quick-start) to set up Python 3.11 or later, create a virtual environment and install the dependencies. Read the [design](docs/DESIGN.md) and pick an item from the [build plan](docs/BUILD_PLAN.md). A synthetic example of a new typology or an innocent look-alike is a good first contribution.

Create an `issue-<number>-<short-name>` branch from `develop`. Always target `develop` when opening a pull request. Never push to or merge into `main`; the maintainer promotes `develop` to `main`.

## Ground rules

- Use synthetic data only. Keep real names, account numbers, sort codes and other bank data out of the repo.
- Use SQLite and the Python standard library where possible. Do not add paid services.
- Use fixed random seeds. Keep rule thresholds in one config file and label them as demo values.
- Put `case_id` first in every function and tool that touches a case.
- Rules detect suspicious patterns. The agent gathers evidence and suggests an action. A human makes the decision.
- Cite at least one transaction or record ID for every claim in a case file.
- Read the `planted_cases` answer key only in `eval/` and in tests. Keep it out of tools, prompts and the review screen.
- Keep tool results small. Summarise records instead of returning raw rows.
- Keep a README in each folder that explains what it does and how to run it.

## Folder ownership

| Owner | Paths |
| --- | --- |
| Codex | `bank/`, `rules/`, `eval/` |
| Claude Code | `agent/`, `tools/`, `usage/`, `pipeline/`, `.claude/`, `.mcp.json` |
| Antigravity | `ui/` |

Keep changes within your assigned paths. Flag changes needed elsewhere in the pull request. Claude Code reviews pull requests against the build plan.

## Tests and pull requests

Run `pytest` from the repository root with the virtual environment active. Tests run without a model or network access.

In the pull request, link the issue, list each acceptance criterion and explain how you met it. Include what changed, which files you touched, and the tests you ran with their results. Check for secrets and personal details before pushing.

## Reporting issues

Open a GitHub issue with the commands you ran, what you expected and what happened. Include your operating system and Python version. Use synthetic examples and remove secrets and local paths from logs. [GitHub issues](https://github.com/SamsonOluwaseun/aml-investigation-agent/issues)
