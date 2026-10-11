import re
from typing import Any

CLARIFY_PREFIX = "Happy to give you a clear call on"
STRONG_CONFIDENCE = 0.7
STARTER_LEAN = 0.15
CONCENTRATION_LIMIT = 0.25

_SELL = re.compile(
    r"\b(sell|selling|exit|exiting|book (?:my |the )?profits?|get out of|offload|dump|cut (?:my )?loss(?:es)?|"
    r"reduce (?:my )?(?:position|holding|stake))\b"
)
_BUY = re.compile(
    r"\b(buy|buying|purchase|invest|investing|accumulate|"
    r"add more|add to my|start a position|go long on|enter)\b"
)
_HOLD = re.compile(r"\b(should i (?:hold|keep)|keep holding|hold on to|continue holding|stay invested)\b")
_ADVICE = re.compile(
    r"\b(should i (?:go for|get|take|pick)|worth buying|worth investing|good (?:buy|investment|stock to buy)|"
    r"recommend (?:buying|it)|is it a good time to)\b"
)

_UNITS = {"k": 1e3, "thousand": 1e3, "l": 1e5, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5,
          "cr": 1e7, "crore": 1e7, "crores": 1e7}
_UNIT = r"(k|thousand|lakhs?|lacs?|l|crores?|cr)"
_AMOUNT_PATTERNS = (
    re.compile(r"(?:₹|\brs\.?|\binr)\s*([\d,]+(?:\.\d+)?)\s*" + _UNIT + r"?\b"),
    re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)\s*" + _UNIT + r"\b"),
    re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)\s*(?:rupees|rs\b|inr\b)"),
)
_SHARES = re.compile(r"(?<![\w.])(\d[\d,]*)\s*(?:shares?|qty|quantity|units)\b")
_BARE = re.compile(r"(?<![\w.₹])(\d{1,3}(?:,\d{2,3})+|\d{4,})(?![\w%]|[.,]\d)")

_LONG = re.compile(r"long[\s-]?term|long run|retire|wealth creation|for (?:many )?years|next decade")
_SHORT = re.compile(r"short[\s-]?term|intraday|swing trad|quick (?:gain|profit|return)s?|few (?:weeks|days)|trading")
_MEDIUM = re.compile(r"medium[\s-]?term|mid[\s-]?term")
_PERIOD = re.compile(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|months?|weeks?|days?)")
_AGREE = re.compile(r"^\s*(same|yes|yeah|yep|ok|okay|fine|sure|that works|go ahead)\b")


def trade_intent(message: str) -> str | None:
    text = message.lower()
    if _SELL.search(text):
        return "sell"
    if _HOLD.search(text):
        return "hold"
    if _BUY.search(text) or _ADVICE.search(text):
        return "buy"
    return None


def _number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def parse_amount(text: str) -> dict[str, float] | None:
    lower = text.lower()
    for pattern in _AMOUNT_PATTERNS:
        match = pattern.search(lower)
        if match:
            groups = match.groups()
            value = _number(groups[0])
            unit = groups[1] if len(groups) > 1 else None
            if value:
                return {"rupees": value * _UNITS.get(unit or "", 1)}
    shares = _SHARES.search(lower)
    if shares and (value := _number(shares.group(1))):
        return {"shares": value}
    for match in _BARE.finditer(lower):
        value = _number(match.group(1))
        if value and not 1900 <= value <= 2100:
            return {"rupees": value}
    return None


def parse_horizon(text: str) -> str | None:
    lower = text.lower()
    if _LONG.search(lower):
        return "long_term"
    if _SHORT.search(lower):
        return "short_term"
    if _MEDIUM.search(lower):
        return "medium_term"
    match = _PERIOD.search(lower)
    if match:
        value, unit = float(match.group(1)), match.group(2)
        if unit.startswith("y"):
            months = value * 12
        elif unit.startswith("m"):
            months = value
        elif unit.startswith("w"):
            months = value / 4.3
        else:
            months = value / 30
        return "long_term" if months >= 36 else "medium_term" if months >= 12 else "short_term"
    if re.search(r"\b(?:a|one) year\b", lower):
        return "medium_term"
    return None


def agrees(text: str) -> bool:
    return bool(_AGREE.match(text.lower()))


def horizon_words(horizon: str | None) -> str:
    return (horizon or "").replace("_", " ") or "not set"


