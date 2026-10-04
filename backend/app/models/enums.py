"""
Enumerations used by the ORM models.

They are stored as VARCHAR columns with a CHECK constraint (not native
PostgreSQL ENUM types), which keeps Alembic migrations simple: adding a new
value only means changing a CHECK constraint, not altering a database type.
"""

import enum

from sqlalchemy import Enum as SAEnum


class RiskAppetite(str, enum.Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class InvestmentHorizon(str, enum.Enum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class AssetType(str, enum.Enum):
    STOCK = "stock"
    MUTUAL_FUND = "mutual_fund"
    FD = "fd"
    GOLD = "gold"
    PROPERTY = "property"


class TransactionAction(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class TransactionSource(str, enum.Enum):
    MANUAL = "manual"
    TRADEBOOK_UPLOAD = "tradebook_upload"
    KITE_SYNC = "kite_sync"


class SecurityStatus(str, enum.Enum):
    """Verdict of the prompt-injection scanner for a piece of content."""

    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    BLOCKED = "blocked"


class SecurityEventType(str, enum.Enum):
    PROMPT_INJECTION = "prompt_injection"
    AGENT_HIJACK = "agent_hijack"
    RAG_POISON = "rag_poison"


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(str, enum.Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


def str_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """
    Column type for a Python enum stored as VARCHAR + CHECK constraint.

    `values_callable` makes the database store the lowercase *values*
    ("buy") rather than the member names ("BUY").
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )
