"""Final Buy/Hold/Sell output of the Recommendation Agent."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import Decision, str_enum

if TYPE_CHECKING:
    from app.models.user import User


class Recommendation(Base):
    """
    One recommendation. Besides the decision and explanation it keeps everything the
    decision was computed from (overall_lean + `details`: per-agent leans, weights,
    statuses, conflicts, thresholds), so any recommendation can be audited later and
    the explainability phase (SHAP / LIME) has the exact numeric inputs.
    """

    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint("confidence_score BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("overall_lean BETWEEN -1 AND 1", name="overall_lean_range"),
        Index("ix_recommendations_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(64))
    decision: Mapped[Decision] = mapped_column(str_enum(Decision, "decision"))
    confidence_score: Mapped[float] = mapped_column(Float)  # 0.0 - 1.0, from the Agreement module
    overall_lean: Mapped[float | None] = mapped_column(Float)  # -1 bearish .. +1 bullish
    explanation: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="recommendations")
