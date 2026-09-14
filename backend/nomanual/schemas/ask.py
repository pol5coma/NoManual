"""Request and response for the answering endpoint."""

from uuid import UUID

from pydantic import BaseModel, Field

from nomanual.agent.state import Citation


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # Reserved for the QR flow: the token identifies which appliance the user
    # is standing in front of, so retrieval can be scoped to its manuals.
    product_token: str | None = None


class AskResponse(BaseModel):
    """What the user gets back.

    Citations are the point: without them the answer is just a chatbot's word,
    and the whole grounding check has nothing to show for itself.
    """

    query_id: UUID
    question: str
    answer: str

    intent: str | None = None
    citations: list[Citation] = Field(default_factory=list)

    # Whether every claim traced back to a retrieved chunk.
    grounded: bool = False
    # True when we declined to answer and handed the question on.
    escalated: bool = False
