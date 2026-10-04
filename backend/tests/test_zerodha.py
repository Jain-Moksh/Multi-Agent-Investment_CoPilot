"""
Zerodha Kite Connect flow with a fake KiteConnect class (no real Zerodha
account or network needed). Flow tests use PostgreSQL (TEST_DATABASE_URL).
"""

from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from kiteconnect.exceptions import NetworkException, TokenException
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import InvalidToken, decrypt_secret, encrypt_secret
from app.core.security import create_access_token, create_purpose_token
from app.models import BrokerConnection, PortfolioHolding
from app.models.enums import TransactionSource
from app.services import zerodha
from tests.conftest import signup_headers

ACCESS_TOKEN = "kite-access-token-123"

HOLDINGS = [
    {"tradingsymbol": "RELIANCE", "exchange": "NSE", "quantity": 10, "t1_quantity": 2, "average_price": 2400.0},
    {"tradingsymbol": "TCS", "exchange": "BSE", "quantity": 5, "t1_quantity": 0, "average_price": 3500.0},
    {"tradingsymbol": "SGBJUN31", "exchange": "NSE", "quantity": 0, "t1_quantity": 0, "average_price": 5000.0},
]
POSITIONS = {
    "net": [
        # Bought 8 more RELIANCE today for delivery -> merged into the holding.
        {"tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC", "quantity": 8, "average_price": 2500.0},
        {"tradingsymbol": "INFY", "exchange": "NSE", "product": "MIS", "quantity": 100, "average_price": 1500.0},
        {"tradingsymbol": "NIFTY24OCTFUT", "exchange": "NFO", "product": "NRML", "quantity": 50, "average_price": 1.0},
    ],
    "day": [],
}


class FakeKite:
    """Stands in for kiteconnect.KiteConnect; behaviour is controlled via class attributes."""

    holdings_data: list = HOLDINGS
    positions_data: dict = POSITIONS
    fail_with: Exception | None = None
    sessions: list = []

    def __init__(self, api_key, timeout=None):
        self.api_key = api_key
        self.access_token = None

    def login_url(self):
        return f"https://kite.zerodha.com/connect/login?api_key={self.api_key}&v=3"

    def set_access_token(self, token):
        self.access_token = token

    def generate_session(self, request_token, api_secret):
        if request_token == "bad-token":
            raise TokenException("Token is invalid or has expired.")
        FakeKite.sessions.append((request_token, api_secret))
        return {"access_token": ACCESS_TOKEN, "user_id": "AB1234"}

    def _check(self):
        assert self.access_token == ACCESS_TOKEN
        if FakeKite.fail_with:
            raise FakeKite.fail_with

    def holdings(self):
        self._check()
        return FakeKite.holdings_data

    def positions(self):
        self._check()
        return FakeKite.positions_data


@pytest.fixture(autouse=True)
def fake_kite(monkeypatch):
    monkeypatch.setattr(zerodha, "KiteConnect", FakeKite)
    monkeypatch.setattr(settings, "ZERODHA_API_KEY", "test-api-key")
    monkeypatch.setattr(settings, "ZERODHA_API_SECRET", "test-api-secret")
    FakeKite.holdings_data, FakeKite.positions_data, FakeKite.fail_with = HOLDINGS, POSITIONS, None
    FakeKite.sessions = []


async def connect(client, headers) -> str:
    """Run connect + callback like a browser would; returns the frontend redirect URL."""
    login_url = (await client.get("/portfolio/zerodha/connect", headers=headers)).json()["login_url"]
    state = parse_qs(parse_qs(urlparse(login_url).query)["redirect_params"][0])["state"][0]
    r = await client.get(
        "/portfolio/zerodha/callback",
        params={"request_token": "req-token-1", "status": "success", "action": "login", "state": state},
    )
    assert r.status_code == 303
    return r.headers["location"]


async def holdings_by_symbol(session_factory, source=TransactionSource.KITE_SYNC):
    async with session_factory() as db:
        rows = (await db.scalars(select(PortfolioHolding).where(PortfolioHolding.source == source))).all()
    return {r.symbol: (r.quantity, r.avg_buy_price) for r in rows}


