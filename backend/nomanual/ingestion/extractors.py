"""Alternative PDF text extractors, for comparison.

Each backend reads the same page and returns plain text. They differ in how
they order the text on pages with columns, how much whitespace they keep, and
how they cope with fonts that carry no ToUnicode table.

Licensing matters if this ever ships:
  pypdf       BSD          - safe
  pdfplumber  MIT          - safe (wraps pdfminer.six)
  pymupdf     AGPL-3.0     - obliges you to release your source, or to buy a
                             commercial licence. Fine for evaluation.
"""

import io
from collections.abc import Callable
from typing import Literal

Backend = Literal[
    "pypdf",
    "pypdf-layout",
    "pdfplumber",
    "pdfplumber-layout",
    "pymupdf",
    "pymupdf-sorted",
]


def page_count(data: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(data)).pages)


def _pypdf(data: bytes, page: int, layout: bool = False) -> str:
    from pypdf import PdfReader

    pdf_page = PdfReader(io.BytesIO(data)).pages[page - 1]
    if layout:
        return pdf_page.extract_text(extraction_mode="layout") or ""
    return pdf_page.extract_text() or ""


def _pdfplumber(data: bytes, page: int, layout: bool = False) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        # layout=True reconstructs the visual position using the coordinates
        # pdfminer already knows, at the cost of a lot of padding whitespace.
        return pdf.pages[page - 1].extract_text(layout=layout) or ""


def _pymupdf(data: bytes, page: int, sort: bool = False) -> str:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        # sort=True orders blocks top-to-bottom, left-to-right instead of by
        # drawing order, which is what fixes two-column pages.
        return doc[page - 1].get_text(sort=sort)


EXTRACTORS: dict[str, Callable[[bytes, int], str]] = {
    "pypdf": lambda d, p: _pypdf(d, p),
    "pypdf-layout": lambda d, p: _pypdf(d, p, layout=True),
    "pdfplumber": lambda d, p: _pdfplumber(d, p),
    "pdfplumber-layout": lambda d, p: _pdfplumber(d, p, layout=True),
    "pymupdf": lambda d, p: _pymupdf(d, p),
    "pymupdf-sorted": lambda d, p: _pymupdf(d, p, sort=True),
}


def control_pct(text: str) -> float:
    """Share of control characters: the giveaway for a broken embedded font."""
    if not text:
        return 0.0
    control = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t")
    return control / len(text) * 100


def space_pct(text: str) -> float:
    """Share of spaces. Layout modes pad heavily, which inflates embedding cost."""
    if not text:
        return 0.0
    return text.count(" ") / len(text) * 100
