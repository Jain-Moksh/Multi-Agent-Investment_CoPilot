"""
Agent Agreement & Confidence module: turn the five agents' outputs into one lean,
a confidence that reflects how much they AGREE, and the conflicts worth showing.

    agreement = compute_agreement(analysis["agents"])     # or the whole run_analysis() result
    agreement["overall_lean"], agreement["confidence"], agreement["conflicts"]

Pure calculation: no LLM, no database, fully deterministic (same input -> same output),
so the decision is reproducible and explainable to a panel / via SHAP later.

------------------------------------------------------------------------------
1. LEANS  (-1 bearish .. +1 bullish), one per DIRECTIONAL agent
------------------------------------------------------------------------------
Each agent already computes a numeric `signal` from documented rules (see its module);
that is its lean. If an output has no signal (e.g. an older format), the lean is derived
from its qualitative fields with the same rules (FALLBACK_* tables below):
  news_agent                  sentiment x severity   (positive/high = +1.0)
  market_agent                trend +-0.5, RSI overbought -0.3 / oversold +0.3
  portfolio_agent             concentration: none/low +0.1, medium -0.2, high -0.6
                              (already concentrated = cautious about buying more)
  fundamental_economic_agent  valuation: cheap +0.4, fair 0, expensive -0.3, loss-making -0.5
The user_profiling_agent is NOT directional; it changes the weights (step 2).
Agents whose output is degraded (error, timeout, no data, LLM unavailable, ...) or whose
confidence is 0 are EXCLUDED and listed in `excluded`, so a missing agent's 0 is never
mistaken for a "neutral" vote.

------------------------------------------------------------------------------
2. WEIGHTS
------------------------------------------------------------------------------
  w_i = BASE_WEIGHT_i x horizon_factor_i x confidence_i x bearish_factor (only if lean_i < 0)
  BASE_WEIGHT:      news 0.25, market 0.25, portfolio 0.20, fundamental 0.30
  horizon_factor:   short-term  -> market x1.5, fundamental x0.75   (price action matters more)
                    long-term   -> market x0.6, fundamental x1.3    (business quality matters more)
  bearish_factor:   conservative x1.5, moderate x1.0, aggressive x0.75
                    (a cautious investor should hear warnings louder)
  (Profile from the User Profiling Agent; moderate / medium-term if it is missing.)

------------------------------------------------------------------------------
3. OVERALL LEAN = weighted mean        L = sum(w_i * lean_i) / sum(w_i)
------------------------------------------------------------------------------

------------------------------------------------------------------------------
4. CONFIDENCE = agreement x evidence                (both 0..1)
------------------------------------------------------------------------------
  agreement = 1 - sigma, where sigma = weighted standard deviation of the leans:
        sigma = sqrt( sum(w_i * (lean_i - L)^2) / sum(w_i) )
     Leans live in [-1, 1], so sigma is at most 1 (half the weight at -1, half at +1).
     All agents saying the same thing -> sigma 0 -> agreement 1 (high confidence);
     agents split between bullish and bearish -> sigma near 1 -> agreement near 0.
  evidence = sum(BASE_i x confidence_i) / sum(BASE_i) over ALL directional agents
     (excluded agents count as 0). Without this, a single agent would "agree with
     itself" and get confidence 1.0; with it, missing or weak evidence lowers confidence.

------------------------------------------------------------------------------
5. CONFLICTS (surfaced to the user)
------------------------------------------------------------------------------
  - any two included agents leaning in opposite directions, each with |lean| >= 0.2
  - overall bullish (L >= 0.2) while the portfolio is already highly concentrated
  - overall bullish while the profile is conservative and the market reads "overbought"
"""

import math
from itertools import combinations
from typing import Any

DIRECTIONAL_AGENTS = ("news_agent", "market_agent", "portfolio_agent", "fundamental_economic_agent")
PROFILE_AGENT = "user_profiling_agent"

BASE_WEIGHT = {"news_agent": 0.25, "market_agent": 0.25, "portfolio_agent": 0.20, "fundamental_economic_agent": 0.30}
HORIZON_FACTOR = {
    "short_term": {"market_agent": 1.5, "fundamental_economic_agent": 0.75},
    "medium_term": {},
    "long_term": {"market_agent": 0.6, "fundamental_economic_agent": 1.3},
}
BEARISH_FACTOR = {"conservative": 1.5, "moderate": 1.0, "aggressive": 0.75}
DEFAULT_RISK, DEFAULT_HORIZON = "moderate", "medium_term"

# Statuses meaning "this agent has no usable opinion" (its signal is a placeholder 0).
DEGRADED_STATUSES = {"error", "timeout", "no_data", "no_news", "llm_unavailable", "invalid_llm_output",
                     "insufficient_history"}
CONFLICT_MIN_LEAN = 0.2

LABELS = {"news_agent": "News", "market_agent": "Market trend", "portfolio_agent": "Your portfolio",
          "fundamental_economic_agent": "Fundamentals"}

# Fallback mappings (used only when an output carries no numeric signal).
FALLBACK_NEWS = {"positive": 1, "negative": -1, "neutral": 0}
FALLBACK_SEVERITY = {"low": 0.33, "medium": 0.66, "high": 1.0}
FALLBACK_TREND = {"up": 0.5, "down": -0.5, "flat": 0.0}
FALLBACK_RSI = {"overbought": -0.3, "oversold": 0.3, "neutral": 0.0}
FALLBACK_CONCENTRATION = {"none": 0.1, "low": 0.1, "medium": -0.2, "high": -0.6}
FALLBACK_VALUATION = {"cheap": 0.4, "fair": 0.0, "expensive": -0.3, "loss_making": -0.5, "unknown": 0.0}


