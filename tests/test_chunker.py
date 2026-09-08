"""Tests for the chunker.

This is the piece with the most subtle logic in the pipeline and the one that
gets tuned most often, so it is the one worth pinning down.
"""

import pytest
from nomanual.ingestion.chunker import chunk_pages
from nomanual.ingestion.extract import (
    Page,
    _confirm_sections,
    _smooth_languages,
)


def page(number: int, text: str, language: str = "es", section: str | None = None):
    return Page(number=number, text=text, language=language, section=section)


def test_no_pages_gives_no_chunks():
    assert chunk_pages([], size=100, overlap=10) == []


def test_short_page_becomes_one_chunk():
    chunks = chunk_pages([page(1, "Pulse el botón MODE.")], size=1000, overlap=100)

    assert len(chunks) == 1
    assert chunks[0].content == "Pulse el botón MODE."
    assert chunks[0].page_from == chunks[0].page_to == 1


def test_long_page_is_split():
    chunks = chunk_pages([page(1, "palabra " * 400)], size=200, overlap=20)

    assert len(chunks) > 1
    assert all(len(c.content) <= 260 for c in chunks)


def test_ordinals_are_sequential():
    chunks = chunk_pages([page(1, "frase larga. " * 200)], size=150, overlap=15)

    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_chunks_never_span_two_languages():
    chunks = chunk_pages(
        [
            page(1, "Pulse el botón para encender. " * 20, language="es"),
            page(2, "Press the button to switch on. " * 20, language="en"),
        ],
        size=2000,
        overlap=100,
    )

    # A single chunk would have swallowed both pages at this size.
    assert len(chunks) >= 2
    assert {c.language for c in chunks} == {"es", "en"}
    for chunk in chunks:
        assert not ("Pulse" in chunk.content and "Press" in chunk.content)


def test_section_is_metadata_not_a_boundary():
    """Sections label a chunk but do not decide where it ends.

    Heading detection was measured across twelve manuals and is only reliable
    enough to annotate. Splitting on a wrong boundary cuts procedures in half,
    which is worse than not splitting at all.
    """
    chunks = chunk_pages(
        [
            page(1, "Limpie el filtro cada mes. " * 10, section="Mantenimiento"),
            page(2, "Error E5 indica sonda averiada. " * 10, section="Errores"),
        ],
        size=5000,
        overlap=100,
    )

    assert len(chunks) == 1
    assert chunks[0].section == "Mantenimiento"
    assert "filtro" in chunks[0].content
    assert "E5" in chunks[0].content


def test_page_range_covers_a_chunk_spanning_pages():
    chunks = chunk_pages(
        [page(7, "Primera parte del procedimiento."), page(8, "Segunda parte.")],
        size=5000,
        overlap=0,
    )

    assert len(chunks) == 1
    assert (chunks[0].page_from, chunks[0].page_to) == (7, 8)


def test_page_numbers_are_the_real_ones():
    """Citations say "page 34", so the number must be the PDF's, not an index."""
    chunks = chunk_pages(
        [page(34, "Contenido de la página treinta y cuatro.")], size=1000, overlap=0
    )

    assert chunks[0].page_from == 34


def test_overlap_repeats_text_between_consecutive_chunks():
    chunks = chunk_pages(
        [page(1, "uno dos tres cuatro cinco seis siete ocho. " * 30)],
        size=200,
        overlap=60,
    )

    assert len(chunks) > 2
    # Some tail of one chunk must reappear at the head of the next.
    overlaps = [
        any(
            chunks[i].content[-30:].strip() in chunks[i + 1].content
            or chunks[i + 1].content[:30].strip() in chunks[i].content
            for _ in [0]
        )
        for i in range(len(chunks) - 1)
    ]
    assert any(overlaps)


@pytest.mark.parametrize("size,overlap", [(100, 10), (500, 50), (1200, 150)])
def test_every_chunk_has_content_and_a_valid_page_range(size, overlap):
    pages = [page(n, f"Texto de la página {n}. " * 40) for n in range(1, 6)]

    for chunk in chunk_pages(pages, size=size, overlap=overlap):
        assert chunk.content.strip()
        assert 1 <= chunk.page_from <= chunk.page_to <= 5


class TestSectionConfirmation:
    """Headings only count when they repeat, which is what tells a real section
    apart from the first sentence of a paragraph."""

    def test_repeated_heading_is_kept(self):
        assert _confirm_sections(["Mantenimiento", "Mantenimiento", "Otra"]) == [
            "Mantenimiento",
            "Mantenimiento",
            None,
        ]

    def test_one_off_line_is_dropped(self):
        # "Es-1" and stray prose showed up as sections on real manuals.
        assert _confirm_sections(["Es-1", "Risk of burns! When replacing"]) == [
            None,
            None,
        ]

    def test_missing_candidates_stay_missing(self):
        assert _confirm_sections([None, None]) == [None, None]


class TestLanguageSmoothing:
    """langid misreads short pages; a single stray language would otherwise cut
    a chunking group in two."""

    def test_stray_detection_is_absorbed(self):
        languages = ["es"] * 4 + ["lb"] + ["es"] * 4
        assert _smooth_languages(languages) == ["es"] * 9

    def test_real_language_block_survives(self):
        languages = ["es"] * 6 + ["en"] * 6
        assert _smooth_languages(languages) == languages

    def test_single_page_document(self):
        assert _smooth_languages(["es"]) == ["es"]
