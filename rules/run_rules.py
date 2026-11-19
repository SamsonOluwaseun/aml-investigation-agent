"""Run the deterministic demo rules and create or update the alert queue."""

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

if __package__:
    from .typologies import CONFIG, band, evaluate
else:
    from typologies import CONFIG, band, evaluate


DB_PATH = Path(__file__).resolve().parent.parent / "bank" / "bank.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
  case_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL UNIQUE REFERENCES customers,
  score REAL NOT NULL,
  typologies TEXT NOT NULL,
  hits TEXT NOT NULL,
  status TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
"""


def _write_alert(case_id, conn, customer_id, score, typologies, hits, start, end, new):
    """Persist one case, retaining its original creation date and status."""
    if new:
        conn.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)",
                     (case_id, customer_id, score, typologies, hits, start, end, end, end))
    else:
        conn.execute("UPDATE alerts SET score=?, typologies=?, hits=?, window_start=?, "
                     "window_end=?, updated_at=? WHERE case_id=?",
                     (score, typologies, hits, start, end, end, case_id))


def run(db_path, as_of=None):
    """Return new/updated/unchanged case ID lists, window, queue size and changes.

    Alerts without current hits remain available for human review; their old
    evidence and dates are retained. Unchanged refers to current rule matches.
    """
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Bank database missing; run python bank/generate.py first.")
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        if as_of is None:
            latest = conn.execute("SELECT max(timestamp) FROM transactions").fetchone()[0]
            if latest is None:
                raise ValueError("No transactions; supply --as-of YYYY-MM-DD")
            end = date.fromisoformat(latest[:10])
        else:
            end = date.fromisoformat(str(as_of))
        start = end - timedelta(days=CONFIG["window_days"] - 1)
        start, end = start.isoformat(), end.isoformat()
        grouped = {}
        for hit in evaluate(conn, start, end):
            customer = hit["customer_id"]
            grouped.setdefault(customer, []).append({k: v for k, v in hit.items() if k != "customer_id"})
        conn.execute(SCHEMA)
        existing = {row[1]: row for row in conn.execute(
            "SELECT case_id, customer_id, score, typologies, hits FROM alerts")}
        used = {row[0] for row in existing.values()}
        next_number = 1
        alerts = []
        for customer, hits in grouped.items():
            typologies = sorted({h["typology"] for h in hits})
            score = round(min(1, max(h["score"] for h in hits)
                              + CONFIG["additional_typology_score"] * (len(typologies) - 1)), 2)
            alerts.append((customer, score, json.dumps(typologies), json.dumps(hits, sort_keys=True)))
        alerts.sort(key=lambda a: (-a[1], a[0]))
        summary = dict(new=[], updated=[], unchanged=[],
                       window=dict(window_start=start, window_end=end), changes=[])
        for customer, score, typologies, hits in alerts:
            old = existing.get(customer)
            if old:
                case_id = old[0]
                if (score, typologies, hits) == old[2:]:
                    summary["unchanged"].append(case_id)
                    continue
                kind = "updated"
            else:
                while f"C-{next_number:03d}" in used:
                    next_number += 1
                case_id = f"C-{next_number:03d}"
                used.add(case_id)
                kind = "new"
            _write_alert(case_id, conn, customer, score, typologies, hits, start, end, kind == "new")
            summary[kind].append(case_id)
            summary["changes"].append(dict(case_id=case_id, customer_id=customer,
                                           typologies=json.loads(typologies), score=score))
        summary["open_queue"] = conn.execute("SELECT count(*) FROM alerts WHERE status='open'").fetchone()[0]
        conn.commit()
        return summary
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, help="inclusive end date YYYY-MM-DD")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    try:
        summary = run(args.db, args.as_of)
    except (ValueError, FileNotFoundError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    window = summary["window"]
    print(f"Rules window {window['window_start']} to {window['window_end']}")
    print(f"New alerts: {len(summary['new'])} | Updated: {len(summary['updated'])} | Open queue: {summary['open_queue']}")
    for alert in summary["changes"]:
        print(f"  {alert['case_id']}  {alert['customer_id']}  {', '.join(alert['typologies'])}  score {alert['score']:.2f}")


if __name__ == "__main__":
    main()
