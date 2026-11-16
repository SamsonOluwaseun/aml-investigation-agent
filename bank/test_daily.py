"""Offline daily batch contract checks, with isolated database and output paths."""
import argparse
from collections import Counter
from contextlib import closing
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from unittest.mock import patch

import pytest

from bank import generate as bank


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    path = tmp_path_factory.mktemp("daily-bank") / "bank.db"
    selected = []
    original = bank.plant_case

    def record(case_id, conn, customer_number, *args):
        selected.append(f"CU-{customer_number:04d}")
        return original(case_id, conn, customer_number, *args)

    with patch.object(bank, "plant_case", side_effect=record):
        bank.generate(path)
    assert len(selected) == 27
    assert bank.daily_demo_customer() not in selected
    return path


def dump_hash(path):
    with closing(sqlite3.connect(path)) as conn:
        return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()


def read_batch(out, day):
    path = out / f"transactions_{day}.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames
        rows = list(reader)
    return path, header, rows


def test_daily_contract(database, tmp_path):
    before = dump_hash(database)
    with closing(sqlite3.connect(database)) as conn:
        accounts = dict(conn.execute("SELECT account_id, customer_id FROM accounts"))
        parties = dict(conn.execute("SELECT counterparty_account, country FROM counterparties"))
    sample = Path(__file__).resolve().parents[1] / "data/sample/transactions_2026-11-16.csv"
    with sample.open(newline="", encoding="utf-8") as stream:
        expected_header = next(csv.reader(stream))
    ids = set()
    deposits = Counter()
    for index, day in enumerate(("2026-11-16", "2026-11-17", "2026-11-18"), 1):
        bank.generate_day(day, database, tmp_path / "incoming")
        path, header, rows = read_batch(tmp_path / "incoming", day)
        control_path = path.with_suffix(".control.json")
        control = json.loads(control_path.read_text())
        assert header == expected_header
        assert control == dict(batch_date=day, file=path.name, row_count=len(rows),
                               total_amount_gbp=float(sum(Decimal(r["amount_gbp"]) for r in rows)))
        first = path.read_bytes(), control_path.read_bytes()
        bank.generate_day(day, database, path.parent)
        assert first == (path.read_bytes(), control_path.read_bytes())
        assert len({r["customer_id"] for r in rows}) > 300
        for row in rows:
            assert re.fullmatch(r"T-" + day.replace("-", "") + r"-\d{4}", row["txn_id"])
            assert row["txn_id"] not in ids
            ids.add(row["txn_id"])
            assert accounts[row["account_id"]] == row["customer_id"]
            assert parties[row["counterparty_account"]] == row["counterparty_country"]
            assert row["channel"] in {"card", "cash", "transfer", "direct_debit"}
            assert row["direction"] in {"in", "out"}
            assert re.fullmatch(r"\d+\.\d{2}", row["amount_gbp"])
            assert Decimal(row["amount_gbp"]) > 0
            assert re.fullmatch(day + r"T\d{2}:\d{2}:00", row["timestamp"])
            if row["channel"] == "cash":
                assert row["counterparty_account"] == "FAKE-CASH-BRANCH"
                if row["direction"] == "in" and 8000 <= Decimal(row["amount_gbp"]) <= 9999:
                    deposits[row["customer_id"]] += 1
            else:
                assert row["counterparty_account"].startswith("FAKE-EXT-")
        count = deposits[bank.daily_demo_customer()]
        assert count == index * 2
        assert (count < 5) if index < 3 else (count >= 5)
    assert dump_hash(database) == before


def test_monthly_activity(database, tmp_path):
    for day, channel, direction in (("2026-12-01", "transfer", "in"),
                                    ("2026-12-05", "direct_debit", "out"),
                                    ("2026-12-06", "direct_debit", "out"),
                                    ("2026-12-07", "direct_debit", "out")):
        bank.generate_day(day, database, tmp_path)
        _, _, rows = read_batch(tmp_path, day)
        monthly = [r for r in rows if r["channel"] == channel]
        assert len(monthly) >= 480
        assert all(r["direction"] == direction for r in monthly)


@pytest.mark.parametrize("value", ["2026-2-01", "2026-02-30", "20261116", "bad", "2026-11-16T00:00:00"])
def test_bad_date(value):
    with pytest.raises(argparse.ArgumentTypeError, match="YYYY-MM-DD"):
        bank.parse_day(value)


def test_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError, match="run python bank/generate.py first"):
        bank.generate_day("2026-11-16", tmp_path / "missing.db", tmp_path / "incoming")
    assert not (tmp_path / "missing.db").exists()
    assert not (tmp_path / "incoming").exists()
