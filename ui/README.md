# ui/

Investigator review screen. Shows the open case queue, cited evidence case files with interactive record inspection, and decision controls. A human investigator makes every decision here.

**Owner:** Antigravity · **Build plan:** item 9 · **Design:** Step 6

## What it does

1. **Investigation Queue**:
   - Ranks open alerts by **Risk Rating** (`High` > `Medium` > `Low` > `Not investigated yet`), then **Rule Score** (descending), then `case_id`.
   - Displays customer ID, rule score, typologies, token consumption, illustrative API-equivalent cost, and decision status.

2. **Case Evidence View**:
   - Displays the investigation summary, innocent explanations, and information gaps.
   - Every claim is cited with source IDs (`T-...` transactions, `CU-...` customers, `FAKE-AC-...` accounts, `FAKE-EXT-...` / `FAKE-CASH-...` counterparties, `SL-n` screening list matches, `AM-n` adverse media matches).
   - Clickable source ID buttons immediately inspect and display the underlying synthetic database records.
   - Displays the AI agent's suggested action as informational guidance only.

3. **Human Decision Recording**:
   - Decision options: **Escalate**, **Request more information**, or **Dismiss**.
   - No decision is preselected (radio has no default selection).
   - Mandatory reason and investigator identity validation before saving.
   - Saves decisions to the `decisions` table in the database with UTC ISO 8601 timestamps.
   - Displays current decision status and complete decision audit history.

4. **AI FinOps Cost Transparency**:
   - Aggregates total token usage per case from `usage/usage.jsonl`.
   - Shows an illustrative API-equivalent cost estimate based on standard model rates (Input: $15/M, Output: $75/M, Cache Write: $18.75/M, Cache Read: $1.50/M).

## How to run

Ensure dependencies (`streamlit`, `pytest`) are installed in your environment, then start the Streamlit review application:

```bash
streamlit run ui/app.py
```

### Environment Variables

Configure file and database paths through environment variables (or the sidebar UI inputs):

| Variable | Default | Purpose |
| --- | --- | --- |
| `AML_BANK_DB` | `bank/bank.db` | Path to the SQLite bank database |
| `AML_CASES_DIR` | `cases/` | Directory containing `<case_id>.json` files |
| `AML_USAGE_LOG` | `usage/usage.jsonl` | Path to the token usage log |

## Testing

Run unit and integration tests (including Streamlit `AppTest`):

```bash
pytest ui
```
