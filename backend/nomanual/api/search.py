from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.core.db import get_session
from nomanual.schemas.searching import SearchRequest, SearchResponse
from nomanual.searching.search import (
    PIVOT_LANGUAGE,
    get_embeddings,
    hits_to_text,
    merge_hits,
    query_texts,
)
from nomanual.searching.translate import translate_query

router = APIRouter(prefix="/search", tags=["searching"])


@router.post("/", response_model=SearchResponse)
async def search(
    item: SearchRequest, session: AsyncSession = Depends(get_session)
) -> SearchResponse:
    """Search the indexed manuals with the question as written and in English.

    Filtering by the question's language was worse than not filtering: it hid
    every chunk of an English-only manual from a Spanish question and left the
    wrong manual answering. Searching both ways instead needs no language
    detection and no knowledge of which product is meant.
    """
    question = item.query

    translated = await translate_query(question, PIVOT_LANGUAGE)
    # The model returns the question unchanged when it is already English, so
    # there is nothing to gain from a second identical search.
    searches = [await query_texts(await get_embeddings(question))]
    if translated.casefold() != question.casefold():
        searches.append(await query_texts(await get_embeddings(translated)))
    else:
        translated = None

    hits = merge_hits(*searches)

    return SearchResponse(
        query=question,
        translated_query=translated,
        hits=hits,
        response=hits_to_text(hits),
    )
