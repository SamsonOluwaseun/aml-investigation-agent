# agent/

Case file schema and notes for the investigation agent. The agent itself lives in `.claude/`:

- `.claude/skills/investigate/SKILL.md`, the `/investigate` skill
- `.claude/agents/evidence-gatherer.md`: calls the bank tools and returns a cited evidence pack
- `.claude/agents/typology-analyst.md`: compares the evidence with the rule hits and lists innocent explanations and gaps
- `.claude/agents/case-writer.md`: writes the case file JSON

**Owner:** Claude Code · **Build plan:** item 6 · **Design:** Step 5

## Run it

```bash
python bank/generate.py && python rules/run_rules.py   # a bank with an alert queue
claude                                                  # then type: /investigate C-001
```

Headless, as the daily pipeline does it:

```bash
claude -p "/investigate C-001" --mcp-config .mcp.json --strict-mcp-config \
  --tools Agent --allowedTools "Agent,mcp__aml-bank__*" --permission-mode dontAsk
```

`--tools Agent` removes the built-in file, search and shell tools, so the only way into the bank is the MCP tools. In an interactive session the skill tells the agent to use only the bank tools, and each subagent's `tools:` list contains only bank tools.

## How a case is built

1. The skill checks the alert with `get_alert`.
2. **Evidence gatherer** (bank read tools only): KYC, accounts, the alert window and one earlier window for a baseline, counterparties and screening. It returns at most 12 facts, each with the record IDs behind it.
3. **Typology analyst** (`get_alert` only): fit against each typology, the evidence against it, innocent explanations, gaps, a suggested risk rating and action.
4. **Case writer** (`get_alert` only): the JSON below.
5. The skill checks the format and calls `save_case_file`. That tool drops any claim with no source, or with source IDs that don't exist in the bank, forces the status to a draft, validates against the schema and writes `cases/<case_id>.json`.

Subagents pass summaries, not raw transaction lists, so each step stays small.

## Case file

[`case_file.schema.json`](case_file.schema.json) (JSON Schema 2020-12) matches DESIGN.md Step 5:

```json
{
  "case_id": "C-014",
  "customer_id": "CU-0231",
  "risk_rating": "High",
  "typologies": ["structuring"],
  "summary": "Two or three plain sentences",
  "evidence": [{"claim": "7 cash deposits of £8,500 to £9,900 in 12 days", "source": ["T-0088120", "T-0088131"]}],
  "innocent_explanations": ["Declared as a market trader"],
  "gaps": ["No source of funds on file"],
  "suggested_action": "Escalate",
  "status": "Draft for human review"
}
```

Valid source IDs: transactions `T-…`, customers `CU-…`, accounts `FAKE-AC-…`, counterparties `FAKE-EXT-…` and `FAKE-CASH-BRANCH`, screening entries `SL-n` and adverse media `AM-n`.

Check a saved file by hand:

```bash
python agent/case_file.py cases/C-001.json
pytest agent
```
