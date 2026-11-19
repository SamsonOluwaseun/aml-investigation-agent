"""Create a reproducible, entirely fictional bank using only the standard library."""

from contextlib import closing
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import argparse
import csv
import json
import random
import re
import sqlite3


SEED = 20261115
DB_PATH = Path(__file__).resolve().with_name("bank.db")
INCOMING_PATH = DB_PATH.parent.parent / "incoming"
BATCH_COLUMNS = (
    "txn_id", "account_id", "customer_id", "timestamp", "direction",
    "amount_gbp", "channel", "counterparty_account", "counterparty_country", "reference",
)
TYPOLOGIES = ("structuring", "rapid_pass_through", "fan_in_fan_out", "high_risk_link")

SCHEMA = """
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, occupation TEXT NOT NULL,
    declared_income REAL NOT NULL CHECK(declared_income > 0),
    risk_rating TEXT NOT NULL, country TEXT NOT NULL, onboarded_on TEXT NOT NULL
);
CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
    type TEXT NOT NULL, opened_on TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE counterparties (
    counterparty_account TEXT PRIMARY KEY, name TEXT NOT NULL,
    country TEXT NOT NULL, bank TEXT NOT NULL
);
CREATE TABLE transactions (
    txn_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts,
    counterparty_account TEXT NOT NULL REFERENCES counterparties,
    amount_gbp REAL NOT NULL CHECK(amount_gbp > 0),
    direction TEXT NOT NULL CHECK(direction IN ('in', 'out')),
    channel TEXT NOT NULL, country TEXT NOT NULL, timestamp TEXT NOT NULL
);
CREATE TABLE screening_list (
    name TEXT NOT NULL, list_type TEXT NOT NULL, country TEXT NOT NULL,
    PRIMARY KEY(name, list_type)
);
CREATE TABLE adverse_media (
    name TEXT NOT NULL, headline TEXT NOT NULL, date TEXT NOT NULL,
    PRIMARY KEY(name, headline, date)
);
CREATE TABLE planted_cases (
    case_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
    typology TEXT NOT NULL, notes TEXT NOT NULL,
    is_suspicious INTEGER NOT NULL CHECK(is_suspicious IN (0, 1))
);
CREATE INDEX transactions_account_time ON transactions(account_id, timestamp);
"""


def add_transaction(conn, account_id, counterparty, amount, direction, channel, when):
    """Store positive GBP amounts with direction separate from the amount."""
    country = "XZ" if counterparty == "FAKE-EXT-099" else "GB"
    txn_id = f"T-{conn.execute('SELECT coalesce((SELECT CAST(substr(txn_id, 3) AS INTEGER) FROM transactions ORDER BY txn_id DESC LIMIT 1), 0)').fetchone()[0] + 1:07d}"
    conn.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (txn_id, account_id, counterparty, round(amount, 2), direction, channel,
         country, when.isoformat(timespec="seconds")),
    )


