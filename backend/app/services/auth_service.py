"""
Database-backed auth logic: creating users, authenticating, and the refresh-token
lifecycle (issue → rotate → revoke).
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models import RefreshToken, User

logger = logging.getLogger(__name__)


class EmailAlreadyRegistered(Exception):
    pass


class InvalidRefreshToken(Exception):
    pass


def _as_utc(dt: datetime) -> datetime:
    """PostgreSQL returns tz-aware datetimes; SQLite (tests) returns naive UTC ones."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ---------------- users ----------------

async def create_user(db: AsyncSession, email: str, password: str) -> User:
    user = User(email=email.lower(), hashed_password=hash_password(password))
    db.add(user)
    try:
        await db.flush()  # assigns user.id; raises if the email is taken
    except IntegrityError as exc:
        await db.rollback()
        raise EmailAlreadyRegistered from exc
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    # verify_password runs even for unknown emails, so timing reveals nothing.
    if not verify_password(password, user.hashed_password if user else None):
        return None
    return user


# ---------------- refresh tokens ----------------

async def issue_refresh_token(db: AsyncSession, user_id: int) -> str:
    """Create and store a new refresh token; returns the raw token (only time it exists)."""
    raw_token = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    await db.flush()
    return raw_token


async def revoke_all_user_tokens(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> tuple[User, str]:
    """
    Exchange a valid refresh token for (user, new refresh token).
    The old token is revoked, so each refresh token works only once.
    """
    stored = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if stored is None:
        raise InvalidRefreshToken("unknown token")

    if stored.revoked_at is not None:
        # A used/revoked token came back: it was probably stolen. Log out every session.
        logger.warning("Refresh token reuse detected for user_id=%s; revoking all sessions", stored.user_id)
        await revoke_all_user_tokens(db, stored.user_id)
        await db.commit()
        raise InvalidRefreshToken("token reuse detected")

    if _as_utc(stored.expires_at) <= datetime.now(UTC):
        raise InvalidRefreshToken("token expired")

    stored.revoked_at = datetime.now(UTC)
    new_token = await issue_refresh_token(db, stored.user_id)
    user = await db.get(User, stored.user_id)
    return user, new_token


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    """Logout: revoke this one token (other devices stay logged in)."""
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(raw_token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
