"""
Zerodha Kite Connect: OAuth login and holdings sync.

Flow:
  1. Frontend calls GET /portfolio/zerodha/connect (with the user's JWT) and gets
     a Kite login URL containing a signed, 10-minute `state` token.
  2. The user logs in at Zerodha; Zerodha redirects the browser to our callback
     with `request_token` and our `state`.
  3. The callback verifies `state` (proves which user started the flow and
     that we started it), exchanges request_token + API secret for an
     access_token, and stores that token ENCRYPTED in broker_connections.
  4. sync_zerodha_holdings(user_id) uses the stored token to read holdings and
     delivery positions and upserts them as source = "kite_sync".

Kite access tokens expire every day at 6:00 AM IST; after that the user must
log in again ("Reconnect Zerodha"). The API key/secret come from .env only.
The kiteconnect SDK is synchronous, so its calls run in a worker thread.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException, TokenException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.crypto import InvalidToken, decrypt_secret, encrypt_secret
from app.core.database import AsyncSessionLocal
from app.core.security import create_purpose_token, decode_purpose_token
from app.models import BrokerConnection, PortfolioHolding
from app.models.enums import AssetType, TransactionSource
from app.schemas.portfolio import ZerodhaSyncReport

logger = logging.getLogger(__name__)

BROKER = "zerodha"
STATE_PURPOSE = "kite_oauth_state"
IST = ZoneInfo("Asia/Kolkata")
TOKEN_EXPIRY_TIME_IST = time(6, 0)
EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
FOUR_PLACES = Decimal("0.0001")


class ZerodhaError(Exception):
    """Base class; `str(exc)` is safe to show to the user."""


class ZerodhaNotConfigured(ZerodhaError):
    pass


class ZerodhaNotConnected(ZerodhaError):
    pass


class ZerodhaTokenExpired(ZerodhaError):
    pass


# ---------------- helpers ----------------

def _kite(access_token: str | None = None) -> KiteConnect:
    if not settings.ZERODHA_API_KEY or not settings.ZERODHA_API_SECRET:
        raise ZerodhaNotConfigured("Zerodha is not configured on the server (ZERODHA_API_KEY / ZERODHA_API_SECRET).")
    kite = KiteConnect(api_key=settings.ZERODHA_API_KEY, timeout=15)
    if access_token:
        kite.set_access_token(access_token)
    return kite


def next_token_expiry(now: datetime) -> datetime:
    """Kite tokens die at the next 6:00 AM IST."""
    local = now.astimezone(IST)
    expiry = datetime.combine(local.date(), TOKEN_EXPIRY_TIME_IST, tzinfo=IST)
    if local >= expiry:
        expiry += timedelta(days=1)
    return expiry.astimezone(UTC)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ---------------- 1. login URL ----------------

def build_login_url(user_id: int) -> str:
    """
    Kite login URL. `redirect_params` is Kite's mechanism for passing our own
    values through the login; it comes back to the callback as `?state=...`.
    """
    state = create_purpose_token(user_id, STATE_PURPOSE, expires_minutes=10)
    return f"{_kite().login_url()}&redirect_params={quote(urlencode({'state': state}))}"


def user_id_from_state(state: str | None) -> int | None:
    return decode_purpose_token(state, STATE_PURPOSE) if state else None


# ---------------- 2. callback: exchange request_token -> access_token ----------------

async def complete_login(db: AsyncSession, user_id: int, request_token: str) -> BrokerConnection:
    kite = _kite()
    try:
        session = await asyncio.to_thread(
            kite.generate_session, request_token, api_secret=settings.ZERODHA_API_SECRET
        )
    except KiteException as exc:  # invalid / already-used request_token, bad checksum, ...
        logger.warning("Kite session exchange failed for user %s: %s", user_id, exc)
        raise ZerodhaError("Zerodha rejected the login. Please try connecting again.") from exc
    except Exception as exc:  # network problems
        logger.error("Kite session exchange error for user %s: %s", user_id, type(exc).__name__)
        raise ZerodhaError("Could not reach Zerodha. Please try again.") from exc

    now = datetime.now(UTC)
    connection = await db.scalar(
        select(BrokerConnection).where(BrokerConnection.user_id == user_id, BrokerConnection.broker == BROKER)
    )
    if connection is None:
        connection = BrokerConnection(user_id=user_id, broker=BROKER)
        db.add(connection)
    connection.broker_user_id = session.get("user_id")
    connection.access_token_encrypted = encrypt_secret(session["access_token"])
    connection.expires_at = next_token_expiry(now)
    connection.connected_at = now
    await db.commit()
    logger.info("User %s connected Zerodha account %s", user_id, connection.broker_user_id)
    return connection


# ---------------- connection lookup / removal ----------------

async def get_connection(db: AsyncSession, user_id: int) -> BrokerConnection | None:
    return await db.scalar(
        select(BrokerConnection).where(BrokerConnection.user_id == user_id, BrokerConnection.broker == BROKER)
    )


def is_active(connection: BrokerConnection | None) -> bool:
    return connection is not None and _as_utc(connection.expires_at) > datetime.now(UTC)


async def disconnect(db: AsyncSession, user_id: int) -> None:
    """Forget the token and remove the synced holdings (they would go stale)."""
    await db.execute(
        delete(BrokerConnection).where(BrokerConnection.user_id == user_id, BrokerConnection.broker == BROKER)
    )
    await db.execute(
        delete(PortfolioHolding).where(
            PortfolioHolding.user_id == user_id, PortfolioHolding.source == TransactionSource.KITE_SYNC
        )
    )
    await db.commit()


# ---------------- 3. sync ----------------

@dataclass
class _Position:
    quantity: Decimal
    cost: Decimal  # quantity * average price, so merged averages are weighted correctly

    @property
    def avg_price(self) -> Decimal:
        return (self.cost / self.quantity).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def merge_holdings_and_positions(
    holdings: list[dict[str, Any]], positions: dict[str, Any]
) -> tuple[dict[str, _Position], int]:
    """
    Combine Kite's holdings (settled + T1 shares) with today's delivery (CNC)
    buys from positions, which only become holdings after settlement.
    Returns ({"RELIANCE.NS": _Position}, skipped_count).

    Skipped: non-equity exchanges (NFO/MCX/CDS), intraday/F&O products
    (MIS/NRML), short or zero quantities. Same-day sells of existing holdings
    are not subtracted (Kite reflects them after settlement).
    """
    merged: dict[str, _Position] = {}
    skipped = 0

    def add(item: dict[str, Any], quantity: Decimal) -> None:
        nonlocal skipped
        suffix = EXCHANGE_SUFFIX.get(item.get("exchange", ""))
        if suffix is None or quantity <= 0:
            skipped += 1
            return
        symbol = f"{item['tradingsymbol'].upper()}{suffix}"
        price = Decimal(str(item.get("average_price") or 0))
        pos = merged.setdefault(symbol, _Position(Decimal(0), Decimal(0)))
        pos.quantity += quantity
        pos.cost += quantity * price

    for h in holdings or []:
        add(h, Decimal(str(h.get("quantity") or 0)) + Decimal(str(h.get("t1_quantity") or 0)))

    for p in (positions or {}).get("net", []):
        if p.get("product") != "CNC":
            skipped += 1
            continue
        add(p, Decimal(str(p.get("quantity") or 0)))

    return merged, skipped


async def _fetch_from_kite(access_token: str) -> tuple[list[dict], dict]:
    kite = _kite(access_token)
    # Sequential on purpose: the SDK shares one requests.Session between calls.
    holdings = await asyncio.to_thread(kite.holdings)
    positions = await asyncio.to_thread(kite.positions)
    return holdings, positions


async def sync_with_session(db: AsyncSession, user_id: int) -> ZerodhaSyncReport:
    connection = await get_connection(db, user_id)
    if connection is None:
        raise ZerodhaNotConnected("Zerodha is not connected.")
    if not is_active(connection):
        raise ZerodhaTokenExpired("Your Zerodha session expired (daily at 6 AM). Please reconnect.")

    try:
        access_token = decrypt_secret(connection.access_token_encrypted)
    except InvalidToken:  # encryption key changed (JWT_SECRET_KEY rotated) or data tampered with
        await db.delete(connection)
        await db.commit()
        raise ZerodhaTokenExpired("Stored Zerodha session is unreadable. Please reconnect.") from None

    try:
        holdings, positions = await _fetch_from_kite(access_token)
    except TokenException:  # revoked or expired early (e.g. user logged out of all Kite sessions)
        await db.delete(connection)
        await db.commit()
        raise ZerodhaTokenExpired("Zerodha rejected the session. Please reconnect.") from None
    except KiteException as exc:
        logger.error("Kite API error for user %s: %s", user_id, exc)
        raise ZerodhaError("Zerodha returned an error while reading holdings.") from exc
    except Exception as exc:
        logger.error("Kite request failed for user %s: %s", user_id, type(exc).__name__)
        raise ZerodhaError("Could not reach Zerodha. Please try again.") from exc

    merged, skipped = merge_holdings_and_positions(holdings, positions)

    if merged:
        values = [
            {
                "user_id": user_id,
                "asset_type": AssetType.STOCK,
                "symbol": symbol,
                "quantity": pos.quantity,
                "avg_buy_price": pos.avg_price,
                "source": TransactionSource.KITE_SYNC,
            }
            for symbol, pos in merged.items()
        ]
        stmt = pg_insert(PortfolioHolding).values(values)
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_portfolio_holdings_user_asset_symbol_source",
                set_={"quantity": stmt.excluded.quantity, "avg_buy_price": stmt.excluded.avg_buy_price},
            )
        )

    # Anything synced earlier but not in Zerodha any more was sold.
    removed = await db.execute(
        delete(PortfolioHolding).where(
            PortfolioHolding.user_id == user_id,
            PortfolioHolding.source == TransactionSource.KITE_SYNC,
            PortfolioHolding.symbol.not_in(list(merged)),
        )
    )
    connection.last_synced_at = datetime.now(UTC)
    await db.commit()

    report = ZerodhaSyncReport(holdings_upserted=len(merged), holdings_removed=removed.rowcount, skipped=skipped)
    logger.info("Zerodha sync for user %s: %s", user_id, report.model_dump())
    return report


async def sync_zerodha_holdings(
    user_id: int, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal
) -> ZerodhaSyncReport:
    """
    Pull current holdings + delivery positions from Kite and upsert them into
    portfolio_holdings (source = kite_sync). For background jobs; API routes
    call sync_with_session() with the request's session.
    Raises ZerodhaError subclasses (not connected, expired, API failure).
    """
    async with session_factory() as db:
        return await sync_with_session(db, user_id)
