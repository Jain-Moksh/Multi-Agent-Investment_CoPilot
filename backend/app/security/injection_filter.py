"""
Prompt-injection defence, stage 1: fast rule-based scan.

Every piece of untrusted text (news articles, RSS items, PDF text, user chat
messages) passes through scan_text_rules() before it may reach an LLM prompt.

    SAFE        no known injection pattern found
    SUSPICIOUS  at least one pattern matched -> send to the LLM classifier
                (stage 2), which alone may decide BLOCKED

This stage never returns BLOCKED: regexes can't understand intent (a news
story *about* prompt injection would match too), so they only escalate.

Patterns are written to need some context, so ordinary market language
("markets act as if...", "RBI issued new instructions: ...") stays SAFE.
Before matching, text is normalised so simple evasions don't work:
Unicode compatibility forms (full-width letters) are folded, invisible
characters are removed (and their presence is itself flagged), and all
whitespace, including line breaks, is collapsed.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

SAFE = "SAFE"
SUSPICIOUS = "SUSPICIOUS"

# Zero-width and bidirectional-control characters: invisible to a human reader,
# commonly used to hide instructions or split trigger words ("ig​nore").
# They are always removed before matching. They are only *flagged* when clearly
# deliberate: bidi overrides anywhere, or a zero-width character inside a word.
# A lone zero-width space next to a space is a common CMS artefact in real
# headlines (seen in our own stored news), so that alone is not flagged.
HIDDEN_CHARS = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
BIDI_CONTROLS = re.compile("[‪-‮⁦-⁩]")
HIDDEN_INSIDE_WORD = re.compile(r"\w[​-‏⁠-⁤﻿]+\w")

MAX_EVIDENCE_CHARS = 80


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    description: str
    on_raw_text: bool = False  # match the original text (line structure kept) instead of the normalised one


_I = re.IGNORECASE

RULES: list[Rule] = [
    Rule(
        "ignore_previous_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|every\s+|of\s+)*(?:the\s+|your\s+|my\s+)?"
            r"(?:previous|prior|above|earlier|preceding|foregoing|original|system)\s+"
            r"(?:instructions?|prompts?|messages?|context|commands?|directives?)\b",
            _I,
        ),
        "tells the model to drop its earlier instructions",
    ),
    Rule(
        "ignore_the_above",
        re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+of\s+|everything\s+)?(?:the\s+)?above\b", _I),
        "'ignore the above' / 'disregard everything above'",
    ),
    Rule(
        "new_instructions",
        # Only at the start of the text or a sentence, or addressed to "you", so
        # "RBI issued new instructions: banks must..." is not flagged.
        re.compile(
            r"(?:^|[.!?:;]\s+|\n)\s*(?:new|updated|revised|real|actual|additional)\s+instructions?\s*:"
            r"|\byour\s+(?:new|real|true|actual)\s+(?:instructions?|task|goal|objective|role)\s+(?:is|are)\b",
            _I,
        ),
        "introduces replacement instructions",
    ),
    Rule(
        "system_prompt_reference",
        re.compile(
            r"\bsystem\s+prompt\b"
            r"|\b(?:reveal|print|show|repeat|output|leak|display)\s+(?:me\s+)?(?:your|the)\s+"
            r"(?:hidden\s+|initial\s+|original\s+)?(?:instructions|prompt)\b",
            _I,
        ),
        "mentions or tries to extract the system prompt",
    ),
    Rule(
        "role_reassignment",
        re.compile(
            r"\byou\s+are\s+now\s+(?:a|an|the|my|in|no\s+longer|free|dan|unrestricted|jailbroken)\b"
            r"|\bfrom\s+now\s+on,?\s+you\s+(?:are|will|must|should|shall)\b"
            r"|\bact\s+as\s+if\s+you\b"
            r"|\bpretend\s+(?:to\s+be|you\s+are|that\s+you)\b"
            r"|\b(?:developer|jailbreak|god)\s+mode\b",
            _I,
        ),
        "tries to give the model a new identity or mode",
    ),
    Rule(
        "addressed_to_ai",
        # Indirect injection: text planted in an article, speaking to the AI that reads it.
        re.compile(
            r"\b(?:ai|llm|language\s+model|assistant|chatbot|bot|model|agent)s?\s+"
            r"(?:reading|processing|summari[sz]ing|analy[sz]ing|parsing|scanning)\s+this\b"
            r"|\bif\s+you\s+are\s+an?\s+(?:ai|llm|language\s+model|assistant|chatbot|bot)\b"
            r"|\bnote\s+to\s+(?:the\s+)?(?:ai|llm|assistant|model|agent)\b",
            _I,
        ),
        "text that speaks directly to an AI reading it",
    ),
    Rule(
        "concealment_instruction",
        re.compile(
            r"\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|mention|reveal|disclose)\s+(?:this\s+to\s+)?"
            r"(?:the\s+)?(?:user|users|anyone|human)\b",
            _I,
        ),
        "asks the model to hide something from the user",
    ),
    Rule(
        "fake_role_marker",
        # "SYSTEM:" / "ASSISTANT:" in capitals anywhere, or any-case role labels at a line start.
        re.compile(
            r"\b(?:SYSTEM|ASSISTANT|DEVELOPER)\s*:"
            r"|(?im:^[ \t>*#\[(]*(?:system|assistant|developer|user)[\])]*[ \t]*:)",
        ),
        "fake chat-role label inside content",
        on_raw_text=True,
    ),
    Rule(
        "chat_template_token",
        re.compile(
            r"<\|\s*(?:im_start|im_end|system|user|assistant|endoftext|eot_id|start_header_id)\s*\|>"
            r"|\[/?INST\]|<</?SYS>>|</?(?:system|assistant)>|###\s*(?:instruction|system)\b",
            _I,
        ),
        "special tokens from LLM chat formats",
    ),
    Rule(
        "breakout_characters",
        re.compile(
            r"([^\w\s])\1{7,}"                 # the same symbol 8+ times: ======== ######## }}}}}}}}
            r"|```"                            # code fence
            r"|[\]}>)\"'`]{2,}\s*[\[{<]"       # closing then reopening delimiters: "}] {  or  ]]> <
            r"|[\]}>)\"'`]{5,}",               # long runs of closing delimiters: "}]}}"
        ),
        "unusual runs of special characters used to break out of a quoted context",
        on_raw_text=True,
    ),
]


def normalize(text: str) -> str:
    """Fold full-width/compatibility characters, drop invisible characters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = HIDDEN_CHARS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _evidence(text: str, match: re.Match[str]) -> str:
    snippet = match.group(0).strip() or text[max(0, match.start() - 10) : match.end() + 10]
    snippet = re.sub(r"\s+", " ", snippet)
    return snippet[:MAX_EVIDENCE_CHARS]


