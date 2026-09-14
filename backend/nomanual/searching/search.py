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

import re
from collections import defaultdict

from sqlalchemy import func, select

from nomanual.core.db import SessionLocal
from nomanual.ingestion.embeddings import embeddings
from nomanual.models.chunk import Chunk
from nomanual.schemas.searching import SearchHit

TOP_K = 5

# How many candidates each strategy contributes before fusion. Wider than TOP_K
# on purpose: a chunk ranked 8th by one strategy and 2nd by the other is worth
# surfacing, and it would be invisible if each list stopped at five.
CANDIDATES = 20

# Reciprocal Rank Fusion constant. Dampens the advantage of the very top
# positions so that appearing in both lists beats topping just one. 60 is the
# value from the original paper and the de-facto default.
RRF_K = 60

# Anything that is not a letter or a digit is dropped before building the
# tsquery. That both avoids tsquery syntax errors on "¿como?" and makes the
# input safe: no user text reaches the query language.
_TERM_RE = re.compile(r"\w+", re.UNICODE)
# The language everything is searched in besides the original. Most manuals
# carry an English section, and it is where the embedding model is strongest.
PIVOT_LANGUAGE = "en"


async def get_embeddings(text: str) -> list[float]:
    return await embeddings.aembed_query(text)


async def query_texts(vectors: list[float], top_k: int = CANDIDATES) -> list[SearchHit]:
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

    return [_to_hit(chunk, distance) for chunk, distance in rows]


def _to_hit(chunk: Chunk, distance: float) -> SearchHit:
    return SearchHit(
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


async def lexical_search(
    query: str, vectors: list[float], top_k: int = CANDIDATES
) -> list[SearchHit]:
    """Full-text search over content_tsv, for what embeddings cannot see.

    Error codes are the reason this exists. "E5", "E4" and "E18" sit almost on
    top of each other in embedding space - the model understands "error code"
    but not which one - so semantic search returns a plausible neighbour rather
    than the right row. Literal matching does not have that problem.

    Terms are joined with OR rather than AND. A question is "que significa el
    codigo de error E5": requiring every word would match nothing, while OR lets
    ts_rank favour the chunk that actually contains E5.

    The 'simple' configuration is what makes this work: it applies no stemming,
    so "e5" survives tokenisation intact where a Spanish configuration might
    mangle it.
    """
    terms = _TERM_RE.findall(query.casefold())
    if not terms:
        return []

    tsquery = func.to_tsquery("simple", " | ".join(terms))
    distance = Chunk.embedding.cosine_distance(vectors)

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Chunk, distance.label("distance"))
                .where(Chunk.content_tsv.op("@@")(tsquery))
                .order_by(func.ts_rank(Chunk.content_tsv, tsquery).desc())
                .limit(top_k)
            )
        ).all()

    # The cosine distance is carried along even though ranking is lexical, so
    # every hit reports similarity on the same scale no matter which strategy
    # found it.
    return [_to_hit(chunk, distance) for chunk, distance in rows]


def reciprocal_rank_fusion(
    *ranked_lists: list[SearchHit], top_k: int = TOP_K, k: int = RRF_K
) -> list[SearchHit]:
    """Merge ranked lists by position rather than by score.

    Cosine similarity runs 0 to 1; ts_rank is unbounded and means something
    else entirely. Comparing or averaging them is meaningless, and normalising
    them requires knowing distributions we do not have.

    RRF sidesteps that by throwing the scores away and using only where each
    chunk placed:

        score(chunk) = sum over lists of  1 / (k + rank)

    A chunk that is 3rd semantically and 1st lexically beats one that only
    tops a single list. k dampens the top positions so a single first place
    cannot dominate on its own.
    """
    scores: dict[object, float] = defaultdict(float)
    hits: dict[object, SearchHit] = {}

    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            scores[hit.chunk_id] += 1 / (k + rank)
            # Keep whichever copy reports the higher similarity, so the value
            # shown to callers is the best evidence we have for that chunk.
            current = hits.get(hit.chunk_id)
            if current is None or hit.similarity > current.similarity:
                hits[hit.chunk_id] = hit

    ordered = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [hits[chunk_id] for chunk_id in ordered[:top_k]]


def merge_hits(*result_sets: list[SearchHit], top_k: int = TOP_K) -> list[SearchHit]:
    """Combine result sets that share a scoring scale, keeping the best score.

    Only valid between searches of the same kind - two vector searches, for
    instance. Use reciprocal_rank_fusion when mixing vector and lexical.
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


async def hybrid_search(
    query: str, translated: str | None = None, top_k: int = TOP_K
) -> list[SearchHit]:
    """Search semantically and lexically, then fuse the rankings.

    Up to three rankings feed the fusion: the question as written, the same
    question translated, and a literal match. Each catches what the others
    miss - meaning, cross-language phrasing, and exact references like E5.
    """
    vectors = await get_embeddings(query)
    rankings = [
        await query_texts(vectors),
        await lexical_search(query, vectors),
    ]

    if translated:
        rankings.append(await query_texts(await get_embeddings(translated)))

    return reciprocal_rank_fusion(*rankings, top_k=top_k)
