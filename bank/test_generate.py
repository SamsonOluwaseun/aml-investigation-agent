"""Offline acceptance checks; answer-key reads are confined to explicit dump comparison."""

from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import sqlite3
import tempfile
from pathlib import Path

from bank.generate import TYPOLOGIES, generate


def test_reproducible_bank(tmp_path):
    path = tmp_path / "bank.db"
    first = generate(path)
    with closing(sqlite3.connect(path)) as conn:
        dump = "\n".join(conn.iterdump())
        digest = hashlib.sha256(dump.encode()).hexdigest()
        # The requested deterministic dump is the only inspection of key contents.
        labels = [line for line in dump.splitlines()
                  if line.startswith('INSERT INTO "planted_cases"')]
        assert len(labels) == 27
        import re
        identifiers = [re.search(r"'PC-\d{3}','(CU-\d{4})'", line).group(1) for line in labels]
        assert len(set(identifiers)) == 27
        assert max(int(i[3:]) for i in identifiers) > 400
        assert min(int(i[3:]) for i in identifiers) < 100
        look_alike_ids = [re.search(r"'PC-\d{3}','(CU-\d{4})'", line).group(1)
                          for line in labels if line.endswith(",0);")]
        flags = [line.endswith(",1);") for line in labels]
        assert any(flags[i] != flags[i+1] for i in range(26))
        assert flags != sorted(flags, reverse=True)
        assert sum(line.endswith(",1);") for line in labels) == 15
        assert sum(line.endswith(",0);") for line in labels) == 12
        for typology, count in zip(TYPOLOGIES, (4, 4, 4, 3)):
            assert sum(f"'{typology}'" in line and line.endswith(",1);")
                       for line in labels) == count
            assert sum(f"'{typology}'" in line and line.endswith(",0);")
                       for line in labels) == 3
    assert generate(path) == first
    with closing(sqlite3.connect(path)) as conn:
        assert hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest() == digest
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )} == {"customers", "accounts", "transactions", "counterparties",
               "screening_list", "adverse_media", "planted_cases"}
        assert 450 <= first["customers"] <= 550
        assert 500 <= first["accounts"] <= 700
        assert 50000 <= first["transactions"] <= 60000
        assert first["planted_cases"] == 15
        assert first["innocent_look_alikes"] == 12
        assert conn.execute(
            "SELECT count(DISTINCT customer_id) FROM accounts JOIN transactions "
            "USING(account_id) GROUP BY substr(timestamp,1,7)"
        ).fetchall() == [(500,)] * 6
        for table in ("customers", "counterparties", "screening_list", "adverse_media"):
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE name NOT LIKE 'FAKE %'"
            ).fetchone() == (0,)
        customers = conn.execute("SELECT occupation,risk_rating,onboarded_on FROM customers").fetchall()
        assert len({r[0] for r in customers}) >= 5
        risks = [r[1] for r in customers]
        assert risks.count("Low") > 350
        assert 20 < risks.count("Medium") < 150
        assert 0 < risks.count("High") < 40
        assert len({r[2] for r in customers}) > 100
        assert all(r[2] < "2026-05-01" for r in customers)
        assert conn.execute(
            "SELECT count(*) FROM transactions JOIN accounts USING(account_id) "
            "JOIN customers USING(customer_id) WHERE counterparty_account='FAKE-EXT-000' "
            "AND abs(amount_gbp-declared_income/12)>0.01"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT DISTINCT counterparty_account FROM transactions WHERE channel='cash'"
        ).fetchall() == [("FAKE-CASH-BRANCH",)]
        assert conn.execute(
            "SELECT name,country FROM counterparties WHERE counterparty_account='FAKE-CASH-BRANCH'"
        ).fetchone() == ("FAKE Cash Deposit", "GB")
        for customer_id in look_alike_ids:
            income, occupation = conn.execute(
                "SELECT declared_income, occupation FROM customers WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
            inbound = conn.execute(
                "SELECT coalesce(sum(amount_gbp), 0) FROM transactions "
                "JOIN accounts USING(account_id) WHERE customer_id = ? AND direction = 'in'",
                (customer_id,),
            ).fetchone()[0]
            assert income >= inbound / 6 * 10
            if occupation in ("Synthetic cash market business", "Synthetic equipment dealer",
                              "Synthetic community subscription club"):
                assert conn.execute(
                    "SELECT count(*) FROM transactions JOIN accounts USING(account_id) "
                    "WHERE customer_id = ? AND counterparty_account = 'FAKE-EXT-000' "
                    "AND direction = 'in'", (customer_id,),
                ).fetchone() == (0,)
        end = datetime.fromisoformat(conn.execute("SELECT max(timestamp) FROM transactions").fetchone()[0])
        window = end - timedelta(days=30)
        # Inspect generated evidence without querying the answer key.
        patterns = conn.execute(
            "SELECT account_id,amount_gbp,direction,channel,counterparty_account,timestamp "
            "FROM transactions WHERE channel='cash' OR counterparty_account BETWEEN "
            "'FAKE-EXT-050' AND 'FAKE-EXT-099' ORDER BY timestamp"
        ).fetchall()
        recent = [r for r in patterns if datetime.fromisoformat(r[5]) >= window]
        assert all(datetime.fromisoformat(r[5]) <= end for r in recent)
        starts = {}
        for row in recent:
            starts.setdefault(row[0], row[5])
        assert len(set(starts.values())) > 10
        cash = [r for r in recent if r[3] == "cash"]
        assert all(8000 <= r[1] <= 9999 for r in cash)
        assert len({r[1] for r in cash}) > 20
        for account in {r[0] for r in cash}:
            rows = [r for r in cash if r[0] == account]
            assert len(rows) == 6
            assert datetime.fromisoformat(rows[-1][5])-datetime.fromisoformat(rows[0][5]) <= timedelta(days=14)
        receipts = [r for r in recent if r[4] == "FAKE-EXT-050"]
        assert len(receipts) == 7
        rapid = 0
        for receipt in receipts:
            outgoing = [r for r in recent if r[0] == receipt[0] and r[4] == "FAKE-EXT-051"]
            assert len(outgoing) == 1
            assert outgoing[0][1] >= receipt[1] * .80
            delay = datetime.fromisoformat(outgoing[0][5])-datetime.fromisoformat(receipt[5])
            rapid += delay <= timedelta(hours=48)
        assert rapid == 4
        suspicious_fan_directions = set()
        for account in {r[0] for r in recent if 'FAKE-EXT-060' <= r[4] <= 'FAKE-EXT-071'}:
            rows = [r for r in recent if r[0] == account and 'FAKE-EXT-060' <= r[4] <= 'FAKE-EXT-071']
            assert len({r[4] for r in rows}) >= 10
            assert datetime.fromisoformat(rows[-1][5])-datetime.fromisoformat(rows[0][5]) <= timedelta(days=7)
            history = [r for r in patterns if r[0] == account and datetime.fromisoformat(r[5]) < window and 'FAKE-EXT-060' <= r[4] <= 'FAKE-EXT-071']
            if not history:
                assert len({r[2] for r in rows}) == 1
                suspicious_fan_directions.update(r[2] for r in rows)
        assert suspicious_fan_directions == {"in", "out"}
        assert len([r for r in recent if r[4] == "FAKE-EXT-099" and r[2] == "out"]) >= 1
    print("Acceptance checks passed; deterministic dump SHA-256:", digest)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        test_reproducible_bank(Path(directory))