def plant_case(case_id, conn, customer_number, typology, suspicious, rng, direction):
    """Inject one scenario and write its evaluation label (never read the key)."""
    customer_id = f"CU-{customer_number:04d}"
    account = f"FAKE-AC-{customer_number:04d}-1"
    start = datetime(2026, 9, 29, 10) + timedelta(days=rng.randrange(19), hours=rng.randrange(6))

    def payment(day, amount, direction="in", channel="transfer", party="FAKE-EXT-050"):
        add_transaction(conn, account, "FAKE-CASH-BRANCH" if channel == "cash" else party, amount, direction, channel,
                        start + timedelta(days=day))

    if typology == "structuring":
        for day in range(0, 12, 2):
            payment(day, rng.randint(800000, 999900) / 100, channel="cash")
        notes = "Six near-threshold cash deposits in eleven days; no declared cash trade."
        if not suspicious:
            conn.execute("UPDATE customers SET occupation = ? WHERE customer_id = ?",
                         ("Synthetic cash market business", customer_id))
            for month in range(5, 10):
                for day in range(1, 28, 3):
                    add_transaction(conn, account, "FAKE-CASH-BRANCH", rng.randint(800000, 999900) / 100, "in", "cash",
                                    datetime(2026, month, day, 10))
            notes = "Declared cash market business; comparable takings throughout the previous five months."
    elif typology == "rapid_pass_through":
        receipt = rng.randint(4000000, 6500000) / 100
        ratio = rng.randint(85, 97)
        payment(0, receipt)
        payment(1 if suspicious else 4, receipt * ratio / 100, "out", party="FAKE-EXT-051")
        notes = (f"{ratio}% of a large receipt leaves for another party within 24 hours."
                 if suspicious else "Synthetic equipment sale followed by a purchase four days later; outside 48 hours.")
        if not suspicious:
            conn.execute("UPDATE customers SET occupation = ? WHERE customer_id = ?",
                         ("Synthetic equipment dealer", customer_id))
    elif typology == "fan_in_fan_out":
        for number in range(12):
            payment(number // 3, rng.randint(40000, 90000) / 100,
                    direction,
                    party=f"FAKE-EXT-{60 + number:03d}")
        notes = f"Twelve distinct parties, direction {direction}, in four days, unlike the prior five months."
        if not suspicious:
            conn.execute("UPDATE customers SET occupation = ? WHERE customer_id = ?",
                         ("Synthetic community subscription club", customer_id))
            for month in range(5, 10):
                for number in range(12):
                    add_transaction(conn, account, f"FAKE-EXT-{60 + number:03d}",
                                    rng.randint(40000, 90000) / 100, direction,
                                    "transfer", datetime(2026, month, 15 + number // 3, 10))
            notes = "Declared subscription club with the same twelve parties and comparable amounts every month."
    else:
        payment(0, rng.randint(1500000, 2500000) / 100, "out", party="FAKE-EXT-098" if suspicious else "FAKE-EXT-097")
        if suspicious:
            payment(2, rng.randint(1000000, 1800000) / 100, "out", party="FAKE-EXT-099")
        notes = ("Exact synthetic sanctions-list counterparty and a payment to fictional country XZ."
                 if suspicious else "Similar name to a listed party, but distinct exact name/account in GB; ordinary supplier.")
    if not suspicious and typology in ("structuring", "rapid_pass_through", "fan_in_fan_out"):
        # Business takings replace the personal salary generated before scenarios.
        conn.execute(
            "DELETE FROM transactions WHERE account_id = ? "
            "AND counterparty_account = 'FAKE-EXT-000' AND direction = 'in'",
            (account,),
        )
        total_inbound = conn.execute(
            "SELECT coalesce(sum(amount_gbp), 0) FROM transactions "
            "WHERE account_id = ? AND direction = 'in'", (account,),
        ).fetchone()[0]
        # Six months of receipts, annualised and rounded up to GBP 1,000.
        annual_takings = ((round(total_inbound * 100) * 2 + 99999) // 100000) * 1000
        conn.execute(
            "UPDATE customers SET declared_income = max(declared_income, ?) "
            "WHERE customer_id = ?", (annual_takings, customer_id),
        )
    conn.execute("INSERT INTO planted_cases VALUES (?, ?, ?, ?, ?)",
                 (case_id, customer_id, typology, notes, int(suspicious)))


def generate(path=DB_PATH):
    """Replace the generated bank and return counts without reading the answer key."""
    rng = random.Random(SEED)
    path = Path(path)
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        for number in range(100):
            name = f"FAKE Counterparty {number:03d}"
            if number == 97:
                name = "FAKE Nebula Trading Supplies"
            elif number == 98:
                name = "FAKE Nebula Trading"
            conn.execute("INSERT INTO counterparties VALUES (?, ?, ?, ?)",
                         (f"FAKE-EXT-{number:03d}", name,
                          "XZ" if number == 99 else "GB", "FAKE Demonstration Bank"))
        conn.execute("INSERT INTO counterparties VALUES (?, ?, ?, ?)",
                     ("FAKE-CASH-BRANCH", "FAKE Cash Deposit", "GB", "FAKE Demonstration Bank"))
        conn.executemany("INSERT INTO screening_list VALUES (?, ?, ?)", [
            ("FAKE Nebula Trading", "sanctions", "GB"),
            ("FAKE Counterparty 099", "sanctions", "XZ"),
            ("FAKE Example PEP", "PEP", "GB"),
        ])
        conn.execute("INSERT INTO adverse_media VALUES (?, ?, ?)",
                     ("FAKE Nebula Trading", "FICTIONAL: synthetic trading entity investigated for laundering", "2026-10-01"))
        for number in range(1, 501):
            customer = f"CU-{number:04d}"
            income = rng.randrange(24000, 96001, 1200)
            occupation = rng.choice(("Synthetic teacher", "Synthetic engineer", "Synthetic nurse",
                                     "Synthetic administrator", "Synthetic technician"))
            risk = rng.choices(("Low", "Medium", "High"), weights=(80, 17, 3))[0]
            onboarded = (datetime(2022, 1, 1) + timedelta(days=rng.randrange(1500))).date().isoformat()
            conn.execute("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (customer, f"FAKE Customer {number:04d}", occupation,
                          income, risk, "GB", onboarded))
            for suffix in range(1, 3 if number % 5 == 0 else 2):
                conn.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                             (f"FAKE-AC-{number:04d}-{suffix}", customer,
                              "current" if suffix == 1 else "savings", onboarded, "active"))
            account = f"FAKE-AC-{number:04d}-1"
            for month in range(5, 11):
                add_transaction(conn, account, "FAKE-EXT-000", income / 12,
                                "in", "transfer", datetime(2026, month, 1, 9))
                for bill in range(3):
                    add_transaction(conn, account, f"FAKE-EXT-{bill + 1:03d}",
                                    income / 12 * (0.10 + bill * 0.04), "out",
                                    "direct_debit", datetime(2026, month, 5 + bill, 9))
                for day in range(2, 29, 2):
                    add_transaction(conn, account, f"FAKE-EXT-{rng.randrange(4, 10):03d}",
                                    rng.randint(500, max(501, income // 60)) / 100,
                                    "out", "card", datetime(2026, month, day, 15))
        scenarios = [(TYPOLOGIES[i % 4], i < 15) for i in range(27)]
        rng.shuffle(scenarios)
        customers = rng.sample(range(1, 501), 27)
        suspicious_fans = 0
        for number, (customer, (typology, suspicious)) in enumerate(zip(customers, scenarios), 1):
            # Alternate independently of customer identifiers to guarantee both directions.
            direction = "out" if number % 2 else "in"
            if typology == "fan_in_fan_out" and suspicious:
                direction = "out" if suspicious_fans % 2 else "in"
                suspicious_fans += 1
            plant_case(f"PC-{number:03d}", conn, customer, typology, suspicious, rng, direction)
        counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("customers", "accounts", "transactions")}
    counts.update(planted_cases=15, innocent_look_alikes=12)
    return counts


def daily_demo_customer():
    """Replay generate's RNG up to scenario selection, without reading the key.

    Keep these draws aligned with generate; the selection test guards this.
    """
    rng = random.Random(SEED)
    for _ in range(500):
        income = rng.randrange(24000, 96001, 1200)
        rng.choice(range(5))
        rng.choices(("Low", "Medium", "High"), weights=(80, 17, 3))
        rng.randrange(1500)
        for _ in range(6 * 14):
            rng.randrange(4, 10)
            rng.randint(500, max(501, income // 60))
    scenarios = [(TYPOLOGIES[i % 4], i < 15) for i in range(27)]
    rng.shuffle(scenarios)
    planted = set(rng.sample(range(1, 501), 27))
    return f"CU-{next(n for n in range(1, 501) if n not in planted):04d}"


def parse_day(value):
    """Accept only an actual calendar date written YYYY-MM-DD."""
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("day must be a valid date in YYYY-MM-DD format") from None


def generate_day(day, path=DB_PATH, out=INCOMING_PATH):
    """Export one deterministic batch using only read-only bank reference data."""
    day = parse_day(day) if isinstance(day, str) else day
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Bank database missing; run python bank/generate.py first.")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        customers = conn.execute(
            "SELECT a.account_id, c.customer_id, c.declared_income, c.occupation "
            "FROM accounts a JOIN customers c USING(customer_id) "
            "WHERE a.type='current' AND a.status='active' ORDER BY a.account_id"
        ).fetchall()
        parties = dict(conn.execute("SELECT counterparty_account, country FROM counterparties"))
    rng = random.Random(f"{SEED}:{day.isoformat()}")
    rows = []

    def payment(account, customer, cents, direction, channel, party, hour, reference):
        rows.append(dict(zip(BATCH_COLUMNS, (
            f"T-{day:%Y%m%d}-{len(rows) + 1:04d}", account, customer,
            f"{day.isoformat()}T{hour:02d}:{rng.randrange(60):02d}:00", direction,
            f"{Decimal(cents) / 100:.2f}", channel, party, parties[party], reference,
        ))))

    demo = daily_demo_customer()
    for account, customer, income, occupation in customers:
        if rng.random() < 0.8:
            payment(account, customer, rng.randint(500, max(501, int(income) // 60)),
                    "out", "card", f"FAKE-EXT-{rng.randrange(4, 10):03d}", 15, "card purchase")
        business = occupation in ("Synthetic cash market business", "Synthetic equipment dealer",
                                  "Synthetic community subscription club")
        if day.day == 1 and not business:
            payment(account, customer, round(income / 12 * 100), "in", "transfer",
                    "FAKE-EXT-000", 9, "salary")
        if 5 <= day.day <= 7:
            bill = day.day - 5
            payment(account, customer, round(income / 12 * (0.10 + bill * 0.04) * 100),
                    "out", "direct_debit", f"FAKE-EXT-{bill + 1:03d}", 9, "monthly bill")
        if customer == demo:
            for hour in (10, 14):
                payment(account, customer, rng.randint(800000, 999900), "in", "cash",
                        "FAKE-CASH-BRANCH", hour, "cash deposit")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / f"transactions_{day.isoformat()}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BATCH_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    control = dict(batch_date=day.isoformat(), file=csv_path.name, row_count=len(rows),
                   total_amount_gbp=float(sum((Decimal(r["amount_gbp"]) for r in rows), Decimal(0))))
    csv_path.with_suffix(".control.json").write_text(json.dumps(control, indent=2) + "\n", encoding="utf-8")
    return control


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=parse_day, help="export a daily batch (YYYY-MM-DD)")
    parser.add_argument("--out", type=Path, default=INCOMING_PATH, help="daily batch output directory")
    args = parser.parse_args()
    if args.day is not None:
        try:
            control = generate_day(args.day, out=args.out)
        except FileNotFoundError as error:
            parser.exit(1, f"{error}\n")
        print(f"Daily batch: {control['file']} | rows: {control['row_count']}")
    else:
        summary = generate()
        print("Synthetic bank:", " | ".join(f"{key}: {value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
