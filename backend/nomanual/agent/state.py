"""State and typed outputs for the answering graph.

The graph is a workflow, not an agent: the path is defined here in code, and
the model decides content - which intent, which answer - never control flow.
That is deliberate. Answering a question about a manual is a predictable task,
and a fixed path keeps cost bounded and the whole thing measurable by evals.
"""

from enum import StrEnum
from typing import TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from nomanual.schemas.searching import SearchHit


class Intent(StrEnum):
    """What the user is asking for, which decides how we retrieve and answer."""

    # "what does E5 mean" - wants a literal lookup, favours lexical search
    ERROR_CODE = "error_code"
    # "how do I set the timer" - wants a procedure, favours semantic search
    HOW_TO = "how_to"
    # anything touching gas, mains wiring or dismantling: we do not improvise
    SAFETY = "safety"
    # not about an appliance at all
    OUT_OF_SCOPE = "out_of_scope"
    # coordial & general talk. Minimum but conversational.
    SMALL_TALK = "small_talk"


class Routing(BaseModel):
    """Structured output of the router node."""

    intent: Intent
    reason: str = Field(description="One short sentence explaining the choice.")


class Citation(BaseModel):
    """A claim tied to the chunk it came from."""

    chunk_id: UUID
    page: int


class DraftAnswer(BaseModel):
    """Structured output of the generator node."""

    answer: str = Field(description="The answer, in the language of the question.")
    citations: list[Citation] = Field(
        default_factory=list,
        description="Every chunk actually used. Empty if the context did not "
        "contain the answer.",
    )


class AnswerState(TypedDict, total=False):
    """What travels between nodes.

    LangGraph merges what each node returns into this dict, so a node only has
    to return the keys it changed.
    """

    question: str

    # The question as it will be searched for. A follow-up like "and how long
    # does it take?" is rewritten into a standalone question first: retrieval
    # only ever sees this string, and a vector built from three pronouns
    # matches nothing in the manual.
    search_question: str | None

    # The recent turns as (role, content), oldest first, and the running notes
    # for everything older than the window.
    history: list[tuple[str, str]]
    summary: dict | None

    # The appliance the user is asking about, chosen before the conversation
    # starts - by QR, by picking brand and model, or by uploading a manual.
    # Retrieval is scoped to it, so a question about an oven cannot be
    # answered from a washing machine's manual.
    product_id: UUID | None

    # Set when the cheap pre-screen rejected the question outright.
    rejection: str | None

    intent: Intent | None
    reason: str | None

    hits: list[SearchHit]
    translated_query: str | None

    answer: str | None
    citations: list[Citation]

    # Verdict of the grounding check, and why it failed. The reason matters:
    # retrying with the same prompt is a dice roll, retrying with "you cited a
    # chunk that was not provided" is a correction.
    grounded: bool | None
    feedback: str | None

    attempts: int
    escalated: bool
