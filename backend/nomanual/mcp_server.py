"""MCP server: the retrieval pipeline exposed to external agents.

This is the one place in the project where a real agent is involved. Claude, 
or a manufacturer's own support bot, decides when to call
these tools, whether to rephrase and search again, and how to combine the
result with its own sources. We only supply capabilities.

It is also the commercial wedge: a manufacturer can start using NoManual from
the assistant they already run, without adopting our interface.

Every tool delegates to the same functions the HTTP API uses. Duplicating the
logic here would let the two drift apart, and then an answer would depend on
which door it came through.
"""

import logging
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field
from sqlalchemy import func, select

from nomanual.agent.graph import answer_question
from nomanual.core.db import SessionLocal
from nomanual.models import Chunk, Manual
from nomanual.searching.search import PIVOT_LANGUAGE, hybrid_search
from nomanual.searching.translate import translate_query

logger = logging.getLogger(__name__)

mcp = MCPServer("nomanual")


@mcp.tool(
    description=(
        "Search indexed appliance manuals and return the most relevant "
        "extracts, each with the page it came from. Use this when you want the "
        "source material to reason over yourself."
    )
)
async def search_manual(
    query: Annotated[str, Field(description="What to look for, in any language.")],
    limit: Annotated[int, Field(description="How many extracts.", ge=1, le=20)] = 5,
) -> list[dict]:
    """Raw retrieval: hybrid search, no generation.

    Returns the extracts rather than an answer so the calling agent keeps
    control - it may want to combine them with its own context, or quote them
    directly.
    """
    translated = await translate_query(query, PIVOT_LANGUAGE)
    if translated.casefold() == query.casefold():
        translated = None

    hits = await hybrid_search(query, translated, top_k=limit)
    logger.info("MCP search_manual(%r) -> %d hits", query, len(hits))

    return [
        {
            "chunk_id": str(hit.chunk_id),
            "content": hit.content,
            "pages": f"{hit.page_from}-{hit.page_to}",
            "language": hit.language,
            "similarity": round(hit.similarity, 3),
        }
        for hit in hits
    ]


@mcp.tool(
    description=(
        "Ask a question about an appliance and get a verified answer with "
        "citations. Every claim is checked against the retrieved extracts, and "
        "the tool declines rather than guess when the manuals do not cover it."
    )
)
async def ask_manual(
    question: Annotated[str, Field(description="The user's question.")],
) -> dict:
    """The full answering workflow, exposed as a single tool.

    Where search_manual hands over raw material, this runs routing, retrieval,
    generation and the grounding check, and returns something already verified.
    The calling agent chooses which it wants.
    """
    state = await answer_question(question)
    logger.info(
        "MCP ask_manual(%r) -> intent=%s grounded=%s",
        question,
        state.get("intent"),
        state.get("grounded"),
    )

    return {
        "answer": state["answer"],
        "intent": str(state.get("intent") or ""),
        "grounded": bool(state.get("grounded")),
        "escalated": bool(state.get("escalated", False)),
        "citations": [
            {"chunk_id": str(c.chunk_id), "page": c.page}
            for c in (state.get("citations") or [])
        ],
    }


@mcp.tool(
    description=(
        "List the appliance manuals available, with how many extracts each has "
        "indexed. Useful to know what can be answered before asking."
    )
)
async def list_manuals() -> list[dict]:
    """What is in the index right now."""
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Manual.title, Manual.status, func.count(Chunk.id))
                .outerjoin(Chunk, Chunk.manual_id == Manual.id)
                .group_by(Manual.id, Manual.title, Manual.status)
                .order_by(Manual.title)
            )
        ).all()

    return [
        {"title": title, "status": str(status), "chunks": chunks}
        for title, status, chunks in rows
    ]
