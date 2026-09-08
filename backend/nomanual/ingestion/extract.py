"""Turn a PDF into clean, labelled pages.

Everything here was derived from measuring a real 130-page appliance manual
rather than from assumptions. Three findings shaped it:

* pdfplumber orders text by coordinates, so two-column pages come out in
  reading order. pypdf returns drawing order, which shuffles numbered steps.
* `(cid:N)` markers are unmappable glyphs - icons and bullets - not broken
  pages. Dropping pages that contain them threw away a quarter of the manual.
* A single manual carries a dozen languages in contiguous blocks, but the
  per-page detector misfires on short pages, so the result is smoothed.
* Section headings are only trustworthy when they repeat across pages. Taking
  the first line at face value invented a section per page on most manuals.
"""

import io
import re
from collections import Counter
from dataclasses import dataclass

import pdfplumber
import py3langid as langid

# Glyphs the font could not map to Unicode. Almost always icons or bullets, so
# they are removed rather than treated as evidence of a broken page.
_CID = re.compile(r"\(cid:\d+\)")
_RUNS_OF_SPACE = re.compile(r"[ \t]{2,}")

MIN_PAGE_CHARS = 100
MAX_CONTROL_RATIO = 0.05
MIN_LETTER_RATIO = 0.45
MAX_SECTION_CHARS = 60
# A heading has to appear on at least this many pages to count as one.
MIN_SECTION_REPEATS = 2
# Half-window used to smooth away one-off language misdetections.
LANGUAGE_SMOOTHING_WINDOW = 2


@dataclass(slots=True)
class Page:
    """One usable page of a manual."""

    # 1-indexed, matching what the reader sees. This ends up in the answer as
    # "see page 34", so it has to line up with the physical document.
    number: int
    text: str
    language: str
    section: str | None


def _clean(text: str) -> str:
    return _RUNS_OF_SPACE.sub(" ", _CID.sub(" ", text)).strip()


def is_usable(text: str) -> tuple[bool, str]:
    """Whether a page carries real text, and why not when it does not.

    A page whose embedded font has no ToUnicode table comes back as the font's
    internal codes. There is no way to recover it - the mapping is simply not
    in the file - so it is dropped instead of poisoning the index.
    """
    if len(text) < MIN_PAGE_CHARS:
        return False, "too short"

    control = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t")
    if control / len(text) > MAX_CONTROL_RATIO:
        return False, "control characters"

    letters = sum(1 for c in text if c.isalpha())
    if letters / len(text) < MIN_LETTER_RATIO:
        return False, "not enough letters"

    return True, ""


def _heading_candidate(text: str) -> str | None:
    """The page's first line, if it is short enough to plausibly be a heading."""
    first = text.split("\n", 1)[0].strip()
    if not first or len(first) > MAX_SECTION_CHARS:
        return None
    # Page numbers and figure references are not headings.
    if not any(c.isalpha() for c in first):
        return None
    return first


def _confirm_sections(candidates: list[str | None]) -> list[str | None]:
    """Keep only headings that repeat across pages.

    Manuals print their section name on every page of the section; ordinary
    prose does not repeat. Measured over twelve real manuals, taking the first
    line at face value produced almost one "section" per page - things like
    "Es-1" or the opening sentence of a paragraph. Requiring a repeat removes
    that noise without any threshold to tune.
    """
    counts = Counter(c for c in candidates if c)
    return [c if c and counts[c] >= MIN_SECTION_REPEATS else None for c in candidates]


def _smooth_languages(languages: list[str]) -> list[str]:
    """Replace one-off detections with the local majority.

    langid misreads short or figure-heavy pages, reporting Luxembourgish or
    Aragonese in the middle of a Spanish block. Left alone, each of those forms
    its own chunking group and cuts the surrounding text in two.
    """
    smoothed = []
    for index, language in enumerate(languages):
        low = max(0, index - LANGUAGE_SMOOTHING_WINDOW)
        high = min(len(languages), index + LANGUAGE_SMOOTHING_WINDOW + 1)
        window = languages[low:high]
        majority, count = Counter(window).most_common(1)[0]
        # Only override when the neighbourhood clearly disagrees with the page.
        smoothed.append(majority if count > len(window) // 2 else language)
    return smoothed


def detect_language(text: str) -> str:
    # The first 1500 characters are plenty and keep this cheap on long pages.
    language, _ = langid.classify(text[:1500])
    return language


def extract_pages(data: bytes) -> list[Page]:
    """Extract usable pages, each labelled with its language and section.

    Returns an empty list for a scanned manual. That is not a parsing failure
    but a PDF made of images, and the caller decides what to do about it.
    """
    numbers: list[int] = []
    texts: list[str] = []

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number, pdf_page in enumerate(pdf.pages, start=1):
            text = _clean(pdf_page.extract_text() or "")
            usable, _ = is_usable(text)
            if usable:
                numbers.append(number)
                texts.append(text)

    if not texts:
        return []

    # Both passes need every page, so they run once the whole document is read.
    languages = _smooth_languages([detect_language(t) for t in texts])
    sections = _confirm_sections([_heading_candidate(t) for t in texts])

    return [
        Page(number=number, text=text, language=language, section=section)
        for number, text, language, section in zip(
            numbers, texts, languages, sections, strict=True
        )
    ]
