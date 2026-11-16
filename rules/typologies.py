"""Explainable demo rules; no model or external services."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path


CONFIG = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))


def band(score):
    """Return the configured risk band for an alert score."""
    for name in ("High", "Medium"):
        if score >= CONFIG["risk_bands"][name]:
            return name
    return "Low"


def _load(conn, window_start, window_end):
    start = date.fromisoformat(str(window_start))
    end = date.fromisoformat(str(window_end))
    if end < start:
        raise ValueError("window_end must not precede window_start")
    history_start = start - timedelta(days=CONFIG["history_days"])
    cursor = conn.execute(
        "SELECT a.customer_id, t.*, p.name AS party_name, p.country AS party_country "
        "FROM transactions t JOIN accounts a USING(account_id) "
        "LEFT JOIN counterparties p USING(counterparty_account) "
        "WHERE t.timestamp >= ? AND t.timestamp < ? "
        "ORDER BY t.timestamp, t.txn_id",
        (history_start.isoformat(), (end + timedelta(days=1)).isoformat()),
    )
    columns = [column[0] for column in cursor.description]
    current, history = {}, {}
    for values in cursor:
        row = dict(zip(columns, values))
        row["time"] = datetime.fromisoformat(row["timestamp"])
        target = current if row["time"].date() >= start else history
        target.setdefault(row["customer_id"], []).append(row)
    return current, history


def _spans(rows, days):
    """Calendar-day spans, inclusive of the first day and exclusive of day N+1."""
    for index, first in enumerate(rows):
        end = first["time"].date() + timedelta(days=days)
        stop = index
        while stop < len(rows) and rows[stop]["time"].date() < end:
            stop += 1
        yield rows[index:stop]


def _hit(customer_id, typology, score, rows, reason):
    return dict(customer_id=customer_id, typology=typology,
                score=round(min(1.0, max(0.0, score)), 2),
                txn_ids=sorted({row["txn_id"] for row in rows})[:CONFIG["max_txn_ids"]],
                reason=reason)


def structuring(conn, window_start, window_end):
    """Find concentrated near-threshold cash deposits, discounted by history."""
    current, history = _load(conn, window_start, window_end)
    cfg = CONFIG["structuring"]

    def deposits(rows):
        return [r for r in rows if r["direction"] == "in" and r["channel"] == "cash"
                and cfg["minimum_amount"] <= r["amount_gbp"] <= cfg["maximum_amount"]]

    hits = []
    for customer, rows in current.items():
        best = max(_spans(deposits(rows), cfg["span_days"]), key=len, default=[])
        if len(best) < cfg["minimum_count"]:
            continue
        previous = max((len(s) for s in _spans(deposits(history.get(customer, [])),
                                              cfg["span_days"])), default=0)
        score = cfg["base_score"] + (len(best) - cfg["minimum_count"]) * cfg["extra_deposit_score"]
        familiar = previous >= len(best) * cfg["history_comparable_ratio"]
        if familiar:
            score = min(score, cfg["history_score_cap"])
        amounts = [r["amount_gbp"] for r in best]
        days = (best[-1]["time"].date() - best[0]["time"].date()).days + 1
        reason = (f"{len(best)} cash deposits of GBP {min(amounts):,.2f} to "
                  f"{max(amounts):,.2f} in {days} days; historical {cfg['span_days']}-day maximum {previous}.")
        hits.append(_hit(customer, "structuring", score, best, reason))
    return hits


def rapid_pass_through(conn, window_start, window_end):
    """Find a qualifying credit followed by transfer outflows within 48 hours."""
    current, _ = _load(conn, window_start, window_end)
    cfg = CONFIG["rapid_pass_through"]
    hits = []
    for customer, rows in current.items():
        candidates = []
        for credit in rows:
            if credit["direction"] != "in" or credit["amount_gbp"] < cfg["minimum_credit"]:
                continue
            deadline = credit["time"] + timedelta(hours=cfg["hours"])
            out = []
            total = 0
            for row in rows:
                if (credit["time"] < row["time"] <= deadline and row["direction"] == "out"
                        and row["channel"] in cfg["outbound_channels"]):
                    out.append(row)
                    total += row["amount_gbp"]
                    ratio = total / credit["amount_gbp"]
                    if ratio >= cfg["minimum_ratio"]:
                        hours = (row["time"] - credit["time"]).total_seconds() / 3600
                        score = (cfg["base_score"] + (min(ratio, 1) - cfg["minimum_ratio"]) * cfg["ratio_weight"]
                                 + (1 - hours / cfg["hours"]) * cfg["speed_weight"])
                        candidates.append(_hit(customer, "rapid_pass_through", score, [credit] + out,
                            f"GBP {total:,.2f} ({ratio:.0%}) of a GBP {credit['amount_gbp']:,.2f} credit paid out in {hours:g} hours."))
        if candidates:
            hits.append(max(candidates, key=lambda h: (h["score"], h["txn_ids"])))
    return hits


def fan_in_fan_out(conn, window_start, window_end):
    """Compare each direction's seven-day distinct-party peak with history."""
    current, history = _load(conn, window_start, window_end)
    cfg = CONFIG["fan_in_fan_out"]

    def eligible(rows, direction):
        return [r for r in rows if r["direction"] == direction
                and r["counterparty_account"] not in cfg["excluded_parties"]]

    def count(rows):
        return len({r["counterparty_account"] for r in rows})

    hits = []
    for customer, rows in current.items():
        candidates = []
        for direction in ("in", "out"):
            best = max(_spans(eligible(rows, direction), cfg["span_days"]), key=count, default=[])
            parties = count(best)
            previous = max((count(s) for s in _spans(eligible(history.get(customer, []), direction),
                                                    cfg["span_days"])), default=0)
            if parties < cfg["minimum_parties"] or previous >= parties * cfg["history_comparable_ratio"]:
                continue
            score = cfg["base_score"] + (parties - cfg["minimum_parties"]) * cfg["extra_party_score"]
            candidates.append(_hit(customer, "fan_in_fan_out", score, best,
                f"{parties} distinct counterparties {direction} in {cfg['span_days']} days; historical maximum {previous}."))
        if candidates:
            hits.append(max(candidates, key=lambda h: (h["score"], h["txn_ids"])))
    return hits


