"""Keeping the state of a long conversation.

Not a prose summary: a few fields that say where the conversation stands. What
the user came for, what they have already tried, whether it worked, and the
facts they gave along the way - "it is the model with a display", "it shows
E4".

Two reasons for structure over prose. The model cannot drift into retelling the
conversation when the fields only have room for a goal and a list of attempts.
And the result is readable by a person: this is what a support dashboard would
show about an open case.

It runs only when a conversation outgrows its window. While every message still
fits, the transcript is a better summary than any model could write.
"""

import logging

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from nomanual.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ConversationSummary(BaseModel):
    """The running state of a conversation."""

    goal: str = Field(
        description="What the user is trying to achieve, in one sentence, "
        "in the language they are writing in."
    )
    tried: list[str] = Field(
        default_factory=list,
        description="Steps the assistant gave that the user has already "
        "followed. Short phrases, most recent last.",
    )
    outcome: str | None = Field(
        default=None,
        description="Where it stands: solved, still failing, or waiting on "
        "something the user has to check. None if it is not clear yet.",
    )
    facts: list[str] = Field(
        default_factory=list,
        description="Concrete details the user gave about their appliance or "
        "situation: error codes shown, model features, what they observed.",
    )


_SYSTEM_PROMPT = """You keep notes on a support conversation about a home appliance.

You are given the notes so far and the messages that have happened since. \
Return the updated notes.

Rules:
- Carry forward anything still true. Do not drop a fact because it is old.
- Do not invent. Only record what the messages actually say.
- Keep error codes, model numbers and button labels exactly as written.
- Write in the language the user is using."""

_model = ChatOpenAI(
    model=settings.summary_model or settings.chat_model,
    api_key=settings.openai_api_key,
    # The same conversation must produce the same notes: this is state, and
    # state that changes on its own is a bug.
    temperature=0,
).with_structured_output(ConversationSummary)


async def update_summary(previous: dict | None, transcript: str) -> dict | None:
    """Fold new messages into the notes, or keep the old ones on failure.

    A failed summary must not fail the answer: the user asked about their
    washing machine, not about our bookkeeping. Returning the previous notes
    loses the last few messages from the long-term view, and nothing else.
    """
    notes = "(no notes yet)" if not previous else str(previous)

    try:
        summary = await _model.ainvoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("human", f"Notes so far:\n{notes}\n\nNew messages:\n{transcript}"),
            ]
        )
    except Exception:
        logger.exception("Could not update the conversation summary")
        return previous

    return summary.model_dump()
