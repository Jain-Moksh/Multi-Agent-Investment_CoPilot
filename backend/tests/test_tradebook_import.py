"""
Tradebook CSV import. Parsing tests need no database; the endpoint tests use
PostgreSQL (TEST_DATABASE_URL) because the insert uses ON CONFLICT.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Transaction
from app.models.enums import TransactionAction, TransactionSource
from app.services.tradebook_import import StatementError, parse_tradebook
from tests.conftest import signup_headers

HEADER = "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time"
ZERODHA_CSV = f"""{HEADER}
RELIANCE,INE002A01018,2024-01-15,NSE,EQ,EQ,buy,false,10.000000,2501.350000,55012345,1100000012345678,2024-01-15T09:30:12
TCS,INE467B01029,2024-02-01,BSE,EQ,A,buy,false,5.000000,3800.000000,55012346,1100000012345679,2024-02-01T10:01:00
RELIANCE,INE002A01018,2024-03-20,NSE,EQ,EQ,sell,false,4.000000,2900.100000,55012347,1100000012345680,2024-03-20T14:45:59
NIFTY24MARFUT,,2024-03-21,NFO,FO,,buy,false,50.000000,22000.000000,55012348,1100000012345681,2024-03-21T09:20:00
"""


def csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


# ---------------- parsing (no DB) ----------------

def test_parses_zerodha_tradebook():
    parsed = parse_tradebook(csv_bytes(ZERODHA_CSV))
    assert parsed.rows_in_file == 4
    assert parsed.non_equity_skipped == 1  # the NIFTY future
    first, second, third = parsed.rows
    assert first["symbol"] == "RELIANCE.NS" and second["symbol"] == "TCS.BO"
    assert first["action"] == TransactionAction.BUY and third["action"] == TransactionAction.SELL
    assert first["quantity"] == Decimal("10.0000") and first["price"] == Decimal("2501.3500")
    assert first["external_id"] == "55012345"
    # 09:30:12 IST = 04:00:12 UTC (exact execution time preferred over the date)
    assert first["transaction_date"] == datetime(2024, 1, 15, 4, 0, 12, tzinfo=UTC)
    assert all(r["source"] == TransactionSource.TRADEBOOK_UPLOAD for r in parsed.rows)


def test_minimal_columns_and_excel_quirks():
    # Only the required columns, a BOM, header spacing/case, Excel-style dates and thousands separators.
    text = "﻿Symbol, Trade Type ,Quantity,Price,Trade Date\nINFY,BUY,3,\"1,450.5\",15-01-2024\n"
    row = parse_tradebook(csv_bytes(text)).rows[0]
    assert row["symbol"] == "INFY.NS"  # no exchange column -> NSE
    assert row["price"] == Decimal("1450.5000")
    assert row["transaction_date"] == datetime(2024, 1, 14, 18, 30, tzinfo=UTC)  # midnight IST
    assert row["external_id"] is None


def test_missing_columns_named_in_error():
    with pytest.raises(StatementError, match="Missing required column.*price.*trade_type"):
        parse_tradebook(csv_bytes("symbol,quantity,trade_date\nINFY,1,2024-01-01\n"))


def test_every_bad_row_reported_and_nothing_accepted():
    text = f"""{HEADER}
