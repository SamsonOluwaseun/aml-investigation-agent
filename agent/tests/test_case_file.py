"""Case file schema tests. No model, no network."""

import copy
import json
import re
from pathlib import Path

import pytest

from agent.case_file import load_schema, validate

REPO = Path(__file__).resolve().parents[2]

GOOD = {
    "case_id": "C-014",
    "customer_id": "CU-0231",
    "risk_rating": "High",
    "typologies": ["structuring"],
    "summary": "Two or three plain sentences",
    "evidence": [{"claim": "7 cash deposits of £8,500 to £9,900 in 12 days", "source": ["T-0088120", "T-0088131"]}],
    "innocent_explanations": ["Declared as a market trader"],
    "gaps": ["No source of funds on file"],
    "suggested_action": "Escalate",
    "status": "Draft for human review",
}


def test_design_example_is_valid():
    assert validate(GOOD) == []


def test_schema_matches_design_doc_fields():
    """The required fields are exactly the ones in the DESIGN.md Step 5 example."""
    design = (REPO / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    block = re.search(r"The case file is fixed JSON.*?```json\n(.*?)```", design, re.S).group(1)
    example = json.loads(block)
    assert set(load_schema()["required"]) == set(example)
    assert validate(example) == []


@pytest.mark.parametrize("change, problem", [
    (lambda c: c.pop("gaps"), "gaps: missing"),
    (lambda c: c.update(status="Closed"), "status"),
    (lambda c: c.update(suggested_action="File a SAR"), "suggested_action"),
    (lambda c: c.update(risk_rating="Critical"), "risk_rating"),
    (lambda c: c.update(typologies=["smurfing"]), "typologies[0]"),
    (lambda c: c["evidence"][0].update(source=[]), "evidence[0].source"),
    (lambda c: c["evidence"][0].pop("source"), "evidence[0].source: missing"),
    (lambda c: c.update(innocent_explanations=[]), "innocent_explanations"),
    (lambda c: c.update(evidence=[]), "evidence"),
    (lambda c: c.update(extra="x"), "extra: not allowed"),
    (lambda c: c.update(case_id="PC-001"), "case_id"),
    (lambda c: c.update(summary="x" * 801), "summary"),
])
def test_invalid_files_are_rejected(change, problem):
    case = copy.deepcopy(GOOD)
    change(case)
    errors = validate(case)
    assert any(problem in e for e in errors), errors


def test_subagents_only_have_bank_tools():
    """Subagents can reach the bank only through the MCP tools: no file, shell or web tools."""
    for name in ("evidence-gatherer", "typology-analyst", "case-writer"):
        text = (REPO / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
        tools_line = next(line for line in text.splitlines() if line.startswith("tools:"))
        tools = [t.strip() for t in tools_line.split(":", 1)[1].split(",")]
        assert tools and all(t.startswith("mcp__aml-bank__") for t in tools), (name, tools)
        assert "mcp__aml-bank__save_case_file" not in tools


def test_skill_runs_the_three_subagents_in_order():
    text = (REPO / ".claude" / "skills" / "investigate" / "SKILL.md").read_text(encoding="utf-8")
    positions = [text.index(name) for name in ("evidence-gatherer", "typology-analyst", "case-writer")]
    assert positions == sorted(positions)
    assert "save_case_file" in text and "Draft for human review" in text
