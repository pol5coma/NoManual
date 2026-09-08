"""Inspection endpoints for development.

Not part of the product: this router exists so extraction can be studied on
real PDFs without re-uploading or waiting for the full pipeline. It returns raw
text rather than JSON, so the output is readable straight from curl or the
browser. Mounted only when settings.debug_endpoints is on.
"""

import asyncio
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.core.db import get_session
from nomanual.core.storage import get_storage
from nomanual.ingestion.extractors import (
    EXTRACTORS,
    Backend,
    control_pct,
    page_count,
    space_pct,
)
from nomanual.models import Manual

# No prefix: these endpoints sit next to the real ones so the URLs stay short.
router = APIRouter(tags=["debug"])

RULE = "=" * 78


async def _load_pdf(session: AsyncSession, manual_id: UUID) -> bytes:
    manual = await session.get(Manual, manual_id)
    if manual is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual not found.")
    # pypdf and friends are blocking and these files are large, so they stay
    # off the event loop.
    return await asyncio.to_thread(get_storage().read, manual.storage_key)


def _run(backend: str, data: bytes, page: int) -> tuple[str, float]:
    started = time.perf_counter()
    try:
        text = EXTRACTORS[backend](data, page)
    except Exception as exc:  # noqa: BLE001 - a failing backend is a result too
        return f"<{type(exc).__name__}: {exc}>", time.perf_counter() - started
    return text, time.perf_counter() - started


def _header(backend: str, page: int, total: int, text: str, secs: float) -> str:
    return (
        f"\n{RULE}\n"
        f"{backend.upper()}  ·  page {page}/{total}  ·  {len(text):,} chars  ·  "
        f"{space_pct(text):.0f}% spaces  ·  {control_pct(text):.1f}% control  ·  "
        f"{secs:.2f}s\n"
        f"{RULE}\n{text}"
    )


@router.get(
    "/manuals/{manual_id}/extract",
    response_class=PlainTextResponse,
    summary="Raw extracted text of a manual (debug)",
)
async def extract_manual_text(
    manual_id: UUID,
    page: int | None = Query(None, ge=1, description="Single page; omit for all"),
    backend: Backend = Query("pypdf", description="Which extractor to use"),
    echo: bool = Query(True, description="Also print to the server console"),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Return the extracted text as plain text, page by page."""
    data = await _load_pdf(session, manual_id)
    total = await asyncio.to_thread(page_count, data)

    if page is not None and page > total:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"This manual has {total} pages."
        )

    pages = [page] if page else range(1, total + 1)
    parts = []
    for number in pages:
        text, secs = await asyncio.to_thread(_run, backend, data, number)
        parts.append(_header(backend, number, total, text, secs))

    out = "\n".join(parts)
    if echo:
        print(out)
    return out


@router.get(
    "/manuals/{manual_id}/extract/compare",
    response_class=PlainTextResponse,
    summary="Same page through every extractor (debug)",
)
async def compare_extractors(
    manual_id: UUID,
    page: int = Query(1, ge=1, description="Page to compare, 1-indexed"),
    echo: bool = Query(True, description="Also print to the server console"),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Run one page through every backend so the outputs sit side by side.

    The summary table at the top is the quick read: chars and % spaces show how
    verbose a backend is, % control flags a broken font, and the timing shows
    what each one costs per page.
    """
    data = await _load_pdf(session, manual_id)
    total = await asyncio.to_thread(page_count, data)

    if page > total:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"This manual has {total} pages."
        )

    results = {}
    for backend in EXTRACTORS:
        results[backend] = await asyncio.to_thread(_run, backend, data, page)

    summary = [
        f"\n{RULE}",
        f"SUMMARY  ·  page {page}/{total}",
        RULE,
        f"{'backend':<20} {'chars':>8} {'spaces':>8} {'control':>8} {'secs':>7}",
        "-" * 55,
    ]
    for backend, (text, secs) in results.items():
        summary.append(
            f"{backend:<20} {len(text):>8,} {space_pct(text):>7.0f}% "
            f"{control_pct(text):>7.1f}% {secs:>7.2f}"
        )

    body = [
        _header(backend, page, total, text, secs)
        for backend, (text, secs) in results.items()
    ]

    out = "\n".join(summary) + "\n" + "\n".join(body)
    if echo:
        print(out)
    return out
