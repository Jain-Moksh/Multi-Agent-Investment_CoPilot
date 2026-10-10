"""
Agreement & Confidence module. Every expected number is worked out by hand in the
comments so the formula can be checked on paper. Pure function: no DB, no LLM.
"""

import random

import pytest

from app.agents.confidence_module import compute_agreement, lean_of


def out(signal=None, confidence=1.0, status="ok", **fields):
    o = {"status": status, "confidence": confidence, **fields}
    if signal is not None:
        o["signal"] = signal
    return o


def outputs(news=None, market=None, portfolio=None, fundamental=None, risk="moderate", horizon="medium_term"):
    return {
        "news_agent": news, "market_agent": market, "portfolio_agent": portfolio,
        "fundamental_economic_agent": fundamental,
        "user_profiling_agent": {"risk_appetite": risk, "investment_horizon": horizon, "signal": 0.0,
                                 "confidence": 0.5, "status": "ok"},
    }


# ---------------- the formula ----------------

def test_full_agreement_gives_full_confidence():
    r = compute_agreement(outputs(out(0.5), out(0.5), out(0.5), out(0.5)))
    # every lean = 0.5 -> mean 0.5, sigma 0 -> agreement 1; all confidences 1 -> evidence 1
    assert (r["overall_lean"], r["agreement"], r["evidence"], r["confidence"]) == (0.5, 1.0, 1.0, 1.0)
    assert r["conflicts"] == [] and r["excluded"] == {}


def test_even_split_gives_zero_confidence():
    r = compute_agreement(outputs(out(1.0), out(1.0), out(-1.0), out(-1.0)))
    # weights .25 + .25 bullish vs .20 + .30 bearish (moderate: no bearish boost) -> mean 0
    # every lean is 1 away from the mean -> sigma 1 -> agreement 0 -> confidence 0
    assert (r["overall_lean"], r["agreement"], r["confidence"]) == (0.0, 0.0, 0.0)
    assert len(r["conflicts"]) == 4  # news & market each conflict with portfolio & fundamentals


def test_partial_disagreement():
    r = compute_agreement(outputs(out(0.6), out(0.4), out(0.2), out(-0.2)))
    # mean = (.25*.6 + .25*.4 + .20*.2 + .30*-.2) / 1.0 = 0.23
    # deviations .37, .17, -.03, -.43 -> sigma^2 = .25*.1369 + .25*.0289 + .20*.0009 + .30*.1849 = 0.0971
    # sigma = 0.3116 -> agreement = 0.6884; evidence 1 -> confidence 0.6884
    assert r["overall_lean"] == pytest.approx(0.23, abs=1e-4)
    assert r["agreement"] == pytest.approx(0.6884, abs=1e-4)
    assert r["confidence"] == pytest.approx(0.6884, abs=1e-4)
    # fundamentals at -0.2 (exactly the threshold) opposes all three bullish agents (each >= +0.2)
    assert r["conflicts"] == [
        "News is bullish (+0.60) but Fundamentals is bearish (-0.20).",
        "Market trend is bullish (+0.40) but Fundamentals is bearish (-0.20).",
        "Your portfolio is bullish (+0.20) but Fundamentals is bearish (-0.20).",
    ]


def test_borderline_leans_count_as_conflict():
    r = compute_agreement(outputs(market=out(0.2), fundamental=out(-0.2)))
    assert r["conflicts"] == ["Market trend is bullish (+0.20) but Fundamentals is bearish (-0.20)."]


@pytest.mark.parametrize(
    "risk, expected_lean",
    [
        # news +0.6 (w .25) vs fundamentals -0.6 (w .30 x bearish factor)
        ("conservative", (0.25 * 0.6 - 0.45 * 0.6) / 0.70),    # bearish x1.5 -> -0.1714
        ("moderate", (0.25 * 0.6 - 0.30 * 0.6) / 0.55),        # -0.0545
        ("aggressive", (0.25 * 0.6 - 0.225 * 0.6) / 0.475),    # bearish x0.75 -> +0.0316
    ],
)
def test_risk_appetite_changes_how_loud_bearish_signals_are(risk, expected_lean):
    r = compute_agreement(outputs(news=out(0.6), fundamental=out(-0.6), risk=risk))
    assert r["overall_lean"] == pytest.approx(expected_lean, abs=1e-4)


def test_horizon_shifts_weight_between_technicals_and_fundamentals():
    short = compute_agreement(outputs(market=out(0.8), fundamental=out(-0.2), horizon="short_term"))
    long_ = compute_agreement(outputs(market=out(0.8), fundamental=out(-0.2), horizon="long_term"))
    # short: market .25*1.5=.375, fundamental .30*.75=.225 -> (.3 - .045)/.6 = 0.425
    # long:  market .25*.6=.15,   fundamental .30*1.3=.39  -> (.12 - .078)/.54 = 0.0778
    assert short["overall_lean"] == pytest.approx(0.425, abs=1e-4)
    assert long_["overall_lean"] == pytest.approx(0.0778, abs=1e-4)
    assert short["weights"]["market_agent"] > long_["weights"]["market_agent"]


def test_agent_confidence_scales_its_weight():
    r = compute_agreement(outputs(news=out(1.0, confidence=0.2), market=out(-1.0, confidence=1.0)))
    # news weight .25*.2 = .05, market .25 -> mean (.05 - .25)/.30 = -0.6667
    assert r["overall_lean"] == pytest.approx(-0.6667, abs=1e-4)


