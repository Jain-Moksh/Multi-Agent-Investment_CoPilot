"""
Fundamental & Economic Agent: is the company sound, and what is the macro backdrop?

    result = await FundamentalEconomicAgent().analyze("HDFCBANK.NS")

Pure rules, no LLM. Reads (through @enforce_permission("fundamental_economic_agent", "read", ...)):
  - company_fundamentals  P/E, sector, ROE, debt/equity, growth (cached a week; a stale or
                          missing row is refreshed first by the system fundamentals service)
  - news_events           SAFE articles from the last 7 days that mention macro keywords

Macro news: an article counts when its title/description matches a macro theme
(word-boundary keyword match, see MACRO_THEMES), e.g. "RBI", "repo rate", "inflation",
"crude", "budget", "GDP", "rupee", "war". Each company's sector is mapped to the themes
that usually move it (SECTOR_THEMES), so a bank looks at interest rates and inflation,
an IT exporter at the rupee/dollar and global growth, an oil company at crude and wars.
Keyword themes are deliberately simple and coarse (e.g. any "war" headline counts); the
per-article sentiment written by the News Agent refines the picture over time.

Fundamental points (each rule that fires is reported in plain English):
  valuation  loss-making (negative EPS) -0.5 | P/E < 15 +0.4 | 15-30 0 | 30-50 -0.2 | > 50 -0.5
  quality    ROE >= 15% +0.3 | ROE < 8% -0.2
  leverage   debt/equity > 2 -0.3 (not applied to banks/financials: leverage is their business)
  growth     revenue growth > 10% +0.2 | < 0% -0.2
fundamental_part = sum, capped to -1..+1.
macro_part = average sentiment (-1..+1, filled by the News Agent / Marketaux) of the
             sector-relevant macro articles, if at least 3 are scored, else 0.
signal = 0.7 x fundamental_part + 0.3 x macro_part
confidence = 0.2 + 0.4 (fundamentals available) + 0.2 (>= 3 macro articles)
             + 0.2 (>= 3 of them have sentiment scores)
"""

import logging
import re
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from app.agents.base import BaseAgent, now_iso
from app.models import CompanyFundamentals, NewsEvent
from app.models.enums import AssetType, SecurityStatus
from app.schemas.portfolio import normalize_symbol
from app.security.permissions import enforce_permission
from app.services import fundamentals as fundamentals_service

logger = logging.getLogger(__name__)

AGENT_NAME = "fundamental_economic_agent"
MACRO_WINDOW = timedelta(days=7)
MAX_MACRO_ARTICLES = 200
HEADLINES_SHOWN = 8
MIN_SCORED = 3

MACRO_THEMES: dict[str, list[str]] = {
    "interest_rates": ["rbi", "repo rate", "interest rate", "rate hike", "rate cut", "monetary policy", "mpc",
                       "federal reserve", "us fed"],
    "inflation": ["inflation", "cpi", "wpi", "consumer prices"],
    "oil_energy": ["crude", "oil price", "brent", "opec"],
    "fiscal_policy": ["budget", "fiscal", "gst", "government policy", "policy", "tax"],
    "growth": ["gdp", "recession", "slowdown", "economic growth", "iip", "pmi", "unemployment"],
    # Split after live testing: a single "global risk" theme mixed rupee/dollar news (what moves
    # IT exporters) with war headlines (what moves oil), so IT stocks were shown war news.
    "currency": ["rupee", "dollar", "forex", "exchange rate"],
    "geopolitics": ["war", "geopolitical", "tariff", "sanction"],
}
SECTOR_THEMES: dict[str, list[str]] = {
    "Financial Services": ["interest_rates", "inflation", "growth"],
    "Real Estate": ["interest_rates", "growth"],
    "Utilities": ["interest_rates", "fiscal_policy"],
    "Energy": ["oil_energy", "geopolitics", "fiscal_policy"],
    "Technology": ["currency", "growth"],                       # export earnings in dollars
    "Healthcare": ["currency", "fiscal_policy"],                # pharma exports
    "Consumer Defensive": ["inflation", "fiscal_policy"],
    "Consumer Cyclical": ["inflation", "interest_rates", "growth"],
    "Industrials": ["growth", "fiscal_policy", "oil_energy"],
    "Basic Materials": ["growth", "geopolitics", "oil_energy"],  # commodity prices, trade barriers
    "Communication Services": ["growth", "fiscal_policy"],
}

_THEME_PATTERNS = {
    theme: re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")s?\b", re.IGNORECASE)
    for theme, keywords in MACRO_THEMES.items()
}
# Same keywords for the database pre-filter (PostgreSQL ~* with \m / \M word boundaries).
_PG_MACRO_REGEX = r"\m(" + "|".join(re.escape(k) for kws in MACRO_THEMES.values() for k in kws) + r")"


# ======================================================================
# Pure rules
# ======================================================================

