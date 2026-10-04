"""
Auth flow tests: signup → login → protected endpoint → refresh → logout.

Run from backend/:  pytest -v
"""

from datetime import UTC, datetime, timedelta

from jose import jwt

from app.core.config import settings

EMAIL = "Alice@Example.com"
PASSWORD = "correct-horse-42"


async def signup(client, email=EMAIL, password=PASSWORD):
    return await client.post("/auth/signup", json={"email": email, "password": password})


async def login(client, email=EMAIL, password=PASSWORD):
    # OAuth2 password flow uses form fields, with the email in `username`.
    return await client.post("/auth/login", data={"username": email, "password": password})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------- happy path ----------------

async def test_signup_login_and_access_protected_route(client):
    r = await signup(client)
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert "refresh_token" in r.cookies  # set as httpOnly cookie, not in the body

    r = await login(client, email="alice@example.com")  # email is case-insensitive
    assert r.status_code == 200
    token = r.json()["access_token"]

    r = await client.get("/auth/me", headers=bearer(token))
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"
    assert "hashed_password" not in r.json()


# ---------------- signup / login failures ----------------

async def test_duplicate_email_is_rejected(client):
    await signup(client)
    r = await signup(client, email="alice@example.com")
    assert r.status_code == 409


async def test_signup_validates_input(client):
    assert (await signup(client, email="not-an-email")).status_code == 422
    assert (await signup(client, password="short")).status_code == 422


async def test_login_with_wrong_password_or_unknown_email(client):
    await signup(client)
    assert (await login(client, password="wrong-password")).status_code == 401
    assert (await login(client, email="nobody@example.com")).status_code == 401


# ---------------- protected route ----------------

async def test_protected_route_rejects_missing_or_bad_tokens(client):
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/me", headers=bearer("garbage"))).status_code == 401


async def test_expired_access_token_is_rejected(client):
    await signup(client)
    expired = jwt.encode(
        {"sub": "1", "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert (await client.get("/auth/me", headers=bearer(expired))).status_code == 401


async def test_token_signed_with_other_secret_is_rejected(client):
    await signup(client)
    forged = jwt.encode({"sub": "1", "type": "access"}, "attacker-secret", algorithm="HS256")
    assert (await client.get("/auth/me", headers=bearer(forged))).status_code == 401


# ---------------- refresh tokens ----------------

async def test_refresh_rotates_token(client):
    await signup(client)
    old_cookie = client.cookies["refresh_token"]

    r = await client.post("/auth/refresh")
    assert r.status_code == 200
    new_cookie = client.cookies["refresh_token"]
    assert new_cookie != old_cookie

    r = await client.get("/auth/me", headers=bearer(r.json()["access_token"]))
    assert r.status_code == 200


async def test_reused_refresh_token_revokes_all_sessions(client):
    await signup(client)
    stolen = client.cookies["refresh_token"]

    assert (await client.post("/auth/refresh")).status_code == 200  # legit user rotates
    legit = client.cookies["refresh_token"]

    # Attacker replays the old token -> rejected, and every session is revoked.
    client.cookies.clear()
    client.cookies.set("refresh_token", stolen, path="/auth")
    assert (await client.post("/auth/refresh")).status_code == 401

    client.cookies.clear()
    client.cookies.set("refresh_token", legit, path="/auth")
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh_token(client):
    await signup(client)
    token = client.cookies["refresh_token"]

    assert (await client.post("/auth/logout")).status_code == 204

    client.cookies.set("refresh_token", token, path="/auth")
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_refresh_without_cookie(client):
    assert (await client.post("/auth/refresh")).status_code == 401
