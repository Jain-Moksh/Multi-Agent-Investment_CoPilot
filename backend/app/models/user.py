"""User accounts and their investment profile (one-to-one)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import InvestmentHorizon, RiskAppetite, str_enum

if TYPE_CHECKING:
    from app.models.broker import BrokerConnection
    from app.models.portfolio import PortfolioHolding, Transaction
    from app.models.recommendation import Recommendation
    from app.models.refresh_token import RefreshToken


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Deleting a user deletes everything they own (ORM side + ON DELETE CASCADE in DB).
    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    holdings: Mapped[list[PortfolioHolding]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    broker_connections: Mapped[list[BrokerConnection]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class UserProfile(Base):
    """
    Investment profile. user_id is both the primary key and the FK, so a user
    has at most one profile.

    Two layers, so the agent never overwrites what the user told us:
      stated_*            what the user chose in the profile form (agent never writes these)
      risk_appetite /     the EFFECTIVE profile used by the other agents, set by the
      investment_horizon  User Profiling Agent from behaviour + stated preferences
    profile_basis / behavior_metrics / classified_at explain how it was decided.
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Effective profile (nullable until the user fills the form or the agent classifies them).
    risk_appetite: Mapped[RiskAppetite | None] = mapped_column(str_enum(RiskAppetite, "risk_appetite"))
    investment_horizon: Mapped[InvestmentHorizon | None] = mapped_column(
        str_enum(InvestmentHorizon, "investment_horizon")
    )
    # What the user said.
    stated_risk_appetite: Mapped[RiskAppetite | None] = mapped_column(
        str_enum(RiskAppetite, "stated_risk_appetite")
    )
    stated_investment_horizon: Mapped[InvestmentHorizon | None] = mapped_column(
        str_enum(InvestmentHorizon, "stated_investment_horizon")
    )
    goals: Mapped[str | None] = mapped_column(Text)
    monthly_investment_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # How the effective profile was decided, e.g. {"risk": "blended", "horizon": "stated"}.
    profile_basis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    behavior_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="profile")
