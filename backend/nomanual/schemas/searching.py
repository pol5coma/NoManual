from uuid import UUID

from pydantic import BaseModel


class SearchHit(BaseModel):
    chunk_id: UUID
    # Which manual this came from, so an answer can name its source.
    manual_id: UUID
    content: str
    page_from: int
    page_to: int
    language: str
    similarity: float


class SearchRequest(BaseModel):
    query: str
    language: str | None = None


class SearchResponse(BaseModel):
    """What API returns from a searching."""

    query: str

    # The filter actually applied. None means the search ran across every
    # language, which happens when filtering returned nothing.
    language: str | None = None

    # What we guessed from the query. Kept separate because detection is
    # unreliable on short questions and this is what you look at when results
    # come back empty.
    detected_language: str | None = None

    # Set when the question was translated to match the corpus. The first
    # thing to look at when results come back odd: this is what was
    # actually searched for.
    translated_query: str | None = None

    response: str | None = None
    hits: list[SearchHit]
