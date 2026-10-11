"""Response bodies for GET /news."""

from datetime import datetime

from pydantic import BaseModel


class NewsItemOut(BaseModel):
    id: int
    title: str
    url: str
    description: str | None
    source_name: str | None
    source_domain: str | None
    sentiment: float | None              # -1 .. +1 (Marketaux or the News Agent), null if not scored yet
    affected_sector: str | None
    affected_symbols: list[str]
    seen_at: datetime
    affects_my_portfolio: bool           # an affected symbol is one of the current user's holdings


class NewsPage(BaseModel):
    items: list[NewsItemOut]
    total: int                           # matching SAFE articles (for pagination)
    limit: int
    offset: int