def high_risk_link(conn, window_start, window_end):
    """Exact case-insensitive screening names or configured country links."""
    current, _ = _load(conn, window_start, window_end)
    cfg = CONFIG["high_risk_link"]
    names = {}
    for name, kind in conn.execute("SELECT name, list_type FROM screening_list"):
        score = cfg["sanctions_score"] if kind.casefold() == "sanctions" else cfg["screening_score"]
        names[name.casefold()] = max(names.get(name.casefold(), 0), score)
    hits = []
    for customer, rows in current.items():
        matched, scores, screened, countries = [], [], 0, 0
        for row in rows:
            name_score = names.get((row["party_name"] or "").casefold(), 0)
            country = row["country"] in cfg["countries"] or row["party_country"] in cfg["countries"]
            if name_score or country:
                matched.append(row)
                scores.append(max(name_score, cfg["country_score"] if country else 0))
                screened += bool(name_score)
                countries += bool(country)
        if matched:
            hits.append(_hit(customer, "high_risk_link", max(scores), matched,
                f"{len(matched)} linked transactions: {screened} exact screening-name matches and {countries} high-risk country links."))
    return hits


def evaluate(conn, window_start, window_end):
    """Return deterministic customer/typology hits within the inclusive window."""
    hits = []
    for rule in (structuring, rapid_pass_through, fan_in_fan_out, high_risk_link):
        hits.extend(rule(conn, window_start, window_end))
    return sorted(hits, key=lambda h: (h["customer_id"], h["typology"]))
