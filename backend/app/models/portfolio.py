"""The user's current holdings and their transaction history."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import AssetType, TransactionAction, TransactionSource, str_enum

if TYPE_CHECKING:
    from app.models.user import User

# Quantities allow fractions (mutual-fund units, grams of gold).
QTY = Numeric(18, 4)
PRICE = Numeric(18, 4)


class PortfolioHolding(Base):
    """
    One position per (user, asset_type, symbol, source).

    `symbol` is the exchange ticker for stocks (e.g. "RELIANCE.NS"), the scheme
    code for mutual funds, and a free-text label for non-market assets
    (e.g. "SBI FD 2027", "Flat - Pune").

    `source` keeps manually-entered rows separate from Zerodha-synced ones: the
    same stock can be held at Zerodha AND at another broker (entered manually),
    and a Kite sync must never overwrite or delete the manual row.
    """

    __tablename__ = "portfolio_holdings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "asset_type", "symbol", "source", name="uq_portfolio_holdings_user_asset_symbol_source"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("avg_buy_price >= 0", name="avg_buy_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_type: Mapped[AssetType] = mapped_column(str_enum(AssetType, "asset_type"))
    symbol: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    avg_buy_price: Mapped[Decimal] = mapped_column(PRICE)
    source: Mapped[TransactionSource] = mapped_column(
        str_enum(TransactionSource, "source"), server_default=TransactionSource.MANUAL.value
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="holdings")


class Transaction(Base):
    """A single buy/sell, from manual entry, a Tradebook/CAS upload, or Kite sync."""

    __tablename__ = "transactions"
    __table_args__ = (
        # Re-uploading the same tradebook must not double-count trades. Rows without an
        # external_id (NULL) never conflict, because NULLs are distinct in a UNIQUE constraint.
        UniqueConstraint("user_id", "source", "external_id", name="uq_transactions_user_source_external_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        Index("ix_transactions_user_id_transaction_date", "user_id", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(64))
    action: Mapped[TransactionAction] = mapped_column(str_enum(TransactionAction, "action"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    price: Mapped[Decimal] = mapped_column(PRICE)
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[TransactionSource] = mapped_column(str_enum(TransactionSource, "source"))
    # Broker's own id for the trade (Zerodha tradebook "trade_id"), used for de-duplication.
    external_id: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="transactions")