def scan_text_rules(text: str | None) -> dict[str, Any]:
    """
    Rule-based injection scan.

    Returns {
        "verdict": "SAFE" | "SUSPICIOUS",
        "matched_patterns": ["ignore_previous_instructions", ...],   # rule names, sorted
        "evidence": [{"pattern": name, "text": "matched text"}, ...], # for logs / LLM stage
    }
    """
    if not text:
        return {"verdict": SAFE, "matched_patterns": [], "evidence": []}

    raw = unicodedata.normalize("NFKC", text)
    raw_visible = HIDDEN_CHARS.sub("", raw)
    normalized = normalize(text)

    evidence: list[dict[str, str]] = []
    if BIDI_CONTROLS.search(raw) or HIDDEN_INSIDE_WORD.search(raw):
        count = len(HIDDEN_CHARS.findall(raw))
        evidence.append({"pattern": "hidden_unicode", "text": f"{count} invisible character(s) inside words / text-direction overrides"})

    for rule in RULES:
        haystack = raw_visible if rule.on_raw_text else normalized
        match = rule.pattern.search(haystack)
        if match:
            evidence.append({"pattern": rule.name, "text": _evidence(haystack, match)})

    matched = sorted({e["pattern"] for e in evidence})
    return {"verdict": SUSPICIOUS if matched else SAFE, "matched_patterns": matched, "evidence": evidence}