def article_themes(text: str) -> list[str]:
    return [theme for theme, pattern in _THEME_PATTERNS.items() if pattern.search(text)]


def fundamental_points(f: CompanyFundamentals | None) -> list[tuple[float, str]]:
    if f is None:
        return []
    points: list[tuple[float, str]] = []
    if f.eps is not None and f.eps < 0:
        points.append((-0.5, f"loss-making (EPS ₹{f.eps:.2f})"))
    elif f.pe_ratio is not None:
        pe = f.pe_ratio
        if pe < 15:
            points.append((0.4, f"low P/E of {pe:.1f} (cheap)"))
        elif pe > 50:
            points.append((-0.5, f"very high P/E of {pe:.1f} (expensive)"))
        elif pe > 30:
            points.append((-0.2, f"high P/E of {pe:.1f}"))
    if f.roe is not None:
        if f.roe >= 0.15:
            points.append((0.3, f"strong ROE of {f.roe * 100:.0f}%"))
        elif f.roe < 0.08:
            points.append((-0.2, f"weak ROE of {f.roe * 100:.0f}%"))
    if f.debt_to_equity is not None and f.sector != "Financial Services" and f.debt_to_equity > 2:
        points.append((-0.3, f"high debt (debt/equity {f.debt_to_equity:.1f})"))
    if f.revenue_growth is not None:
        if f.revenue_growth > 0.10:
            points.append((0.2, f"revenue growing {f.revenue_growth * 100:.0f}% a year"))
        elif f.revenue_growth < 0:
            points.append((-0.2, f"revenue shrinking {abs(f.revenue_growth) * 100:.0f}% a year"))
    return points


def valuation_label(f: CompanyFundamentals | None) -> str:
    if f is None:
        return "unknown"
    if f.eps is not None and f.eps < 0:
        return "loss_making"
    if f.pe_ratio is None:
        return "unknown"
    if f.pe_ratio < 15:
        return "cheap"
    return "fair" if f.pe_ratio <= 30 else "expensive"


def compute_signal(points: list[tuple[float, str]], macro_sentiment: float | None) -> float:
    fundamental_part = max(-1.0, min(1.0, sum(p for p, _ in points)))
    return round(0.7 * fundamental_part + 0.3 * (macro_sentiment or 0.0), 2)


def compute_confidence(has_fundamentals: bool, macro_count: int, scored_count: int) -> float:
    return round(0.2 + (0.4 if has_fundamentals else 0) + (0.2 if macro_count >= MIN_SCORED else 0)
                 + (0.2 if scored_count >= MIN_SCORED else 0), 2)


# ======================================================================
# The agent
# ======================================================================

