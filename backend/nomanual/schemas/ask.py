"""Request and response for the answering endpoint."""

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from nomanual.agent.state import Citation


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

    # The appliance, chosen before the conversation starts. Either works:
    # product_id from a picker, or the token a QR code carries.
    product_id: UUID | None = None
    product_token: str | None = None

    # The thread this question belongs to. Omitted on the first message: the
    # API opens a conversation and returns its id, and the client sends it back
    # from then on.
    conversation_id: UUID | None = None

    @model_validator(mode="after")
    def _needs_an_appliance(self) -> "AskRequest":
        """Refuse a question with nothing to scope it to.

        Without a product, retrieval would run across every manual in the
        catalogue and answer about someone else's appliance. The product comes
        directly, from a QR token, or from the conversation it continues.
        """
        if not (self.product_id or self.product_token or self.conversation_id):
            raise ValueError(
                "Provide product_id, product_token or conversation_id."
            )
        return self


class AskResponse(BaseModel):
    """What the user gets back.

    Citations are the point: without them the answer is just a chatbot's word,
    and the whole grounding check has nothing to show for itself.
    """

    query_id: UUID
    # Always returned, including on the first message: this is how the client
    # learns which thread to continue.
    conversation_id: UUID
    question: str
    answer: str

    intent: str | None = None
    citations: list[Citation] = Field(default_factory=list)

    # Whether every claim traced back to a retrieved chunk.
    grounded: bool = False
    # True when we declined to answer and handed the question on.
    escalated: bool = False
