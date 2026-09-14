"""Retrieval over the indexed manuals.

The question is searched twice: as written, and translated into English. Both
result sets are merged and the best chunks win.

That comes from measurement, not preference. Filtering by the question's
language actively hurt: asking "como precaliento el horno" with a language
filter removed every chunk of the English-only oven manual and left only the
Spanish air-conditioner ones competing - the wrong manual entirely. Dropping
the filter let the multilingual embeddings do their job and the oven came back
first. Translating on top raised the best match from 0.484 to 0.621.

Searching both ways needs neither language detection - unreliable on short
questions, "cada cuanto limpio el filtro" is read as Venetian - nor knowing
which product the user means.
"""

from sqlalchemy import select

from nomanual.core.db import SessionLocal
from nomanual.ingestion.embeddings import embeddings
from nomanual.models.chunk import Chunk
from nomanual.schemas.searching import SearchHit

TOP_K = 5
# The language everything is searched in besides the original. Most manuals
# carry an English section, and it is where the embedding model is strongest.
PIVOT_LANGUAGE = "en"


async def get_embeddings(text: str) -> list[float]:
    return await embeddings.aembed_query(text)


async def query_texts(vectors: list[float], top_k: int = TOP_K) -> list[SearchHit]:
    """Nearest chunks to a vector, closest first."""
    async with SessionLocal() as session:
        distance = Chunk.embedding.cosine_distance(vectors)
        rows = (
            await session.execute(
                select(Chunk, distance.label("distance"))
                .order_by(distance)
                .limit(top_k)
            )
        ).all()

    return [
        SearchHit(
            chunk_id=chunk.id,
            manual_id=chunk.manual_id,
            content=chunk.content,
            page_from=chunk.page_from,
            page_to=chunk.page_to,
            language=chunk.language,
            # pgvector returns cosine distance (0 = identical), so similarity is
            # its complement and higher reads as better.
            similarity=1 - distance,
        )
        for chunk, distance in rows
    ]


def merge_hits(*result_sets: list[SearchHit], top_k: int = TOP_K) -> list[SearchHit]:
    """Combine result sets, keeping each chunk's best score.

    A chunk found by both the original and the translated question is the same
    chunk, and deserves its highest similarity rather than two entries.
    """
    best: dict[object, SearchHit] = {}
    for hits in result_sets:
        for hit in hits:
            current = best.get(hit.chunk_id)
            if current is None or hit.similarity > current.similarity:
                best[hit.chunk_id] = hit

    return sorted(best.values(), key=lambda hit: hit.similarity, reverse=True)[:top_k]


def hits_to_text(hits: list[SearchHit]) -> str:
    """Format hits as the context an LLM reads.

    The chunk id travels with the text so the model can cite it and the
    grounding check can verify the citation against what was retrieved.
    """
    return "\n\n".join(
        f"[chunk {hit.chunk_id} · page {hit.page_from}-{hit.page_to}]\n{hit.content}"
        for hit in hits
    )
