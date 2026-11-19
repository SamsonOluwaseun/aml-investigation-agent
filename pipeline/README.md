# pipeline/

Daily batch run. Picks up the day's file from `incoming/`, validates it against its control file, loads it, runs the rules over a rolling 30-day window, creates or updates alerts, runs the agent on new alerts within a token budget and writes a run summary.

**Owner:** Claude Code · **Build plan:** item 8 · **Design:** How this maps to production

## Run it

```bash
python bank/generate.py                         # once: build the bank
python bank/generate.py --day 2026-11-16        # write incoming/transactions_2026-11-16.csv + .control.json
python pipeline/run_daily.py --day 2026-11-16 --max-cases 1
```

Options:

| Option | Default | What it does |
| --- | --- | --- |
| `--day` | required | Batch date |
| `--budget-tokens` | 1,500,000 (or `AML_DAILY_TOKEN_BUDGET`) | Daily token budget across all agent runs for that batch day |
| `--max-cases` | no limit | Investigate at most this many new alerts |
| `--no-agent` | off | Load and run rules only |
| `--db`, `--incoming`, `--processed`, `--usage-log` | repo defaults | Paths |

## What it checks

The whole batch is rejected, nothing is loaded and the exit status is 2 if any of these fail:

- the columns match the agreed header exactly
- the row count, total amount, date and file name match the control file
- there are no duplicate transaction IDs in the file, and none already loaded
- amounts are positive numbers, direction is `in` or `out`, every timestamp falls on the batch date
- every account exists and belongs to the stated customer, and every counterparty exists
- the batch has not already been processed

On success the rows are loaded in one transaction, both files move to `processed/` and the summary is written to `processed/summary_<day>.txt`.

## The agent step

For each new alert, the pipeline runs Claude Code headless:

```bash
claude -p "/investigate C-019" --output-format json --mcp-config <bank tools> --strict-mcp-config \
  --tools Agent --allowedTools "Agent,mcp__aml-bank__*" --permission-mode dontAsk
```

`--tools Agent` switches off every built-in file, search and shell tool, so the agent can reach the bank only through the MCP tools and cannot read the generator or the answer key. Set `AML_CLAUDE_BIN` if `claude` is not on your `PATH`.

Before each case it adds up the tokens that the usage hook logged for this batch day (`pipeline_day` in `usage/usage.jsonl`). When the budget is reached, the remaining alerts wait for the next run. If hooks are off, it falls back to the usage the CLI reports. Token figures are API-equivalent; on a subscription they are not money spent.

The sample file in `data/sample/` shows the format, but it uses illustrative account IDs that are not in the generated bank. Use `bank/generate.py --day` to make loadable batches.

## Tests

```bash
pytest pipeline     # generated bank and day files, fake agent, no model
```
