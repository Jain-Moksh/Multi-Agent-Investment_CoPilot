"""Point-in-time market data fetched by the Market Agent's polling jobs."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Float, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    # Typical query: "latest snapshots for RELIANCE.NS" -> index on (symbol, fetched_at).
    __table_args__ = (Index("ix_market_snapshots_symbol_fetched_at", "symbol", "fetched_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    change_pct: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str | None] = mapped_column(String(16))  # "yfinance" | "nse" (fallback)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceHistory(Base):
    """
    One daily OHLCV bar per (symbol, trading day). Filled by the market data job
    from the ~30-day yfinance history it already downloads (upserted, so the
    latest values for a day win). Used for moving averages and locally computed RSI.
    """

    __tablename__ = "price_history"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_price_history_symbol_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(16))  # "yfinance"
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompanyFundamentals(Base):
    """
    Latest basic fundamentals per symbol (one row, overwritten on refresh), cached for
    a week because they change slowly. Source: yfinance (primary, free) or Alpha
    Vantage OVERVIEW (fallback). Units are normalised at write time:
    ratios as fractions (roe 0.32 = 32%), percentages named *_pct.
    """

    __tablename__ = "company_fundamentals"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str | None] = mapped_column(String(8))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    pe_ratio: Mapped[float | None] = mapped_column(Float)            # trailing P/E
    forward_pe: Mapped[float | None] = mapped_column(Float)
    price_to_book: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)                 # fraction
    debt_to_equity: Mapped[float | None] = mapped_column(Float)      # ratio (0.5 = debt is half of equity)
    dividend_yield_pct: Mapped[float | None] = mapped_column(Float)
    profit_margin: Mapped[float | None] = mapped_column(Float)       # fraction
    revenue_growth: Mapped[float | None] = mapped_column(Float)      # fraction, year on year
    week52_high: Mapped[float | None] = mapped_column(Float)
    week52_low: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TechnicalIndicator(Base):
    """
    Latest value of one indicator for one symbol (e.g. RSI-14 for RELIANCE.NS).

    One row per (symbol, indicator), overwritten on refresh. It doubles as a
    persistent cache for Alpha Vantage (25 requests/day on the free tier): if
    fetched_at is recent enough, the API is not called again, even after the
    server restarts.
    """

    __tablename__ = "technical_indicators"
    __table_args__ = (UniqueConstraint("symbol", "indicator", name="uq_technical_indicators_symbol_indicator"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    indicator: Mapped[str] = mapped_column(String(32))     # e.g. "RSI_14"
    value: Mapped[float] = mapped_column(Float)
    as_of: Mapped[date] = mapped_column(Date)              # trading day the value refers to
    source: Mapped[str] = mapped_column(String(32))        # e.g. "alphavantage"
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
