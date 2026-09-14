"""Cheap checks on the question, before anything is spent on it.

Everything here is deterministic and runs in microseconds. The point is to
reject obvious junk without paying for the router's model call, not to be
clever: anything requiring judgement belongs in the router.

Note what this does NOT protect against. Chunks come from PDFs uploaded by
anonymous users and go straight into the answering prompt, so the real
injection surface is the document, not the question. A manual carrying
"ignore previous instructions" in white-on-white text passes every check here,
and `verify` approves it because its chunk id genuinely was retrieved. That is
handled separately, and leans on manual.source and tenant.verified.
"""

import re
from enum import StrEnum

# Deliberately tiny: "E5" is a complete question. Someone staring at a
# blinking code types exactly that, and it is one of the cases we most want
# to answer.
MIN_QUESTION_CHARS = 2
# Nobody types this much to ask about a washing machine. They do to burn tokens.
MAX_QUESTION_CHARS = 2000
MIN_LETTER_RATIO = 0.4

# Blunt on purpose. These catch copy-pasted jailbreak attempts, not a
# determined attacker - for that you need a model trained on it. The value is
# that they cost nothing and remove the noise floor.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
        r"\bdisregard\s+(all\s+)?(previous|prior|above)\b",
        r"\b(olvida|ignora)\s+(las\s+)?instrucciones\b",
        # Role markers: a question has no reason to contain a chat turn.
        r"^\s*(system|assistant|developer)\s*:",
        r"<\|.*?\|>",
        r"\byou\s+are\s+now\b",
        r"\bact\s+as\s+(an?\s+)?(unrestricted|different)\b",
        r"\breveal\s+(your|the)\s+(system\s+)?prompt\b",
    )
]


class Rejection(StrEnum):
    """Why a question was not worth processing."""

    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    NOT_TEXT = "not_text"
    INJECTION = "injection"


REJECTION_MESSAGES = {
    Rejection.TOO_SHORT: (
        "That is too short to work with. Describe what your appliance is doing."
    ),
    Rejection.TOO_LONG: (
        "That is too long. Ask one question about your appliance at a time."
    ),
    Rejection.NOT_TEXT: (
        "I could not read that as a question. Try describing the problem in words."
    ),
    Rejection.INJECTION: ("I can only answer questions about appliance manuals."),
}


def prescreen(question: str) -> Rejection | None:
    """Return why the question should be rejected, or None to let it through."""
    stripped = question.strip()

    if len(stripped) < MIN_QUESTION_CHARS:
        return Rejection.TOO_SHORT

    if len(stripped) > MAX_QUESTION_CHARS:
        return Rejection.TOO_LONG

    # Control characters and symbol soup: the same idea as the ingestion
    # quality filter, applied to what the user sends.
    letters = sum(1 for c in stripped if c.isalpha())
    if letters / len(stripped) < MIN_LETTER_RATIO:
        return Rejection.NOT_TEXT

    if any(pattern.search(stripped) for pattern in _INJECTION_PATTERNS):
        return Rejection.INJECTION

    return None
