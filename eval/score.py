"""Evaluate synthetic investigations against the bank's private answer key."""
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean, median

# Demo starting points from DESIGN.md Step 8, not industry benchmarks.
TARGETS = {"planted": 15, "catch": 13, "false_alarms": 3, "typology": 12}
ROOT = Path(__file__).resolve().parent.parent


def source_exists(case_id, source_id, conn):
    """Check a cited record by its explicit ID kind; never infer from names."""
    kinds = (("T-", "transactions", "txn_id"),
             ("CU-", "customers", "customer_id"),
             ("FAKE-AC-", "accounts", "account_id"),
             ("FAKE-EXT-", "counterparties", "counterparty_account"))
    for prefix, table, column in kinds:
        if source_id.startswith(prefix):
            return conn.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (source_id,)).fetchone() is not None
    if source_id == "FAKE-CASH-BRANCH":
        return conn.execute("SELECT 1 FROM counterparties WHERE counterparty_account=?", (source_id,)).fetchone() is not None
    match = re.fullmatch(r"(SL|AM)-([1-9][0-9]*)", source_id)
    if match:
        table = "screening_list" if match[1] == "SL" else "adverse_media"
        return conn.execute(f"SELECT 1 FROM {table} WHERE rowid=?", (int(match[2]),)).fetchone() is not None
    return False


