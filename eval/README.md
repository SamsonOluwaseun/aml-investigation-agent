# eval/

Scorecard comparing synthetic case files with the private planted-case answer key.

**Owner:** Codex Â· **Build plan:** item 10 Â· **Design:** Step 8

Run from the repository root (Python 3.11+, standard library only):

```bash
python eval/score.py
python eval/score.py --db bank/bank.db --cases cases --usage usage/usage.jsonl --out eval/scorecard.md
python -m pytest eval
```

The command prints all six measures and writes the same results as Markdown.
`score(db_path, cases_dir, usage_path)` returns a dictionary for other callers.
The database is opened read-only. The report excludes answer-key notes and mappings.
The generated-on date comes from the latest case `saved_at`; without one it is
reported as unavailable. No wall-clock date is used.

Catch rate and typology use the demo denominator of 15 suspicious planted cases,
matched by customer ID. Missing files count as not caught; catch rate also requires
an alert. These measures are marked partial until all 15 have case files. False
alarms count High-rated look-alikes. Coverage includes open alerts and alerted and
investigated answer-key customers. These are demo targets, not industry benchmarks.

Citation checking counts every source-ID occurrence across every saved case,
including repetitions, and lists missing IDs once per case. It checks transaction,
customer, account and counterparty IDs, and screening/adverse-media row IDs. It
checks existence, not whether the record supports the claim. With no citations,
the report shows 0/0 and explains that no success rate was observed.

Token totals sum `total_tokens` for each usage task ID, including cache tokens
already present in that total. Mean and median cover only IDs with usage rows, including usage-only IDs, and
state the number of cases measured. A saved case without usage is labelled
"no usage logged" and excluded from these statistics. Per-case lines combine
customer kind, planted typology, risk, suggested action, outcome and usage. Handoff amplification divides all case tokens by the sum
of top-level `investigate` rows (no parent); a zero or missing denominator is
unavailable. Costs are API-equivalent. Recording-only measures have no numeric
pass target and are marked recorded. Missing usage logs and empty or missing case
directories produce a report with zeros and notes. Inputs otherwise follow the
case schema and usage log format; invalid JSON or an invalid bank is an input error.

`scorecard.md` is reproducible sample output from the checkout's available data.
Tests use a small temporary synthetic SQLite bank with no model or network.
