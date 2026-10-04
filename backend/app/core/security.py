"""
Low-level auth primitives: password hashing and token creation/decoding.
No database access here; see app/services/auth_service.py for that.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt with passlib. NOTE: passlib 1.7.4 needs bcrypt==4.0.1 (pinned in requirements).
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A real bcrypt hash used when the email doesn't exist, so a failed login takes
# the same time either way (prevents discovering registered emails by timing).
_DUMMY_HASH = pwd_context.hash("dummy-password-for-timing")

ACCESS_TOKEN_TYPE = "access"


# ---------------- passwords ----------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    """Constant-time check. Pass hashed_password=None for unknown users."""
    if hashed_password is None:
        pwd_context.verify(password, _DUMMY_HASH)
        return False
    return pwd_context.verify(password, hashed_password)


# ---------------- access tokens (JWT) ----------------

def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),           # JWT spec: subject must be a string
        "type": ACCESS_TOKEN_TYPE,      # stops other token kinds being used as access tokens
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user id if the token is valid, unexpired and an access token; else None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:  # bad signature, malformed, or expired
        return None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------- single-purpose tokens (e.g. OAuth "state") ----------------

def create_purpose_token(user_id: int, purpose: str, expires_minutes: int = 10) -> str:
    """
    Short-lived signed JWT for one specific job, such as the `state` value that
    travels through Zerodha's login and back to our callback. The `type` claim
    stops it from ever being accepted as an access token, and vice versa.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": purpose,
        "nonce": secrets.token_urlsafe(8),
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_purpose_token(token: str, purpose: str) -> int | None:
    """User id if the token is valid, unexpired and was issued for `purpose`; else None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != purpose:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------- refresh tokens (opaque random strings) ----------------

def generate_refresh_token() -> str:
    """256 bits of randomness. Not a JWT: its validity is checked against the DB."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 is enough here: the token is already high-entropy random data."""
    return hashlib.sha256(token.encode()).hexdigest()
