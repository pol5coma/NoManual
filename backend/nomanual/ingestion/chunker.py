"""Split extracted pages into retrievable chunks.

Chunks never cross a language boundary: a single PDF carries a dozen languages
in contiguous blocks, and an overlap running from French into Turkish produces
a chunk that belongs to neither.

Sections are carried as metadata but deliberately do NOT drive the grouping.
Measured across twelve manuals, heading detection is only reliable enough to
label a chunk, not to decide where one ends - grouping on a wrong boundary is
worse than not grouping at all, because it cuts procedures in half.

Within a language block, pages are joined before splitting, so a procedure that
runs across a page break stays in one chunk.
"""

from dataclasses import dataclass
from itertools import groupby

from langchain_text_splitters import RecursiveCharacterTextSplitter

from nomanual.ingestion.extract import Page

# Paragraphs first, then lines, then sentences: the splitter only falls back to
# cutting mid-word when a single fragment exceeds the chunk size on its own.
SEPARATORS = ["\n\n", "\n", ". ", "; ", ", ", " ", ""]

PAGE_JOIN = "\n\n"


@dataclass(slots=True)
class TextChunk:
    """A chunk ready to be embedded, with everything needed to cite it."""

    content: str
    ordinal: int
    page_from: int
    page_to: int
    language: str
    section: str | None

    def __str__(self) -> str:
        return self.content


def _pages_spanned(
    pages: list[Page], offsets: list[int], start: int, end: int
) -> tuple[int, int]:
    """Map a character range in the joined text back to page numbers."""
    first = last = pages[0].number
    for page, offset in zip(pages, offsets, strict=True):
        if offset <= start:
            first = page.number
        if offset < end:
            last = page.number
    return first, last


def chunk_pages(pages: list[Page], size: int, overlap: int) -> list[TextChunk]:
    """Split pages into chunks, never crossing a language or section boundary."""
    if not pages:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=SEPARATORS,
        # Gives each chunk its offset in the source text, which is how we work
        # out which pages it came from.
        add_start_index=True,
        keep_separator=True,
    )

    chunks: list[TextChunk] = []

    for _, group in groupby(pages, key=lambda p: p.language):
        block = list(group)

        # Offsets of each page within the joined block, so a chunk can be
        # traced back to the page or pages it spans.
        offsets: list[int] = []
        cursor = 0
        for page in block:
            offsets.append(cursor)
            cursor += len(page.text) + len(PAGE_JOIN)

        joined = PAGE_JOIN.join(page.text for page in block)

        for document in splitter.create_documents([joined]):
            content = document.page_content.strip()
            if not content:
                continue

            start = document.metadata["start_index"]
            page_from, page_to = _pages_spanned(
                block, offsets, start, start + len(document.page_content)
            )

            chunks.append(
                TextChunk(
                    content=content,
                    ordinal=len(chunks),
                    page_from=page_from,
                    page_to=page_to,
                    language=block[0].language,
                    section=block[0].section,
                )
            )

    return chunks
