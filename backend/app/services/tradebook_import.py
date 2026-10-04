"""
Import a Zerodha Console **Tradebook** CSV into the transactions table.

Zerodha's export (Console -> Reports -> Tradebook -> Download CSV) has these
columns:
    symbol, isin, trade_date, exchange, segment, series, trade_type, auction,
    quantity, price, trade_id, order_id, order_execution_time

Required here: symbol, trade_type, quantity, price, trade_date.
Used when present: exchange (NSE -> ".NS", BSE -> ".BO"), segment (only
equity "EQ" rows are imported), trade_id (de-duplication),
order_execution_time (exact timestamp instead of just the date).

The import is all-or-nothing: if any row is invalid, nothing is inserted and
every bad row is reported, so the user can fix the file and re-upload.
Re-uploading the same file is safe: trades with a known trade_id are skipped.
"""

import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.models.enums import TransactionAction, TransactionSource
from app.schemas.portfolio import ImportReport

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000
MAX_REPORTED_ERRORS = 50
INSERT_CHUNK_SIZE = 500

REQUIRED_COLUMNS = {"symbol", "trade_type", "quantity", "price", "trade_date"}
EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
EQUITY_SEGMENTS = {"EQ"}
FOUR_PLACES = Decimal("0.0001")


class StatementError(Exception):
    """The file can't be imported. `row_errors` lists problems per CSV row."""

    def __init__(self, message: str, row_errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.message = message
        self.row_errors = row_errors or []


@dataclass
class ParsedTradebook:
    rows: list[dict[str, Any]] = field(default_factory=list)  # ready for INSERT (minus user_id)
    rows_in_file: int = 0
    non_equity_skipped: int = 0


# ---------------- parsing helpers (each raises ValueError with a readable message) ----------------

def _parse_decimal(raw: str, name: str, *, positive: bool) -> Decimal:
    try:
        value = Decimal(raw.replace(",", ""))  # tolerate "1,250.50"
    except InvalidOperation:
        raise ValueError(f"{name} {raw!r} is not a number") from None
    if not value.is_finite() or (value <= 0 if positive else value < 0):
        raise ValueError(f"{name} must be {'greater than 0' if positive else 'at least 0'}, got {raw!r}")
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def _parse_timestamp(trade_date: str, execution_time: str) -> datetime:
    """Prefer the exact execution time; fall back to the trade date (midnight IST)."""
    for raw in (execution_time, trade_date):
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(raw)  # Zerodha's format: "2024-01-15", "2024-01-15T09:30:12"
        except ValueError:
            # Files re-saved in Excel often become "15-01-2024" / "15/01/2024": Indian day-first order.
            parsed = pd.to_datetime(raw, errors="coerce", dayfirst=True)
            if pd.isna(parsed):
                continue
            ts = parsed.to_pydatetime()
        return ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=IST).astimezone(UTC)
    raise ValueError(f"trade_date {trade_date!r} is not a valid date")


def _yahoo_symbol(symbol: str, exchange: str) -> str:
    """'RELIANCE' on NSE -> 'RELIANCE.NS' (same convention as the rest of the app)."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol is empty")
    if "." in symbol:
        return symbol
    return symbol + EXCHANGE_SUFFIX.get(exchange.strip().upper(), ".NS")


def parse_tradebook(content: bytes) -> ParsedTradebook:
    """Validate and convert the CSV. Raises StatementError; never touches the database."""
    try:
        df = pd.read_csv(
            io.BytesIO(content),
            dtype=str,                 # keep raw text: no float rounding, no "trade_id" as 1.2e+15
            keep_default_na=False,     # empty cells -> "" instead of NaN
            encoding="utf-8-sig",      # Excel adds a BOM when re-saving
            skipinitialspace=True,
        )
    except pd.errors.EmptyDataError:
        raise StatementError("The file is empty.") from None
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise StatementError(f"Could not read the file as CSV: {exc}") from None

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise StatementError(
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Found: {', '.join(df.columns)}. Expected a Zerodha Console Tradebook CSV."
        )
    if df.empty:
        raise StatementError("The file has a header but no trades.")
    if len(df) > MAX_ROWS:
        raise StatementError(f"Too many rows ({len(df)}); the limit is {MAX_ROWS}.")

    parsed = ParsedTradebook(rows_in_file=len(df))
    errors: list[dict[str, Any]] = []

    for index, record in enumerate(df.to_dict("records")):
        row_number = index + 2  # header is row 1, as in a spreadsheet
        get = lambda col: str(record.get(col, "")).strip()  # noqa: E731

        segment = get("segment").upper()
        if segment and segment not in EQUITY_SEGMENTS:
            parsed.non_equity_skipped += 1
            continue

        try:
            action = get("trade_type").lower()
            if action not in ("buy", "sell"):
                raise ValueError(f"trade_type must be 'buy' or 'sell', got {get('trade_type')!r}")
            parsed.rows.append(
                {
                    "symbol": _yahoo_symbol(get("symbol"), get("exchange")),
                    "action": TransactionAction(action),
                    "quantity": _parse_decimal(get("quantity"), "quantity", positive=True),
                    "price": _parse_decimal(get("price"), "price", positive=False),
                    "transaction_date": _parse_timestamp(get("trade_date"), get("order_execution_time")),
                    "source": TransactionSource.TRADEBOOK_UPLOAD,
                    "external_id": get("trade_id") or None,
                }
            )
        except ValueError as exc:
            errors.append({"row": row_number, "error": str(exc)})

    future = [r for r in parsed.rows if r["transaction_date"] > datetime.now(UTC)]
    if future:
        errors.append({"row": None, "error": f"{len(future)} trade(s) are dated in the future"})

    if errors:
        raise StatementError(
            f"{len(errors)} row(s) have problems; nothing was imported. Fix them and upload again.",
            errors[:MAX_REPORTED_ERRORS],
        )
    return parsed


async def import_tradebook(db: AsyncSession, user_id: int, content: bytes) -> ImportReport:
    """Parse, then bulk-insert into transactions (source = tradebook_upload)."""
    if len(content) > MAX_FILE_BYTES:
        raise StatementError(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    parsed = parse_tradebook(content)

    rows = [{**row, "user_id": user_id} for row in parsed.rows]
    inserted = 0
    for start in range(0, len(rows), INSERT_CHUNK_SIZE):
        stmt = (
            pg_insert(Transaction)
            .values(rows[start : start + INSERT_CHUNK_SIZE])
            # Same trade_id already imported -> skip (rows without trade_id never conflict).
            .on_conflict_do_nothing(constraint="uq_transactions_user_source_external_id")
            .returning(Transaction.id)
        )
        inserted += len((await db.execute(stmt)).all())
    await db.commit()

    dates: list[date] = sorted(r["transaction_date"].astimezone(IST).date() for r in rows)
    report = ImportReport(
        rows_in_file=parsed.rows_in_file,
        inserted=inserted,
        duplicates_skipped=len(rows) - inserted,
        non_equity_skipped=parsed.non_equity_skipped,
        date_range=(dates[0], dates[-1]) if dates else None,
    )
    logger.info("Tradebook import for user %s: %s", user_id, report.model_dump())
    return report
