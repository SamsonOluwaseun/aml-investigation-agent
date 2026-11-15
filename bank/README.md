# bank/

Synthetic bank generator. Creates `bank.db` (SQLite) with customers, accounts, transactions, counterparties, a fake screening list, fake adverse media and the planted cases used as the answer key.

**Owner:** Codex · **Build plan:** items 1 and 2 · **Design:** Step 2

Planned commands:

```bash
python bank/generate.py                    # build bank.db with a fixed seed
python bank/generate.py --day 2026-11-16   # write one day's batch file to incoming/
```

`bank.db` is generated, not committed.
