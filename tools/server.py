"""MCP server exposing the synthetic bank to Claude Code.

Run by Claude Code through .mcp.json (stdio). Every tool takes case_id first,
writes one line to tools/audit.jsonl and returns a small JSON result. All tools
are read-only except save_case_file. The answer key is never reachable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from tools import bank_tools, case_store  # noqa: E402

server = MCPServer(
    name="aml-bank",
    instructions=(
        "Read-only tools over a synthetic bank for AML investigation. "
        "Every tool takes case_id first. Use case_id 'QUEUE' for list_alerts. "
        "Results are capped; narrow date ranges rather than asking for everything."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


@server.tool(annotations=READ_ONLY)
def list_alerts(case_id: str = bank_tools.QUEUE, limit: int = 20) -> dict:
    """Open alerts in the queue, highest score first. Pass case_id "QUEUE"."""
    return bank_tools.list_alerts(case_id, limit=limit)


@server.tool(annotations=READ_ONLY)
def get_alert(case_id: str) -> dict:
    """Rule hits for the case and the transaction IDs that triggered them."""
    return bank_tools.get_alert(case_id)


@server.tool(annotations=READ_ONLY)
def get_customer(case_id: str, customer_id: str) -> dict:
    """KYC profile (occupation, declared income, risk rating, country) of the case customer."""
    return bank_tools.get_customer(case_id, customer_id=customer_id)


@server.tool(annotations=READ_ONLY)
def get_accounts(case_id: str, customer_id: str) -> dict:
    """Accounts held by the case customer and when they were opened."""
    return bank_tools.get_accounts(case_id, customer_id=customer_id)


@server.tool(annotations=READ_ONLY)
def get_transactions(case_id: str, account_id: str, date_from: str, date_to: str) -> dict:
    """Transactions on one of the case customer's accounts between two dates (YYYY-MM-DD, inclusive). At most 200."""
    return bank_tools.get_transactions(case_id, account_id=account_id, date_from=date_from, date_to=date_to)


@server.tool(annotations=READ_ONLY)
def get_counterparties(case_id: str, account_id: str) -> dict:
    """Who the account pays and is paid by, with counts, totals and first/last dates. At most 50."""
    return bank_tools.get_counterparties(case_id, account_id=account_id)


@server.tool(annotations=READ_ONLY)
def screen_name(case_id: str, name: str) -> dict:
    """Exact and close matches on the fake sanctions/PEP list and fake adverse media."""
    return bank_tools.screen_name(case_id, name=name)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def save_case_file(case_id: str, case_json: str) -> dict:
    """Save the finished case file (a JSON string) as a draft for human review. Uncited claims are dropped."""
    return case_store.save_case_file(case_id, case_json=case_json)


if __name__ == "__main__":
    server.run("stdio")
