# Investigator review screen demo

This directory contains the demonstration GIF and documentation for the AML investigator review screen.

## What the demo GIF shows

The demo animation captures five sequential steps of an investigator reviewing and escalating a flagged case:

1. **Investigation queue**: The initial screen displays the prominent synthetic data banner and the open alert queue, ranked by risk rating (High > Medium > Low) and detection rule score. Each row indicates the customer ID, triggered typologies, token consumption, and illustrative API-equivalent cost.
2. **Case evidence view**: Scrolling to case C-001 (the default selected case) presents the AI-synthesised investigation summary, followed by specific factual claims cited with verifiable source IDs (`T-...` transactions, `CU-...` customer profiles, `FAKE-EXT-...` counterparties, `SL-n` screening list entries, and `AM-n` adverse media records).
3. **Interactive source inspection**: Clicking on a cited transaction ID button immediately displays the underlying synthetic banking record directly beneath the claims, enabling the investigator to audit facts against the raw database.
4. **Human decision form**: The investigator navigates to the decision section, selects **Escalate** (no action is preselected), documents the mandatory rationale ("Sanctions matches on two new payees; escalating for review."), and provides their investigator name.
5. **Decision audit confirmation**: Clicking **Save Decision** writes the decision to the database audit table and updates the interface to display a success confirmation alongside the case decision history log.

## Synthetic data proof of concept

All data presented in the review application and recorded in the demo GIF is entirely synthetic:

- All customer names, account numbers, transactions, counterparty names, and screening records are generated with fixed random seeds for reproducibility.
- No real banking data, customer personal information, or live financial infrastructure is involved.
- The AI agent gathers cited evidence and suggests actions, but an authorised human investigator must review and record every final decision.

## How to regenerate the demo GIF

Ensure dependencies from `requirements.txt` are installed in your Python 3.11+ environment.

### Step 1: Generate the bank database

```bash
python bank/generate.py
```

### Step 2: Run the typology detection rules

```bash
python rules/run_rules.py
```

Optional: to include C-019 in the queue, as the committed GIF does, also export and load the three demo batches (step 8 of the root [README](../../README.md#quick-start), with `--no-agent`).

### Step 3: Run the demo capture script

```bash
python scripts/make_demo_gif.py --db bank/bank.db
```

The script automatically:

1. Discovers a local Chromium browser (Microsoft Edge or Google Chrome).
2. Copies the bank database to a temporary directory so the original `bank/bank.db` is never modified.
3. Launches the Streamlit review screen in headless mode on an available local port.
4. Drives the browser over the Chrome DevTools Protocol (CDP) using `websockets` to capture all five frames.
5. Assembles and compresses the frames into an optimised animated GIF saved at `docs/demo/demo.gif`.
6. Gracefully shuts down the browser and application processes.

### Command-line options

| Option | Default | Purpose |
| --- | --- | --- |
| `--db` | `bank/bank.db` | Source SQLite database file |
| `--cases` | `docs/samples/cases` | Directory containing case JSON files |
| `--usage` | `docs/samples/usage.sample.jsonl` | Path to token usage JSONL log |
| `--out` | `docs/demo/demo.gif` | Output path for the animated GIF |
| `--browser` | Auto-detected | Explicit path to Microsoft Edge or Google Chrome executable |
