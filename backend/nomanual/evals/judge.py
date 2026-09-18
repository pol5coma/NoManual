"""LLM-as-judge: decides whether an answer matches the reference.

A human with the manual open is the gold standard, but it does not scale: every
change to the chunker means re-reading eighty answers. A model can compare two
texts in seconds, as many times as needed.

It works because comparing is far easier than generating. The judge does not
need to know anything about air conditioners - only whether "two weeks" and
"fourteen days" say the same thing, and whether "six months" does not.

Deliberately NOT given a search tool. If the judge looked the answer up using
our own retrieval, it would inherit our retrieval's failures: when the system
answers badly because it missed the right chunk, the judge would miss it too
and approve. The reference answer in the case file is what breaks that loop.
"""

import logging

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from nomanual.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_model = ChatOpenAI(
    model=settings.chat_model,
    api_key=settings.openai_api_key,
    # A verdict that changes between runs would make every comparison noise.
    temperature=0,
)

_JUDGE_PROMPT = """You grade an answer from an appliance manual assistant \
against a reference answer written from the manual itself.

Say it matches when it conveys the same facts as the reference. Wording,
length and language may differ freely: "every two weeks", "cada dos semanas"
and "every 14 days" all match.

Say it does not match when:
- a number, interval or setting differs from the reference
- it adds a specific claim the reference does not support
- it answers a different question
- it declines to answer while the reference gives one

Extra context around a correct answer is fine. Being vague where the reference
is specific is not."""

_UNANSWERABLE_PROMPT = """You grade whether an appliance manual assistant \
correctly declined to answer.

The manual does not cover this question, so the only correct behaviour is
saying it cannot be found, or handing the question to support.

It matches when the assistant declines, says the manual does not cover it, or
escalates. It does not match when it answers the question anyway - however
plausible the answer sounds. A confident invented answer is the failure this
check exists to catch."""


class Verdict(BaseModel):
    """Structured output of the judge."""

    matches: bool
    reason: str = Field(description="One sentence. What differs, or why it matches.")


async def judge_answer(
    question: str, answer: str, reference: str | None, answerable: bool
) -> Verdict:
    """Grade one answer. Falls back to a failed verdict if the judge errors.

    A judge that crashes must not be read as a pass: an unscored case counted
    as correct would inflate every metric.
    """
    if answerable:
        system = _JUDGE_PROMPT
        human = (
            f"Question: {question}\n\n"
            f"Reference answer: {reference}\n\n"
            f"Assistant's answer: {answer}"
        )
    else:
        system = _UNANSWERABLE_PROMPT
        human = f"Question: {question}\n\nAssistant's answer: {answer}"

    try:
        return await _model.with_structured_output(Verdict).ainvoke(
            [("system", system), ("human", human)]
        )
    except Exception as exc:  # noqa: BLE001 - a broken judge is a failed case
        logger.exception("Judge failed on %r", question)
        return Verdict(matches=False, reason=f"judge error: {type(exc).__name__}")
