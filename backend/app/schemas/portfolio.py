"""Request/response bodies for /portfolio endpoints."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AssetType, TransactionSource

# Match the NUMERIC(18, 4) columns in the database.
Quantity = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
Price = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]


def normalize_symbol(asset_type: AssetType, symbol: str) -> str:
    """
    Stocks: upper-case, and default to NSE when no exchange suffix is given
    ("reliance" -> "RELIANCE.NS"). Other assets keep the user's label as typed.
    """
    symbol = symbol.strip()
    if asset_type == AssetType.STOCK:
        symbol = symbol.upper()
        if "." not in symbol:
            symbol += ".NS"
    return symbol


class HoldingCreate(BaseModel):
    asset_type: AssetType
    symbol: str = Field(min_length=1, max_length=60)
    quantity: Quantity
    avg_buy_price: Price

    @model_validator(mode="after")
    def _normalize(self) -> "HoldingCreate":
        self.symbol = normalize_symbol(self.asset_type, self.symbol)
        return self


class HoldingUpdate(BaseModel):
    """
    Only the fields sent are changed. To change a holding's symbol or asset
    type, delete it and add a new one.
    """

    quantity: Quantity | None = None
    avg_buy_price: Price | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "HoldingUpdate":
        if self.quantity is None and self.avg_buy_price is None:
            raise ValueError("send at least one of: quantity, avg_buy_price")
        return self


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: AssetType
    symbol: str
    quantity: float
    avg_buy_price: float
    source: TransactionSource
    added_at: datetime


class ImportReport(BaseModel):
    rows_in_file: int
    inserted: int
    duplicates_skipped: int        # trades already imported (same trade_id)
    non_equity_skipped: int        # F&O / currency / commodity rows
    date_range: tuple[date, date] | None


class ZerodhaLoginUrl(BaseModel):
    login_url: str


class ZerodhaStatus(BaseModel):
    connected: bool
    broker_user_id: str | None = None
    expires_at: datetime | None = None
    last_synced_at: datetime | None = None


class ZerodhaSyncReport(BaseModel):
    holdings_upserted: int
    holdings_removed: int     # Zerodha rows no longer held (sold since last sync)
    skipped: int              # derivatives, intraday, short or zero-quantity positions
