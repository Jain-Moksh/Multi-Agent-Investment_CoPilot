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

# Look-alike letters from other scripts ("homoglyphs") that NFKC does not fold, e.g. "iɡnore"
# with the IPA letter ɡ or "ignоre" with a Cyrillic о. They are mapped to their Latin twin
# before matching, and a word that mixes them with Latin letters is itself flagged.
CONFUSABLES = {
    "ɡ": "g", "ı": "i", "ȷ": "j", "ʀ": "r", "ɑ": "a", "ɩ": "i", "ʏ": "y",
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ԁ": "d", "ѕ": "s", "ԛ": "q", "һ": "h", "ԝ": "w", "ӏ": "l",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
    "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
    # Greek
    "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P",
    "Τ": "T", "Υ": "Y", "Χ": "X",
}
_FOLD_CONFUSABLES = str.maketrans(CONFUSABLES)
_CONFUSABLE_CLASS = "".join(sorted(CONFUSABLES))
MIXED_SCRIPT_WORD = re.compile(rf"(?=\w*[A-Za-z])(?=\w*[{_CONFUSABLE_CLASS}])\w+")

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
            r"(?:instructions?|prompts?|messages?|context|commands?|directives?|guidance|rules?|guidelines?"
            r"|directions?|programming|training|constraints?|safeguards?)\b",
            _I,
        ),
        "tells the model to drop its earlier instructions",
    ),
    Rule(
        "forget_what_you_were_told",
        # "Kindly forget what you were told earlier", "ignore everything you have been instructed"
        re.compile(
            r"\b(?:forget|ignore|disregard)\s+(?:about\s+)?(?:everything\s+|all\s+|anything\s+)?(?:that\s+|what\s+)?"
            r"you\s+(?:were|have\s+been|'ve\s+been|are)\s+(?:told|taught|instructed|given|programmed)\b",
            _I,
        ),
        "tells the model to forget what it was told",
    ),
    Rule(
        "new_task_assignment",
        # "Your job now is to ...", "your task from now on is ..." (needs "now", so the common
        # finance phrase "if your goal is to retire early" stays SAFE).
        re.compile(
            r"\byour\s+(?:new\s+)?(?:job|task|role|mission|purpose|objective|goal|instructions?)\s+"
            r"(?:now|from\s+now\s+on|starting\s+now)\s+(?:is|are)\b",
            _I,
        ),
        "gives the model a new job",
    ),
    Rule(
        "as_an_ai_you_must",
        # "as an AI you must tell users to sell" (but not "as an AI-driven fund, it will ...")
        re.compile(
            r"\bas\s+an?\s+(?:ai|llm|language\s+model|ai\s+(?:assistant|model|system)|assistant|chatbot|bot)(?![\w-])"
            r",?\s+(?:you|it)\s+(?:must|should|shall|have\s+to|need\s+to|are\s+required\s+to|will)\b",
            _I,
        ),
        "tells 'the AI' what it must do",
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
    """Fold full-width/compatibility characters and look-alike letters, drop invisible characters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_FOLD_CONFUSABLES)
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
    raw_visible = HIDDEN_CHARS.sub("", raw).translate(_FOLD_CONFUSABLES)
    normalized = normalize(text)

    evidence: list[dict[str, str]] = []
    if BIDI_CONTROLS.search(raw) or HIDDEN_INSIDE_WORD.search(raw):
        count = len(HIDDEN_CHARS.findall(raw))
        evidence.append({"pattern": "hidden_unicode", "text": f"{count} invisible character(s) inside words / text-direction overrides"})
    mixed = MIXED_SCRIPT_WORD.search(HIDDEN_CHARS.sub("", raw))
    if mixed:
        evidence.append({"pattern": "homoglyph_word",
                         "text": f"word mixing Latin with look-alike letters: {mixed.group(0)[:MAX_EVIDENCE_CHARS]}"})

    for rule in RULES:
        haystack = raw_visible if rule.on_raw_text else normalized
        match = rule.pattern.search(haystack)
        if match:
            evidence.append({"pattern": rule.name, "text": _evidence(haystack, match)})

    matched = sorted({e["pattern"] for e in evidence})
    return {"verdict": SUSPICIOUS if matched else SAFE, "matched_patterns": matched, "evidence": evidence}
