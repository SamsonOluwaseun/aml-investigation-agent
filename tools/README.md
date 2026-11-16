# tools/

Local MCP server that lets Claude Code query the fake bank, the way an investigator queries core systems. The agent sees only what these tools return. It never gets the raw database or the answer key.

**Owner:** Claude Code · **Build plan:** item 5 · **Design:** Step 4

## Tools

| Tool | Returns |
| --- | --- |
| `list_alerts(case_id="QUEUE", limit=20)` | Open alerts, highest score first (at most 50) |
| `get_alert(case_id)` | Rule hits, scores, reasons and triggering transaction IDs |
| `get_customer(case_id, customer_id)` | KYC profile: occupation, declared income, risk rating, country, onboarding date |
| `get_accounts(case_id, customer_id)` | Accounts and when they were opened |
| `get_transactions(case_id, account_id, date_from, date_to)` | Transactions in a date range, at most 200, with totals and a `truncated` flag |
| `get_counterparties(case_id, account_id)` | Who the account pays and is paid by, with counts, totals and first/last dates (at most 50) |
| `screen_name(case_id, name)` | Exact and close matches on the fake sanctions/PEP list (`SL-n`) and adverse media (`AM-n`) |
| `save_case_file(case_id, case_json)` | Validates and stores the draft case file in `cases/<case_id>.json` |

Rules every tool follows:

- `case_id` comes first. It must be an alert in the queue (`list_alerts` uses the reserved ID `QUEUE`).
- Each call appends one line to `tools/audit.jsonl`: time, case, tool, arguments and result size, or the error.
- Scope is limited to the case: customer and account tools refuse records that don't belong to the alert's customer.
- Read tools open the database read-only (`mode=ro`). `save_case_file` is the only tool that writes, and it writes only to `cases/`.
- The answer key table is not reachable. Every query is a fixed SQL string in `bank_tools.py`, and a test checks that the table name appears nowhere in this folder's code.
- `save_case_file` drops evidence claims with no source or with source IDs that don't exist in the bank, sets the status to `Draft for human review` and validates against `agent/case_file.schema.json` before writing.

## Run it

Claude Code starts the server from `.mcp.json` when you open the repo (activate the virtualenv first so `python` has the `mcp` package). To start it by hand:

```bash
python tools/server.py      # stdio MCP server
pytest tools                # tests on a tiny hand-built bank, no model
```

Settings: `AML_BANK_DB` (default `bank/bank.db`), `AML_AUDIT_LOG` (default `tools/audit.jsonl`), `AML_CASES_DIR` (default `cases/`).

Built on the MCP Python SDK 2.x (`mcp.server.mcpserver.MCPServer`).
