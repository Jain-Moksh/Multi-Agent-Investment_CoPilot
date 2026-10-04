"""Linked brokerage accounts (currently Zerodha Kite Connect)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class BrokerConnection(Base):
    """
    A user's authorised link to a broker.

    The broker access token is stored ENCRYPTED (Fernet, see
    app/core/crypto.py): a leaked database dump alone can't be used to read
    anyone's portfolio. Kite tokens expire every day at ~6 AM IST, after which
    the user must reconnect.
    """

    __tablename__ = "broker_connections"
    __table_args__ = (UniqueConstraint("user_id", "broker", name="uq_broker_connections_user_broker"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    broker: Mapped[str] = mapped_column(String(32))                 # "zerodha"
    broker_user_id: Mapped[str | None] = mapped_column(String(64))  # e.g. Zerodha client id "AB1234"
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="broker_connections")
