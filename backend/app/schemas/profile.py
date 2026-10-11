"""Request/response bodies for /profile."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import InvestmentHorizon, RiskAppetite


class ProfileOut(BaseModel):
    # What the user chose (editable through PUT /profile)
    stated_risk_appetite: RiskAppetite | None = None
    stated_investment_horizon: InvestmentHorizon | None = None
    goals: str | None = None
    monthly_investment_amount: float | None = None
    # What the User Profiling Agent decided (read-only; the agents use these)
    risk_appetite: RiskAppetite | None = None
    investment_horizon: InvestmentHorizon | None = None
    profile_basis: dict[str, Any] | None = None
    behavior_metrics: dict[str, Any] | None = None
    classified_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileUpdate(BaseModel):
    """
    Only the four user-editable fields; anything else (e.g. risk_appetite) is rejected
    with 422. Fields that are not sent stay unchanged; sending null clears a field.
    """

    model_config = ConfigDict(extra="forbid")

    stated_risk_appetite: RiskAppetite | None = None
    stated_investment_horizon: InvestmentHorizon | None = None
    goals: str | None = Field(default=None, max_length=2000)
    monthly_investment_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one of: stated_risk_appetite, stated_investment_horizon, goals, "
                             "monthly_investment_amount")
        return self