# ---------------- pure helpers ----------------

@pytest.mark.parametrize(
    "now_utc, expected_utc",
    [
        (datetime(2026, 10, 3, 10, 0, tzinfo=UTC), datetime(2026, 10, 4, 0, 30, tzinfo=UTC)),  # 15:30 IST -> next 06:00 IST
        (datetime(2026, 10, 2, 21, 0, tzinfo=UTC), datetime(2026, 10, 3, 0, 30, tzinfo=UTC)),  # 02:30 IST -> same day 06:00
    ],
)
def test_token_expiry_is_next_6am_ist(now_utc, expected_utc):
    assert zerodha.next_token_expiry(now_utc) == expected_utc


def test_merge_holdings_and_positions():
    merged, skipped = zerodha.merge_holdings_and_positions(HOLDINGS, POSITIONS)
    assert set(merged) == {"RELIANCE.NS", "TCS.BO"}
    rel = merged["RELIANCE.NS"]
    assert rel.quantity == 20                                         # 10 + 2 (T1) + 8 (today's CNC buy)
    assert rel.avg_price == Decimal("2440.0000")                      # (12*2400 + 8*2500) / 20
    assert skipped == 3                                               # zero-qty SGB, MIS, NRML


def test_encryption_round_trip_and_tamper_detection():
    ciphertext = encrypt_secret(ACCESS_TOKEN)
    assert ACCESS_TOKEN not in ciphertext
    assert decrypt_secret(ciphertext) == ACCESS_TOKEN
    with pytest.raises(InvalidToken):
        decrypt_secret(ciphertext[:-4] + "AAAA")


def test_login_url_carries_signed_state():
    url = zerodha.build_login_url(user_id=42)
    query = parse_qs(urlparse(url).query)
    assert query["api_key"] == ["test-api-key"]
    state = parse_qs(query["redirect_params"][0])["state"][0]
    assert zerodha.user_id_from_state(state) == 42
    assert "test-api-secret" not in url


def test_access_token_is_not_accepted_as_state():
    assert zerodha.user_id_from_state(create_access_token(42)) is None
    assert zerodha.user_id_from_state("forged") is None


# ---------------- full flow (PostgreSQL) ----------------

async def test_connect_callback_stores_encrypted_token_and_syncs(pg_client, pg_sessionmaker):
    h = await signup_headers(pg_client)
    location = await connect(pg_client, h)

    assert location == "http://localhost:5173/portfolio?zerodha=connected"
    assert FakeKite.sessions == [("req-token-1", "test-api-secret")]

    async with pg_sessionmaker() as db:
        conn = await db.scalar(select(BrokerConnection))
    assert conn.broker_user_id == "AB1234"
    assert ACCESS_TOKEN not in conn.access_token_encrypted           # stored encrypted
    assert decrypt_secret(conn.access_token_encrypted) == ACCESS_TOKEN
    assert conn.last_synced_at is not None                            # first sync ran in the callback

    assert await holdings_by_symbol(pg_sessionmaker) == {
        "RELIANCE.NS": (Decimal("20.0000"), Decimal("2440.0000")),
        "TCS.BO": (Decimal("5.0000"), Decimal("3500.0000")),
    }

    status = (await pg_client.get("/portfolio/zerodha/status", headers=h)).json()
    assert status["connected"] and status["broker_user_id"] == "AB1234"


async def test_resync_updates_and_removes_sold_holdings_but_not_manual_ones(pg_client, pg_sessionmaker):
    h = await signup_headers(pg_client)
    manual = {"asset_type": "stock", "symbol": "TCS.BO", "quantity": "1", "avg_buy_price": "3000"}
    await pg_client.post("/portfolio/holdings", json=manual, headers=h)
    await connect(pg_client, h)

    FakeKite.holdings_data = [
        {"tradingsymbol": "RELIANCE", "exchange": "NSE", "quantity": 25, "t1_quantity": 0, "average_price": 2450.0}
    ]
    FakeKite.positions_data = {"net": [], "day": []}
    r = await pg_client.post("/portfolio/zerodha/sync", headers=h)
    assert r.json() == {"holdings_upserted": 1, "holdings_removed": 1, "skipped": 0}

    assert await holdings_by_symbol(pg_sessionmaker) == {"RELIANCE.NS": (Decimal("25.0000"), Decimal("2450.0000"))}
    assert await holdings_by_symbol(pg_sessionmaker, TransactionSource.MANUAL) == {
        "TCS.BO": (Decimal("1.0000"), Decimal("3000.0000"))
    }