RELIANCE,,2024-01-15,NSE,EQ,EQ,hold,false,10,2501,1,1,
,,2024-01-15,NSE,EQ,EQ,buy,false,10,2501,2,2,
TCS,,2024-01-15,NSE,EQ,EQ,buy,false,0,3800,3,3,
TCS,,not-a-date,NSE,EQ,EQ,buy,false,1,abc,4,4,
"""
    with pytest.raises(StatementError) as exc:
        parse_tradebook(csv_bytes(text))
    errors = {e["row"]: e["error"] for e in exc.value.row_errors}
    assert set(errors) == {2, 3, 4, 5}  # spreadsheet row numbers (header = row 1)
    assert "trade_type" in errors[2] and "symbol" in errors[3]
    assert "quantity" in errors[4] and "price" in errors[5]


def test_future_dates_rejected():
    with pytest.raises(StatementError) as exc:
        parse_tradebook(csv_bytes("symbol,trade_type,quantity,price,trade_date\nINFY,buy,1,100,2999-01-01\n"))
    assert "future" in exc.value.row_errors[0]["error"]


@pytest.mark.parametrize("content", [b"", b"symbol,trade_type,quantity,price,trade_date\n", b"\xff\xfe\x00garbage"])
def test_empty_or_unreadable_files(content):
    with pytest.raises(StatementError):
        parse_tradebook(content)


# ---------------- endpoint (PostgreSQL) ----------------

def upload(text: str | bytes, filename: str = "tradebook.csv"):
    data = text.encode() if isinstance(text, str) else text
    return {"file": (filename, data, "text/csv")}


async def test_upload_inserts_transactions_and_reupload_is_idempotent(pg_client, pg_sessionmaker):
    h = await signup_headers(pg_client)

    r = await pg_client.post("/portfolio/import-statement", files=upload(ZERODHA_CSV), headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "rows_in_file": 4, "inserted": 3, "duplicates_skipped": 0, "non_equity_skipped": 1,
        "date_range": ["2024-01-15", "2024-03-20"],
    }

    r = await pg_client.post("/portfolio/import-statement", files=upload(ZERODHA_CSV), headers=h)
    assert r.json()["inserted"] == 0 and r.json()["duplicates_skipped"] == 3

    async with pg_sessionmaker() as db:
        rows = (await db.scalars(select(Transaction).order_by(Transaction.transaction_date))).all()
    assert [(t.symbol, t.action.value, t.quantity) for t in rows] == [
        ("RELIANCE.NS", "buy", Decimal("10.0000")),
        ("TCS.BO", "buy", Decimal("5.0000")),
        ("RELIANCE.NS", "sell", Decimal("4.0000")),
    ]
    assert all(t.source == TransactionSource.TRADEBOOK_UPLOAD and t.user_id == 1 for t in rows)
    assert rows[0].transaction_date.astimezone(UTC).date() == date(2024, 1, 15)


async def test_same_file_from_another_user_is_not_a_duplicate(pg_client):
    alice = await signup_headers(pg_client, "alice@example.com")
    bob = await signup_headers(pg_client, "bob@example.com")
    await pg_client.post("/portfolio/import-statement", files=upload(ZERODHA_CSV), headers=alice)
    r = await pg_client.post("/portfolio/import-statement", files=upload(ZERODHA_CSV), headers=bob)
    assert r.json()["inserted"] == 3


async def test_invalid_file_returns_422_with_row_errors(pg_client, pg_sessionmaker):
    h = await signup_headers(pg_client)
    bad = "symbol,trade_type,quantity,price,trade_date\nINFY,buy,1,100,2024-01-01\nTCS,hold,1,100,2024-01-01\n"
    r = await pg_client.post("/portfolio/import-statement", files=upload(bad), headers=h)
    assert r.status_code == 422
    assert r.json()["detail"]["row_errors"] == [{"row": 3, "error": "trade_type must be 'buy' or 'sell', got 'hold'"}]
    async with pg_sessionmaker() as db:
        assert (await db.scalars(select(Transaction))).all() == []  # the valid INFY row wasn't saved either


async def test_rejects_non_csv_and_oversized_files(pg_client, monkeypatch):
    h = await signup_headers(pg_client)
    r = await pg_client.post("/portfolio/import-statement", files=upload("x", "statement.pdf"), headers=h)
    assert r.status_code == 415

    from app.services import tradebook_import

    monkeypatch.setattr(tradebook_import, "MAX_FILE_BYTES", 100)
    r = await pg_client.post("/portfolio/import-statement", files=upload(ZERODHA_CSV), headers=h)
    assert r.status_code == 422 and "larger than" in r.json()["detail"]["message"]


async def test_upload_requires_login(pg_client):
    assert (await pg_client.post("/portfolio/import-statement", files=upload(ZERODHA_CSV))).status_code == 401