def score(db_path, cases_dir, usage_path):
    """Return JSON-serializable measures, coverage and per-case results.

    Missing investigations remain in the fixed 15-case denominator. Token
    statistics include only case IDs with usage rows, including usage-only IDs. Citation occurrences are counted, including
    repeated IDs; missing IDs are listed once per case.
    """
    cases = {}
    for path in sorted(Path(cases_dir).glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        cases[case["case_id"]] = case
    notes = []
    if not cases:
        notes.append("No case files found; missing investigations count as not caught.")
    usage = defaultdict(list)
    usage_path = Path(usage_path)
    if usage_path.is_file():
        for line in usage_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                usage[row["task_id"]].append(row)
    else:
        notes.append("Usage log missing; cases without rows have no usage logged.")
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        planted = conn.execute("SELECT customer_id, typology, is_suspicious FROM planted_cases").fetchall()
        has_alerts = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alerts'").fetchone()
        alerts = conn.execute("SELECT case_id, customer_id, status FROM alerts").fetchall() if has_alerts else []
        by_customer = defaultdict(list)
        for case in cases.values():
            by_customer[case["customer_id"]].append(case)
        alerted_customers = {row["customer_id"] for row in alerts}
        groups = {}
        for name, suspicious in (("suspicious", 1), ("look_alikes", 0)):
            rows = [row for row in planted if row["is_suspicious"] == suspicious]
            groups[name] = {
                "total": len(rows),
                "alerted": sum(row["customer_id"] in alerted_customers for row in rows),
                "investigated": sum(bool(by_customer[row["customer_id"]]) for row in rows),
            }
        caught = correct = false_alarms = 0
        planted_results = []
        for row in planted:
            files = by_customer[row["customer_id"]]
            is_caught = row["customer_id"] in alerted_customers and any(c["risk_rating"] in ("High", "Medium") for c in files)
            right = any(row["typology"] in c["typologies"] for c in files)
            if row["is_suspicious"]:
                caught += is_caught
                correct += right
            else:
                false_alarms += any(c["risk_rating"] == "High" for c in files)
            for case in files:
                planted_results.append({"case_id": case["case_id"], "typology": row["typology"],
                                        "suspicious": bool(row["is_suspicious"]),
                                        "caught": bool(row["customer_id"] in alerted_customers and case["risk_rating"] in ("High", "Medium")),
                                        "right_typology": row["typology"] in case["typologies"]})
        cited = existing = 0
        missing = []
        for case_id, case in sorted(cases.items()):
            absent = set()
            for evidence in case["evidence"]:
                for source_id in evidence["source"]:
                    cited += 1
                    if source_exists(case_id, source_id, conn):
                        existing += 1
                    else:
                        absent.add(source_id)
            missing.extend({"case_id": case_id, "source_id": sid} for sid in sorted(absent))
    per_case = {}
    for case_id in sorted(cases.keys() | usage.keys()):
        rows = usage[case_id]
        total = sum(row["total_tokens"] for row in rows)
        top = sum(row["total_tokens"] for row in rows
                  if row["agent"] == "investigate" and not row.get("parent_run"))
        per_case[case_id] = {"total_tokens": total, "top_level_tokens": top,
                             "amplification": total / top if top else None,
                             "usage_recorded": bool(rows)}
    results_by_id = {row["case_id"]: row for row in planted_results}
    for case_id, case in cases.items():
        result = results_by_id.get(case_id)
        per_case[case_id].update({
            "investigated": True,
            "customer_kind": ("planted suspicious" if result["suspicious"] else "look-alike") if result else "not in answer key",
            "typology": result["typology"] if result else None,
            "risk_rating": case["risk_rating"],
            "suggested_action": case.get("suggested_action", "unavailable"),
            "caught": result["caught"] if result and result["suspicious"] else None,
            "right_typology": result["right_typology"] if result and result["suspicious"] else None,
        })
    totals = [row["total_tokens"] for row in per_case.values() if row["usage_recorded"]]
    open_alerts = [row for row in alerts if row["status"] == "open"]
    investigated_open = sum(any(c["customer_id"] == row["customer_id"] for c in cases.values()) for row in open_alerts)
    dates = [datetime.fromisoformat(c["saved_at"].replace("Z", "+00:00")) for c in cases.values() if c.get("saved_at")]
    # Compare timestamps with offsets consistently; naive saved_at is interpreted as UTC.
    from datetime import timezone
    dates = [d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d for d in dates]
    partial = groups["suspicious"]["investigated"] < TARGETS["planted"]
    if partial:
        notes.append("Catch rate and right typology are partial: fewer than all 15 planted suspicious cases have case files.")
    notes.extend(("Citation check verifies record existence only, not whether a record supports a claim.",
                  "Token costs are API-equivalent. Cases without usage rows are labelled no usage logged and excluded from token statistics.",
                  "Token mean and median include only IDs with usage rows, including usage-only cases; amplification is unavailable without positive top-level investigate tokens.",
                  "Targets are demo starting points."))
    return {"generated_on": max(dates).date().isoformat() if dates else "unavailable (no saved_at)",
            "coverage": {"case_files": len(cases), "open_alerts": len(open_alerts), "investigated_open": investigated_open, **groups},
            "catch_rate": {"caught": caught, "out_of": 15, "partial": partial},
            "false_alarms": false_alarms,
            "citations": {"existing": existing, "total": cited, "share": existing / cited if cited else 0, "missing": missing},
            "right_typology": {"correct": correct, "out_of": 15, "partial": partial},
            "tokens": {"count": len(totals), "mean": mean(totals) if totals else 0, "median": median(totals) if totals else 0},
            "per_case": per_case, "planted_results": sorted(planted_results, key=lambda r: r["case_id"]), "notes": notes}


def render(report, markdown=False):
    """Render the same results as a plain-text or Markdown scorecard."""
    r = report
    c = r["coverage"]
    caught, right, citations = r["catch_rate"], r["right_typology"], r["citations"]
    def met(value):
        return "yes" if value else "no"
    rows = [
        ("Catch rate", f'{caught["caught"]}/15', '>= 13/15', "partial" if caught["partial"] else met(caught["caught"] >= TARGETS["catch"])),
        ("False alarms", str(r["false_alarms"]), '<= 3', met(r["false_alarms"] <= TARGETS["false_alarms"])),
        ("Citation check", f'{citations["existing"]}/{citations["total"]} ({citations["share"]:.1%})', '100%', met(citations["total"] > 0 and citations["existing"] == citations["total"])),
        ("Right typology", f'{right["correct"]}/15', '>= 12/15', "partial" if right["partial"] else met(right["correct"] >= TARGETS["typology"])),
        ("Tokens per case", f'mean {r["tokens"]["mean"]:,.1f}; median {r["tokens"]["median"]:,.1f} ({r["tokens"]["count"]} cases with usage)', 'Record and reduce', 'recorded'),
        ("Handoff amplification", 'See per-case lines', 'Record per case', 'recorded'),
    ]
    lines = ["# Evaluation scorecard" if markdown else "Evaluation scorecard", f'Generated on: {r["generated_on"]}', "Data is entirely synthetic.", "",
             f'Coverage: investigated {c["investigated_open"]} of {c["open_alerts"]} open alerts; {c["case_files"]} case files.']
    for label, key in (("Suspicious planted cases", "suspicious"), ("Look-alikes", "look_alikes")):
        group = c[key]
        lines.append(f'{label}: {group["alerted"]} alerted; {group["investigated"]} investigated; {group["total"]} in answer key.' + (f' {caught["caught"]} caught.' if key == "suspicious" else ""))
    def table_row(values):
        text = " | ".join(values)
        return f"| {text} |" if markdown else text
    lines += ["", "## Measures" if markdown else "Measures", "",
              table_row(("Measure", "Result", "Target", "Met"))]
    if markdown:
        lines.append("| --- | --- | --- | --- |")
    lines.extend(table_row(row) for row in rows)
    lines += ["", "## Per case" if markdown else "Per case", ""]
    for case_id, data in r["per_case"].items():
        amp = f'{data["amplification"]:.3f}x' if data["amplification"] is not None else "unavailable"
        usage_text = (f'{data["total_tokens"]:,} tokens; top-level {data["top_level_tokens"]:,}; amplification {amp}'
                      if data["usage_recorded"] else "no usage logged")
        if not data.get("investigated"):
            lines.append(f'- {case_id}: usage only; no case file; {usage_text}')
            continue
        if data["customer_kind"] == "planted suspicious":
            outcome = f'caught {met(data["caught"])}; right typology {met(data["right_typology"])}'
        elif data["customer_kind"] == "look-alike":
            outcome = "false alarm" if data["risk_rating"] == "High" else "not a false alarm"
        else:
            outcome = "not scored"
        typology = f'; planted typology {data["typology"]}' if data["typology"] else ""
        lines.append(f'- {case_id}: {data["customer_kind"]}{typology}; risk_rating {data["risk_rating"]}; '
                     f'suggested_action {data["suggested_action"]}; {outcome}; {usage_text}')
    lines += [f'- Missing source: {row["case_id"]}: {row["source_id"]}' for row in citations["missing"]]
    if not r["per_case"]:
        lines.append("- No cases or usage rows.")
    lines += ["", "## Notes" if markdown else "Notes", ""] + [f'- {note}' for note in r["notes"]]
    lines.append("- Met is recorded for recording-only measures, which have no numeric pass target.")
    if not citations["total"]:
        lines.append("- No cited IDs to check; 0% is a placeholder, not an observed citation success rate.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in (("db", "bank/bank.db"), ("cases", "cases"), ("usage", "usage/usage.jsonl"), ("out", "eval/scorecard.md")):
        parser.add_argument(f"--{name}", type=Path, default=ROOT / default)
    args = parser.parse_args()
    report = score(args.db, args.cases, args.usage)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report, markdown=True), encoding="utf-8")
    print(render(report), end="")


if __name__ == "__main__":
    main()
