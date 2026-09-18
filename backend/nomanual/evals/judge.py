"""LLM-as-judge: decides whether an answer matches the reference.

A human with the manual open is the gold standard, but it does not scale: every
change to the chunker means re-reading eighty answers. A model can compare two
texts in seconds, as many times as needed.

It works because comparing is far easier than generating. The judge does not
need to know anything about air conditioners - only whether "two weeks" and
"fourteen days" say the same thing, and whether "six months" does not.

The judge reads the manual text behind the case, but is never given a search
tool. Two reasons. Looking answers up through our own retrieval would inherit
its failures: when the system answers badly because it missed the right chunk,
the judge would miss it too and approve. And a measuring instrument should be
predictable before it is clever - every decision an agent makes is another
chance for the same case to be graded differently on two runs.

That mattered here. Before the source text was passed in, the prompt both
penalised "adds a claim the reference does not support" and allowed "extra
context is fine". The contradiction let the model pick a rule, and it picked
differently on consecutive runs: the same answer to the same question was
graded correct one day and incorrect the next. With the source text, the two
questions separate cleanly - does it cover the reference, and does it claim
anything the manual does not say.
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

_JUDGE_PROMPT = """You grade an assistant's answer about a household appliance.

You are given three things: a reference answer written from the manual, the \
assistant's answer, and the manual text those pages contain.

Judge two things separately.

COVERS: does the answer convey the facts of the reference? Wording, length and
language may differ freely - "every two weeks", "cada dos semanas" and "every
14 days" all cover the same fact. It does not cover when a number, interval or
setting contradicts the reference, when it answers a different question, or
when it declines while the reference gives an answer.

INVENTS: does the answer state anything the manual text does not support?
Detail the reference omits is fine as long as the manual text backs it - a
fuller answer is a better answer. Only count a claim as invented when the
manual text does not support it.

Judge the answer against the REFERENCE for coverage, never against everything
the manual happens to say. An answer that covers the reference is complete,
even if the manual contains more."""

_UNANSWERABLE_PROMPT = """You grade whether an appliance manual assistant \
correctly declined to answer.

The manual does not cover this question, so the only correct behaviour is
saying it cannot be found, or handing the question to support.

It matches when the assistant declines, says the manual does not cover it, or
escalates. It does not match when it answers the question anyway - however
plausible the answer sounds. A confident invented answer is the failure this
check exists to catch."""


class Verdict(BaseModel):
    """Structured output of the judge.

    Two signals rather than one. Separating them is what removed the ambiguity
    that made the judge unstable, and `invents` is a metric the system had no
    way of producing before: how often it states something the manual does not.
    """

    covers: bool = Field(description="Conveys the facts of the reference answer.")
    invents: bool = Field(description="States something the manual does not support.")
    reason: str = Field(description="One sentence. What differs, or why it matches.")

    @property
    def matches(self) -> bool:
        return self.covers and not self.invents


async def judge_answer(
    question: str,
    answer: str,
    reference: str | None,
    answerable: bool,
    source_text: str = "",
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
            f"Assistant's answer: {answer}\n\n"
            f"Manual text for those pages:\n{source_text or '(not available)'}"
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
        return Verdict(
            covers=False, invents=False, reason=f"judge error: {type(exc).__name__}"
        )
