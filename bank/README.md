# Synthetic bank

**Owner:** Codex · **Build plan:** items 1 and 2 · **Design:** Step 2

Run from the repository root with Python 3.11 or newer, with no dependencies or network:

```sh
python bank/generate.py
```

This replaces `bank/bank.db` regardless of the working directory. The root
`.gitignore` excludes `*.db`; do not commit the database. Daily batch export
(`--day`) belongs to build plan item 2 and is not implemented yet.

The seed is fixed at `20261115`, and dates cover May–October 2026. There are
500 customers and 600 accounts, with six months of salaries, bills and card
spending scaled to declared annual GBP income. KYC includes varied occupations,
mostly Low risk ratings with some Medium and a few High, and varied onboarding
dates before May 2026. Every fifth customer also has
an empty savings account. Amounts are positive GBP values rounded to pennies;
`direction` is `in` or `out`. Timestamps are synthetic local ISO 8601 times.
All customer and counterparty names start with `FAKE`, as do account identifiers.
`XZ` is a fictional high-risk country marker. No real banking data is used.

The seven tables are `customers`, `accounts`, `transactions`, `counterparties`,
`screening_list`, `adverse_media`, and `planted_cases`, with the Step 2 columns,
primary keys and foreign keys. Screening and media records are fictional.
All external parties, including the dedicated FAKE-CASH-BRANCH cash source, have counterparty records.

The generator writes 27 answer-key rows: 15 suspicious cases and 12 innocent
look-alikes. `planted_cases.is_suspicious` distinguishes them (`1` / `0`). Only
`eval/` should read this key; the generator only writes it. Cases PC-001 through PC-027
use distinct customers sampled across the bank with shuffled scenario labels. Labels are not exposed in customer names
or transaction columns. Typology values and suspicious counts are:

| Typology | Suspicious | Innocent look-alikes |
| --- | --- | --- |
| structuring | 4 | 3 |
| rapid_pass_through | 4 | 3 |
| fan_in_fan_out | 4 | 3 |
| high_risk_link | 3 | 3 |

Pattern starts and amounts vary with the seeded RNG. All recent patterns fit
inside the final 30 days ending on the last transaction date:

- Six cash deposits of GBP 8,000 to 9,999 in eleven days. Look-alikes are
  declared cash businesses with comparable deposits in the prior five months.
- A GBP 40,000 to 65,000 receipt with 85 to 97 percent paid onward within
  24 hours. Equipment-dealer look-alikes pay four days later, outside 48 hours.
- Twelve distinct senders or recipients in four days, including suspicious
  fan-in and fan-out. Subscription-club look-alikes have comparable historical activity.
- Payments to an exact fake sanctions-list name and fictional XZ.
  Look-alikes pay a distinct, similarly named supplier in GB.

Cash-business, equipment-dealer and subscription-club look-alikes receive no
personal salary credits. Their declared annual income is at least their six-month
inbound takings annualised and rounded up to GBP 1,000 (or their original declared
income, if higher).

Amounts illustrate demo patterns, not regulatory thresholds. Detection thresholds
will belong to the rules configuration in build plan item 3.
The generator prints customers, accounts, transactions, planted cases and look-alikes.
For reproducibility, run twice and compare SHA-256 hashes of UTF-8
`"\n".join(connection.iterdump())` from each run using the same Python/SQLite
runtime. Logical dumps avoid relying on SQLite file layout.

Run the offline acceptance checks with `python -m bank.test_generate` (standard
library only), or `.venv\Scripts\python.exe -m pytest bank -q` if pytest is installed.
They generate two temporary databases, compare complete logical dumps, and check
schema, integrity, foreign keys, monthly coverage, fake names, labels and patterns.
The full-dump comparison explicitly inspects the answer key for this acceptance
check; normal application reads of that table remain restricted to `eval/`.
