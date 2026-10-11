"""
The user's investment profile (login required).

GET /profile   what the user stated + what the User Profiling Agent decided
PUT /profile   update only the four user-editable fields (stated_risk_appetite,
               stated_investment_horizon, goals, monthly_investment_amount);
               the row is created if the user has none yet.

The effective risk_appetite / investment_horizon are never set here: the User
Profiling Agent recomputes them (from trades + these stated values) on its next run,
e.g. the next recommendation.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User, UserProfile
from app.schemas.profile import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


def _out(profile: UserProfile | None) -> ProfileOut:
    if profile is None:
        return ProfileOut()
    return ProfileOut(
        stated_risk_appetite=profile.stated_risk_appetite,
        stated_investment_horizon=profile.stated_investment_horizon,
        goals=profile.goals,
        monthly_investment_amount=(float(profile.monthly_investment_amount)
                                   if profile.monthly_investment_amount is not None else None),
        risk_appetite=profile.risk_appetite,
        investment_horizon=profile.investment_horizon,
        profile_basis=profile.profile_basis,
        behavior_metrics=profile.behavior_metrics,
        classified_at=profile.classified_at,
        updated_at=profile.updated_at,
    )


@router.get("", response_model=ProfileOut)
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """All fields are null until the user saves the form or the agent classifies them."""
    return _out(await db.get(UserProfile, user.id))


@router.put("", response_model=ProfileOut)
async def update_profile(body: ProfileUpdate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Fields not sent stay unchanged; null clears a field. Other fields -> 422."""
    profile = await db.get(UserProfile, user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return _out(profile)