class FundamentalEconomicAgent(BaseAgent):
    name = AGENT_NAME

    # ---------------- permission-guarded data access ----------------

    @enforce_permission(AGENT_NAME, "read", "company_fundamentals")
    async def _fundamentals(self, symbol: str) -> CompanyFundamentals | None:
        # A missing/stale row is refreshed by the SYSTEM fundamentals service (it owns the
        # cache, like the market data job); the agent itself only reads.
        return await fundamentals_service.refresh_if_stale(symbol, self.session_factory)

    @enforce_permission(AGENT_NAME, "read", "news_events")
    async def _macro_news(self) -> list[NewsEvent]:
        since = datetime.now(UTC) - MACRO_WINDOW
        async with self.session_factory() as db:
            return list(await db.scalars(
                select(NewsEvent)
                .where(NewsEvent.security_status == SecurityStatus.SAFE, NewsEvent.seen_at >= since,
                       or_(NewsEvent.title.op("~*")(_PG_MACRO_REGEX), NewsEvent.description.op("~*")(_PG_MACRO_REGEX)))
                .order_by(NewsEvent.seen_at.desc())
                .limit(MAX_MACRO_ARTICLES)
            ))

    # ---------------- main entry point ----------------

    async def analyze(self, symbol: str) -> dict[str, Any]:
        """Fundamentals + macro context for `symbol`. Every call is logged; errors are logged, then re-raised."""
        symbol = normalize_symbol(AssetType.STOCK, symbol)
        result = self._empty_result(symbol)
        try:
            await self._run(result)
        except Exception as exc:
            result.update(status="error", summary=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            result["rationale"] = result["summary"]
            await self.log_call(
                "analyze",
                {"symbol": symbol},
                {"status": result["status"], "valuation": result["valuation"],
                 "pe_ratio": (result["company"] or {}).get("pe_ratio"), "sector": (result["company"] or {}).get("sector"),
                 "macro_articles": result["macro"].get("article_count"), "macro_sentiment": result["macro"].get(
                     "relevant_avg_sentiment"), "signal": result["signal"], "confidence": result["confidence"],
                 "summary": result["summary"]},
            )
        return result

    @staticmethod
    def _empty_result(symbol: str) -> dict[str, Any]:
        return {
            "agent": AGENT_NAME, "symbol": symbol, "status": "ok",
            "company": None, "valuation": "unknown", "fundamental_reasons": [],
            "macro": {}, "signal": 0.0, "confidence": 0.0,
            "summary": "", "rationale": "", "analyzed_at": now_iso(),
        }

    async def _run(self, r: dict[str, Any]) -> None:
        f = await self._fundamentals(r["symbol"])
        articles = await self._macro_news()

        if f is not None:
            r["company"] = {
                "name": f.name, "sector": f.sector, "industry": f.industry,
                "pe_ratio": _round(f.pe_ratio), "forward_pe": _round(f.forward_pe),
                "price_to_book": _round(f.price_to_book), "eps": _round(f.eps),
                "roe_pct": _round(f.roe, 100), "debt_to_equity": _round(f.debt_to_equity),
                "dividend_yield_pct": _round(f.dividend_yield_pct),
                "revenue_growth_pct": _round(f.revenue_growth, 100), "profit_margin_pct": _round(f.profit_margin, 100),
                "market_cap_crore": round(float(f.market_cap) / 1e7) if f.market_cap is not None else None,
                "week52_high": _round(f.week52_high), "week52_low": _round(f.week52_low),
                "source": f.source, "fetched_at": f.fetched_at.isoformat(),
            }
        points = fundamental_points(f)
        r["valuation"] = valuation_label(f)
        r["fundamental_reasons"] = [reason for _, reason in points]

        relevant = SECTOR_THEMES.get(f.sector, []) if f is not None and f.sector else []
        tagged = [(a, article_themes(f"{a.title} {a.description or ''}")) for a in articles]
        tagged = [(a, themes) for a, themes in tagged if themes]  # SQL pre-filter is broader (no plural/ case nuance)
        theme_counts = {t: sum(t in themes for _, themes in tagged) for t in MACRO_THEMES}
        relevant_articles = [(a, th) for a, th in tagged if not relevant or set(th) & set(relevant)]
        scored = [a.sentiment for a, _ in relevant_articles if a.sentiment is not None]
        all_scored = [a.sentiment for a, _ in tagged if a.sentiment is not None]
        relevant_sentiment = round(statistics.fmean(scored), 3) if len(scored) >= MIN_SCORED else None

        ordered = sorted(tagged, key=lambda item: (not set(item[1]) & set(relevant), -item[0].seen_at.timestamp()))
        r["macro"] = {
            "window_days": MACRO_WINDOW.days,
            "article_count": len(tagged),
            "themes": {t: c for t, c in theme_counts.items() if c},
            "relevant_themes": relevant,
            "relevant_article_count": len(relevant_articles),
            "avg_sentiment": round(statistics.fmean(all_scored), 3) if all_scored else None,
            "relevant_avg_sentiment": relevant_sentiment,
            "headlines": [
                {"news_event_id": a.id, "title": a.title, "themes": th, "sentiment": a.sentiment,
                 "source_domain": a.source_domain, "seen_at": a.seen_at.isoformat()}
                for a, th in ordered[:HEADLINES_SHOWN]
            ],
        }

        if f is None and not tagged:
            r["status"] = "no_data"
        r["signal"] = compute_signal(points, relevant_sentiment)
        r["confidence"] = 0.0 if r["status"] == "no_data" else compute_confidence(
            f is not None, len(relevant_articles), len(scored))
        r["summary"] = self._summary(r)

    @staticmethod
    def _summary(r: dict[str, Any]) -> str:
        c, m = r["company"], r["macro"]
        if r["status"] == "no_data":
            return f"No fundamentals or recent macro news available for {r['symbol']}."
        if c:
            pe = f"P/E {c['pe_ratio']:.1f}" if c["pe_ratio"] is not None else "P/E n/a"
            reasons = "; ".join(r["fundamental_reasons"]) or "no standout strengths or weaknesses"
            company = f"{c['name'] or r['symbol']} ({c['sector'] or 'unknown sector'}, {pe}): {reasons}."
        else:
            company = f"No fundamental data for {r['symbol']}."
        if m["article_count"]:
            top = sorted(m["themes"].items(), key=lambda kv: -kv[1])[:3]
            themes = ", ".join(f"{t.replace('_', ' ')} ({n})" for t, n in top)
            mood = ""
            if m["relevant_avg_sentiment"] is not None:
                tone = "positive" if m["relevant_avg_sentiment"] > 0.1 else (
                    "negative" if m["relevant_avg_sentiment"] < -0.1 else "mixed")
                mood = f"; news relevant to this sector is {tone} on average ({m['relevant_avg_sentiment']:+.2f})"
            macro = f"Macro news, last {m['window_days']} days: {m['article_count']} articles, mostly {themes}{mood}."
        else:
            macro = f"No macro news in the last {m['window_days']} days."
        return f"{company} {macro}"


def _round(value: float | None, factor: float = 1.0) -> float | None:
    return None if value is None else round(value * factor, 2)