def _clamp(x: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def lean_of(agent: str, output: dict[str, Any]) -> float:
    """The agent's lean: its own `signal` if present, else the fallback mapping."""
    if isinstance(output.get("signal"), (int, float)):
        return _clamp(float(output["signal"]))
    if agent == "news_agent":
        return FALLBACK_NEWS.get(output.get("sentiment"), 0) * FALLBACK_SEVERITY.get(output.get("severity"), 0.33)
    if agent == "market_agent":
        return _clamp(FALLBACK_TREND.get(output.get("trend"), 0) + FALLBACK_RSI.get(output.get("rsi_signal"), 0))
    if agent == "portfolio_agent":
        return FALLBACK_CONCENTRATION.get(output.get("concentration_risk"), 0.0)
    if agent == "fundamental_economic_agent":
        return FALLBACK_VALUATION.get(output.get("valuation"), 0.0)
    return 0.0


def _direction(lean: float) -> str:
    return "bullish" if lean > 0 else "bearish"


def compute_agreement(agent_outputs: dict[str, Any]) -> dict[str, Any]:
    """
    agent_outputs: {agent_name: output dict} as in run_analysis()["agents"]
                   (the whole run_analysis() result is accepted too).
    Returns {
        "overall_lean": float -1..1, "confidence": float 0..1, "conflicts": [str, ...],
        # explanation of how it was computed:
        "agreement": float, "evidence": float, "leans": {agent: lean}, "weights": {agent: share of weight},
        "excluded": {agent: reason}, "profile": {"risk_appetite", "investment_horizon"},
    }
    """
    if "agents" in agent_outputs and isinstance(agent_outputs["agents"], dict):
        agent_outputs = agent_outputs["agents"]

    # ---- profile (non-directional) ----
    profile_out = agent_outputs.get(PROFILE_AGENT) or {}
    risk = profile_out.get("risk_appetite") or DEFAULT_RISK
    horizon = profile_out.get("investment_horizon") or DEFAULT_HORIZON
    bearish_factor = BEARISH_FACTOR.get(risk, 1.0)
    horizon_factor = HORIZON_FACTOR.get(horizon, {})

    # ---- leans + weights ----
    leans: dict[str, float] = {}
    raw_weights: dict[str, float] = {}
    excluded: dict[str, str] = {}
    for agent in DIRECTIONAL_AGENTS:
        out = agent_outputs.get(agent)
        if not out:
            excluded[agent] = "no output"
            continue
        status, confidence = out.get("status"), float(out.get("confidence") or 0.0)
        if status in DEGRADED_STATUSES:
            excluded[agent] = f"status {status}"
            continue
        if confidence <= 0:
            excluded[agent] = "confidence 0"
            continue
        lean = lean_of(agent, out)
        weight = BASE_WEIGHT[agent] * horizon_factor.get(agent, 1.0) * confidence
        if lean < 0:
            weight *= bearish_factor
        leans[agent], raw_weights[agent] = round(lean, 4), weight

    total = sum(raw_weights.values())

    # ---- (a) overall lean: weighted mean ----
    overall = sum(raw_weights[a] * leans[a] for a in leans) / total if total else 0.0

    # ---- (b) confidence = agreement x evidence ----
    if total:
        sigma = math.sqrt(sum(raw_weights[a] * (leans[a] - overall) ** 2 for a in leans) / total)
        agreement = 1 - min(sigma, 1.0)
    else:
        agreement = 0.0
    evidence = sum(BASE_WEIGHT[a] * float((agent_outputs.get(a) or {}).get("confidence") or 0)
                   for a in leans) / sum(BASE_WEIGHT.values())
    confidence = _clamp(agreement * evidence, 0.0, 1.0)

    # ---- (c) conflicts ----
    conflicts: list[str] = []
    for a, b in combinations(leans, 2):
        la, lb = leans[a], leans[b]
        if abs(la) >= CONFLICT_MIN_LEAN and abs(lb) >= CONFLICT_MIN_LEAN and (la > 0) != (lb > 0):
            conflicts.append(f"{LABELS[a]} is {_direction(la)} ({la:+.2f}) but {LABELS[b]} is "
                             f"{_direction(lb)} ({lb:+.2f}).")
    portfolio = agent_outputs.get("portfolio_agent") or {}
    if overall >= CONFLICT_MIN_LEAN and portfolio.get("concentration_risk") == "high":
        weight_pct = portfolio.get("position_weight_pct")
        share = f" ({weight_pct:.0f}% of your portfolio)" if isinstance(weight_pct, (int, float)) else ""
        conflicts.append(f"The signals lean bullish, but you already hold a large position{share}: "
                         "buying more would increase concentration risk.")
    market = agent_outputs.get("market_agent") or {}
    if overall >= CONFLICT_MIN_LEAN and risk == "conservative" and market.get("rsi_signal") == "overbought":
        conflicts.append("The signals lean bullish, but the stock looks overbought and your profile is "
                         "conservative: consider waiting for a pullback.")

    return {
        "overall_lean": round(_clamp(overall), 4),
        "confidence": round(confidence, 4),
        "conflicts": conflicts,
        "agreement": round(agreement, 4),
        "evidence": round(evidence, 4),
        "leans": leans,
        "weights": {a: round(w / total, 4) for a, w in raw_weights.items()} if total else {},
        "excluded": excluded,
        "profile": {"risk_appetite": risk, "investment_horizon": horizon},
    }