def clarify_text(name: str, symbol: str, missing: list[str], profile_horizon: str | None) -> str:
    plural = "s" if len(missing) > 1 else ""
    lines = [f"{CLARIFY_PREFIX} {name} ({symbol}). Quick question{plural} first so I can size it for you:", ""]
    number = 1
    if "amount" in missing:
        lines.append(f"{number}. How much are you planning to invest? An amount like ₹50,000, or a number of shares.")
        number += 1
    if "horizon" in missing:
        question = f"{number}. Is this for the short term (under a year), medium term (1-3 years) or long term (3+ years)?"
        if profile_horizon:
            question += f' Your profile says {horizon_words(profile_horizon)}; reply "same" to use that.'
        lines.append(question)
    return "\n".join(lines)


def pending_symbol(history: list[tuple[str, str]]) -> str | None:
    for role, content in reversed(history):
        if role != "assistant":
            continue
        match = re.match(rf"{CLARIFY_PREFIX} .*?\(([A-Z0-9&.\-]+)\)", content)
        return match.group(1) if match else None
    return None


def question_before_clarify(history: list[tuple[str, str]]) -> str:
    for index in range(len(history) - 1, -1, -1):
        role, content = history[index]
        if role == "assistant" and content.startswith(CLARIFY_PREFIX):
            for earlier_role, earlier in reversed(history[:index]):
                if earlier_role == "user":
                    return earlier
            return ""
    return ""


def verdict(label: str, confidence: float, lean: float, held: bool, action: str) -> tuple[str, float]:
    strong = confidence >= STRONG_CONFIDENCE
    if label == "Buy":
        if held and action != "buy":
            return "Keep holding (positive outlook)", 0.0
        if held:
            return ("Add more" if strong else "Add in small steps"), (1.0 if strong else 0.4)
        return ("Buy" if strong else "Buy in small steps"), (1.0 if strong else 0.4)
    if label == "Hold":
        if held:
            return ("Hold, don't add more right now" if action == "buy" else "Hold"), 0.0
        if lean > STARTER_LEAN:
            return "Hold off for now (a small starter position at most)", 0.15
        return "Hold off, don't buy right now", 0.0
    if held:
        return ("Sell" if strong else "Reduce your position"), 0.0
    return "Avoid for now", 0.0


def round_rupees(value: float) -> int:
    step = 500 if value >= 5000 else 100
    return int(max(step, round(value / step) * step))


def money(value: float) -> str:
    number = int(round(value))
    digits = str(abs(number))
    if len(digits) > 3:
        head = ",".join(re.findall(r"\d{1,2}", digits[:-3][::-1]))[::-1]
        digits = f"{head},{digits[-3:]}"
    return f"{'-' if number < 0 else ''}₹{digits}"


def sizing(plan: dict[str, float] | None, price: float | None, fraction: float,
           portfolio_value: float) -> dict[str, Any]:
    result: dict[str, Any] = {"plan_rupees": None, "now_rupees": None, "text": None, "concentration_pct": None}
    if not plan:
        return result
    rupees = plan.get("rupees")
    if rupees is None and plan.get("shares") and price:
        rupees = plan["shares"] * price
    if rupees is None:
        result["text"] = (f"Of the {plan['shares']:g} shares you mentioned, start with about "
                          f"{max(1, round(plan['shares'] * fraction)):g}." if fraction else None)
        return result
    result["plan_rupees"] = round(rupees)
    if portfolio_value > 0:
        result["concentration_pct"] = round(rupees / (portfolio_value + rupees) * 100, 1)
    if fraction <= 0:
        return result
    if fraction >= 1:
        first = round_rupees(rupees / 2)
        result["now_rupees"] = first
        result["text"] = (f"Invest your {money(rupees)} in two parts: about {money(first)} now and the remaining "
                          f"{money(max(0, rupees - first))} over the next 2-4 weeks.")
    else:
        now = min(round_rupees(rupees * fraction), round(rupees))
        result["now_rupees"] = now
        result["text"] = (f"Start with about {money(now)} of your {money(rupees)} now. Keep the remaining "
                          f"{money(max(0, rupees - now))} aside and add it only if the outlook improves, "
                          f"for example after the next quarterly results.")
    return result


def first_sentence(text: str | None) -> str:
    if not text:
        return ""
    return re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip(), maxsplit=1)[0]


REFUSAL_HINTS = re.compile(
    r"(can(?:no|')t (?:give|provide|offer|make)|unable to (?:give|provide)|not able to (?:give|provide)|"
    r"consult (?:a|your) (?:financial|registered)|financial advis[eo]r|recommendation (?:feature|section))", re.I
)


def looks_like_refusal(text: str) -> bool:
    return bool(REFUSAL_HINTS.search(text))