# ---------------- missing evidence ----------------

def test_degraded_agents_are_excluded_and_lower_evidence():
    r = compute_agreement(outputs(
        news=out(0.0, confidence=0.0, status="llm_unavailable"),
        market=out(0.5, confidence=0.8), portfolio=out(0.1, confidence=1.0), fundamental=out(0.49, confidence=0.8)))
    assert r["excluded"] == {"news_agent": "status llm_unavailable"}
    assert "news_agent" not in r["leans"]
    # evidence = (.25*.8 + .20*1 + .30*.8) / 1.0 = 0.64   (news counts as 0)
    assert r["evidence"] == pytest.approx(0.64)


def test_single_agent_cannot_be_fully_confident():
    r = compute_agreement(outputs(market=out(0.7, confidence=0.8)))
    assert r["agreement"] == 1.0                       # agrees with itself...
    assert r["confidence"] == pytest.approx(0.2)       # ...but evidence is .25*.8 = 0.2


def test_no_usable_agents():
    r = compute_agreement(outputs(news=out(status="error", confidence=0), market=None))
    assert (r["overall_lean"], r["confidence"], r["conflicts"], r["weights"]) == (0.0, 0.0, [], {})
    assert set(r["excluded"]) == {"news_agent", "market_agent", "portfolio_agent", "fundamental_economic_agent"}


def test_missing_profile_defaults_to_moderate_medium():
    r = compute_agreement({"market_agent": out(0.5)})
    assert r["profile"] == {"risk_appetite": "moderate", "investment_horizon": "medium_term"}


# ---------------- qualitative fallback ----------------

@pytest.mark.parametrize(
    "agent, output, lean",
    [
        ("news_agent", {"sentiment": "negative", "severity": "high"}, -1.0),
        ("news_agent", {"sentiment": "positive", "severity": "medium"}, 0.66),
        ("market_agent", {"trend": "up", "rsi_signal": "overbought"}, 0.2),
        ("market_agent", {"trend": "down", "rsi_signal": "oversold"}, -0.2),
        ("portfolio_agent", {"concentration_risk": "high"}, -0.6),
        ("fundamental_economic_agent", {"valuation": "cheap"}, 0.4),
        ("market_agent", {"signal": 3.0}, 1.0),            # out-of-range signals are clamped
    ],
)
def test_lean_from_qualitative_fields(agent, output, lean):
    assert lean_of(agent, output) == pytest.approx(lean)


# ---------------- user-facing conflicts ----------------

def test_bullish_but_already_concentrated():
    r = compute_agreement(outputs(news=out(0.8), market=out(0.6), fundamental=out(0.5),
                                  portfolio=out(-0.1, concentration_risk="high", position_weight_pct=42.0)))
    assert ("The signals lean bullish, but you already hold a large position (42% of your portfolio): "
            "buying more would increase concentration risk.") in r["conflicts"]


def test_bullish_overbought_conservative():
    r = compute_agreement(outputs(news=out(0.8), market=out(0.4, rsi_signal="overbought"), fundamental=out(0.5),
                                  risk="conservative"))
    assert any("overbought and your profile is conservative" in c for c in r["conflicts"])


def test_accepts_the_whole_run_analysis_result():
    agents = outputs(market=out(0.5))
    assert compute_agreement({"agents": agents, "symbol": "INFY.NS"}) == compute_agreement(agents)


def test_real_live_outputs_from_the_orchestrator_run():
    """The INFY.NS outputs from the Phase 7.1 live run (news had no LLM key)."""
    r = compute_agreement(outputs(
        news=out(0.0, confidence=0.0, status="llm_unavailable"),
        market=out(0.32, confidence=0.8, trend="up", rsi_signal="neutral"),
        portfolio=out(-0.9, confidence=1.0, concentration_risk="high", position_weight_pct=100.0),
        fundamental=out(0.49, confidence=0.8, valuation="cheap"),
        risk="aggressive", horizon="long_term"))
    # weights: market .25*.6*.8=.12; portfolio .20*1*.75(aggressive, bearish)=.15; fundamental .30*1.3*.8=.312
    # mean = (.0384 - .135 + .15288) / .582 = .05628 / .582 = 0.0967
    assert r["overall_lean"] == pytest.approx(0.0967, abs=1e-3)
    assert r["confidence"] < 0.5                                        # strongly split evidence
    assert "Your portfolio is bearish (-0.90) but Fundamentals is bullish (+0.49)." in r["conflicts"]


# ---------------- properties ----------------

def test_outputs_always_in_range():
    rng = random.Random(7)
    for _ in range(500):
        agents = outputs(*[out(rng.uniform(-1, 1), confidence=rng.random()) if rng.random() > 0.2 else None
                           for _ in range(4)],
                         risk=rng.choice(["conservative", "moderate", "aggressive"]),
                         horizon=rng.choice(["short_term", "medium_term", "long_term"]))
        r = compute_agreement(agents)
        assert -1 <= r["overall_lean"] <= 1 and 0 <= r["confidence"] <= 1
        assert r["confidence"] <= r["agreement"] + 1e-9 and r["confidence"] <= r["evidence"] + 1e-9


def test_more_agreement_means_more_confidence():
    spread = [compute_agreement(outputs(out(0.5 + d), out(0.5 - d), out(0.5 + d), out(0.5 - d)))["confidence"]
              for d in (0.0, 0.2, 0.4)]
    assert spread[0] > spread[1] > spread[2]
