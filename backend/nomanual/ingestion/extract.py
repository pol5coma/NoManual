import io
from dataclasses import dataclass

from pypdf import PdfReader


@dataclass(slots=True)
class Page:
    """One page of extracted text."""

    # 1-indexed, matching what the user sees in a PDF reader. This number ends
    # up in the answer as "see page 34", so it has to line up.
    number: int
    text: str


def extract_pages(data: bytes) -> list[Page]:
    """Extract plain text per page, dropping pages that carry none.

    A scanned manual returns an empty list. That is not a parsing failure but a
    PDF made of images, and the caller decides what to do about it.
    """
    reader = PdfReader(io.BytesIO(data))
    pages: list[Page] = []

    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(Page(number=index, text=text))

    return pages
