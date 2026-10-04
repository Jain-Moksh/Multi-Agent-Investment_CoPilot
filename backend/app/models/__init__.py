"""
SQLAlchemy ORM models (PostgreSQL tables).

Every model is imported here so that `Base.metadata` knows about all tables —
Alembic's env.py imports this package to detect schema changes.
"""

from app.models.base import Base
from app.models.broker import BrokerConnection
from app.models.logs import AgentLog, SecurityLog
from app.models.market import CompanyFundamentals, MarketSnapshot, PriceHistory, TechnicalIndicator
from app.models.news import NewsEvent, NewsQuarantine
from app.models.portfolio import PortfolioHolding, Transaction
from app.models.recommendation import Recommendation
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserProfile

__all__ = [
    "Base",
    "User",
    "UserProfile",
    "RefreshToken",
    "PortfolioHolding",
    "Transaction",
    "BrokerConnection",
    "NewsEvent",
    "NewsQuarantine",
    "MarketSnapshot",
    "PriceHistory",
    "TechnicalIndicator",
    "CompanyFundamentals",
    "AgentLog",
    "SecurityLog",
    "Recommendation",
]