async def test_revoked_token_removes_connection(pg_client, pg_sessionmaker):
    h = await signup_headers(pg_client)
    await connect(pg_client, h)

    FakeKite.fail_with = TokenException("Incorrect `api_key` or `access_token`.")
    r = await pg_client.post("/portfolio/zerodha/sync", headers=h)
    assert r.status_code == 409 and "reconnect" in r.json()["detail"].lower()
    assert (await pg_client.get("/portfolio/zerodha/status", headers=h)).json() == {
        "connected": False, "broker_user_id": None, "expires_at": None, "last_synced_at": None,
    }


async def test_network_error_keeps_connection(pg_client):
    h = await signup_headers(pg_client)
    await connect(pg_client, h)
    FakeKite.fail_with = NetworkException("Gateway timed out")
    assert (await pg_client.post("/portfolio/zerodha/sync", headers=h)).status_code == 502
    assert (await pg_client.get("/portfolio/zerodha/status", headers=h)).json()["connected"] is True


async def test_expired_connection_requires_reconnect(pg_client, pg_sessionmaker):
    h = await signup_headers(pg_client)
    await connect(pg_client, h)
    async with pg_sessionmaker() as db:
        conn = await db.scalar(select(BrokerConnection))
        conn.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        await db.commit()
    r = await pg_client.post("/portfolio/zerodha/sync", headers=h)
    assert r.status_code == 409 and "expired" in r.json()["detail"]


async def test_disconnect_removes_token_and_synced_holdings(pg_client, pg_sessionmaker):
    h = await signup_headers(pg_client)
    await pg_client.post(
        "/portfolio/holdings",
        json={"asset_type": "gold", "symbol": "Gold coins", "quantity": "10", "avg_buy_price": "6000"},
        headers=h,
    )
    await connect(pg_client, h)

    assert (await pg_client.delete("/portfolio/zerodha", headers=h)).status_code == 204
    assert await holdings_by_symbol(pg_sessionmaker) == {}
    assert len(await holdings_by_symbol(pg_sessionmaker, TransactionSource.MANUAL)) == 1  # manual kept
    async with pg_sessionmaker() as db:
        assert await db.scalar(select(BrokerConnection)) is None


@pytest.mark.parametrize(
    "params, result",
    [
        ({"request_token": "x", "status": "success", "state": "forged"}, "invalid_state"),
        ({"request_token": "x", "status": "success"}, "invalid_state"),
        ({"status": "cancelled", "state": "__VALID__"}, "cancelled"),
        ({"request_token": "bad-token", "status": "success", "state": "__VALID__"}, "error"),
    ],
)
async def test_callback_failure_modes(pg_client, pg_sessionmaker, params, result):
    await signup_headers(pg_client)
    if params.get("state") == "__VALID__":
        params = {**params, "state": create_purpose_token(1, zerodha.STATE_PURPOSE)}
    r = await pg_client.get("/portfolio/zerodha/callback", params=params)
    assert r.headers["location"].endswith(f"zerodha={result}")
    async with pg_sessionmaker() as db:
        assert await db.scalar(select(BrokerConnection)) is None


async def test_not_configured_returns_503(pg_client, monkeypatch):
    h = await signup_headers(pg_client)
    monkeypatch.setattr(settings, "ZERODHA_API_KEY", "")
    r = await pg_client.get("/portfolio/zerodha/connect", headers=h)
    assert r.status_code == 503 and "ZERODHA_API_KEY" in r.json()["detail"]


async def test_zerodha_endpoints_require_login(pg_client):
    assert (await pg_client.get("/portfolio/zerodha/connect")).status_code == 401
    assert (await pg_client.post("/portfolio/zerodha/sync")).status_code == 401
