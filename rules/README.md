# Typology rules

**Owner:** Codex · **Build plan:** items 3 and 4 · **Design:** Step 3

Run from the repository root with Python 3.11+, using only the standard library:

```sh
python bank/generate.py
python rules/run_rules.py
python rules/run_rules.py --as-of 2026-10-28 --db bank/bank.db
```

`config.json` contains all detection thresholds, scoring weights and risk bands:
**DEMO VALUES, NOT REGULATORY**. High starts at 0.75, Medium at 0.5, otherwise Low.

The inclusive window is 30 calendar days, ending on `--as-of`, or the latest
transaction date by default. History covers the preceding 90 days, excluding the
current window. No wall-clock dates are used. An empty bank requires `--as-of`.

`typologies.py` exposes `structuring`, `rapid_pass_through`, `fan_in_fan_out`,
and `high_risk_link`, each taking `(conn, window_start, window_end)` and returning
hit dictionaries. `evaluate` combines the four; `band(score)` returns a risk band.
Dates may be ISO strings or `date` objects. Each hit contains customer ID,
typology, rounded score, at most 50 sorted transaction IDs, and a short reason.
Reasons describe the full pattern even when evidence IDs are capped.

Structuring uses any 14-calendar-day span and discounts activity comparable to
the historical maximum. Fan-in/fan-out compares distinct parties separately in
each direction over seven-calendar-day spans and skips historically comparable
peaks. FAKE-CASH-BRANCH is excluded from that count. Pass-through uses credits of
at least GBP 5,000 and subsequent transfers within 48 elapsed hours, excluding
routine card purchases and direct debits. Screening names match exactly,
ignoring case; either transaction or counterparty country can trigger.
These are demo heuristics, not attribution of individual outgoing funds to a
particular credit.

Pipeline use:

```python
from rules.run_rules import run
summary = run("bank/bank.db", as_of="2026-10-28")
```

The summary has `new`, `updated`, and `unchanged` case-ID lists, `window` with
`window_start`/`window_end`, `open_queue`, and `changes` with printable details.
The alerts table lives in the same database. New case numbers use the lowest
free C-### number in score-descending/customer-ID order. Customer IDs are unique;
existing cases keep their IDs, creation dates and review status. Multiple
typologies add 0.05 each to the highest hit score, capped at 1.0.

Only changed hits, typologies or scores cause an update to evidence, window and
updated date. Identical reruns leave stored rows untouched, even if the requested
date moves and evidence remains identical. Customers without current hits retain
their earlier alert for human review; rules never close cases. `unchanged` counts
only customers with current matches. Evaluation and persistence run in one SQLite
transaction, rolling back on failure.

Run the focused offline examples and bank regression checks:

```powershell
.venv\Scripts\python.exe -m pytest rules bank --basetemp=rules\.pytest_tmp
Remove-Item -LiteralPath rules\.pytest_tmp -Recurse -Force
```

Tests use small hand-built databases for date boundaries, history comparisons,
exact screening names, normal bills, deterministic case IDs and idempotent updates.
