"""Manual holdings CRUD: /portfolio/holdings (runs on in-memory SQLite)."""

from decimal import Decimal

from app.models import PortfolioHolding
from app.models.enums import AssetType, TransactionSource
from tests.conftest import signup_headers

RELIANCE = {"asset_type": "stock", "symbol": "reliance", "quantity": "10", "avg_buy_price": "2450.50"}


async def test_add_list_update_delete(client):
    h = await signup_headers(client)

    r = await client.post("/portfolio/holdings", json=RELIANCE, headers=h)
    assert r.status_code == 201
    holding = r.json()
    assert holding["symbol"] == "RELIANCE.NS"  # upper-cased, NSE suffix added
    assert holding["quantity"] == 10 and holding["avg_buy_price"] == 2450.5
    assert holding["source"] == "manual"

    fd = {"asset_type": "fd", "symbol": "SBI FD 2027", "quantity": "1", "avg_buy_price": "100000"}
    assert (await client.post("/portfolio/holdings", json=fd, headers=h)).json()["symbol"] == "SBI FD 2027"

    r = await client.get("/portfolio/holdings", headers=h)
    assert [x["symbol"] for x in r.json()] == ["SBI FD 2027", "RELIANCE.NS"]  # ordered by asset_type, symbol

    r = await client.put(f"/portfolio/holdings/{holding['id']}", json={"quantity": "15"}, headers=h)
    assert r.status_code == 200
    assert r.json()["quantity"] == 15 and r.json()["avg_buy_price"] == 2450.5  # untouched field kept

    assert (await client.delete(f"/portfolio/holdings/{holding['id']}", headers=h)).status_code == 204
    assert len((await client.get("/portfolio/holdings", headers=h)).json()) == 1


async def test_duplicate_holding_rejected(client):
    h = await signup_headers(client)
    await client.post("/portfolio/holdings", json=RELIANCE, headers=h)
    r = await client.post("/portfolio/holdings", json={**RELIANCE, "symbol": "RELIANCE.NS"}, headers=h)
    assert r.status_code == 409


async def test_validation_errors(client):
    h = await signup_headers(client)
    for bad in (
        {**RELIANCE, "quantity": "0"},
        {**RELIANCE, "avg_buy_price": "-1"},
        {**RELIANCE, "asset_type": "crypto"},
        {**RELIANCE, "symbol": ""},
    ):
        assert (await client.post("/portfolio/holdings", json=bad, headers=h)).status_code == 422
    r = await client.post("/portfolio/holdings", json=RELIANCE, headers=h)
    assert (await client.put(f"/portfolio/holdings/{r.json()['id']}", json={}, headers=h)).status_code == 422


async def test_users_cannot_see_or_touch_each_others_holdings(client):
    alice = await signup_headers(client, "alice@example.com")
    bob = await signup_headers(client, "bob@example.com")
    alice_holding = (await client.post("/portfolio/holdings", json=RELIANCE, headers=alice)).json()

    assert (await client.get("/portfolio/holdings", headers=bob)).json() == []
    url = f"/portfolio/holdings/{alice_holding['id']}"
    assert (await client.put(url, json={"quantity": "1"}, headers=bob)).status_code == 404
    assert (await client.delete(url, headers=bob)).status_code == 404
    assert (await client.get("/portfolio/holdings", headers=alice)).json()[0]["quantity"] == 10


async def test_requires_login(client):
    assert (await client.get("/portfolio/holdings")).status_code == 401
    assert (await client.post("/portfolio/holdings", json=RELIANCE)).status_code == 401


async def test_zerodha_synced_rows_are_read_only(client, db_sessionmaker):
    h = await signup_headers(client)
    async with db_sessionmaker() as db:
        row = PortfolioHolding(user_id=1, asset_type=AssetType.STOCK, symbol="TCS.NS", quantity=Decimal(5),
                               avg_buy_price=Decimal(3500), source=TransactionSource.KITE_SYNC)
        db.add(row)
        await db.commit()
        row_id = row.id

    assert (await client.put(f"/portfolio/holdings/{row_id}", json={"quantity": "1"}, headers=h)).status_code == 409
    assert (await client.delete(f"/portfolio/holdings/{row_id}", headers=h)).status_code == 409

    # A manual row for the same stock can coexist with the synced one (e.g. held at another broker).
    manual = {"asset_type": "stock", "symbol": "TCS.NS", "quantity": "2", "avg_buy_price": "3000"}
    assert (await client.post("/portfolio/holdings", json=manual, headers=h)).status_code == 201
