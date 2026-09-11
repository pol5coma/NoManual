"""Turn a PDF into clean, labelled pages.

Everything here was derived from measuring twelve real appliance manuals
rather than from assumptions:

* A PDF stores glyph positions, not spaces. Extractors have to infer word
  boundaries from the gap between boxes, and they differ a lot at it: on a
  130-page manual pdfplumber glued 374 words together ("Configureunatemperatura")
  against 42 for pymupdf, and took 85s against 1.5s.
* `(cid:N)` markers are unmappable glyphs - icons and bullets - not broken
  pages. Dropping pages that contain them threw away a quarter of the manual.
* A page whose embedded font has no ToUnicode table comes back as readable
  letters that spell nothing. Counting vowels catches it; counting control
  characters does not.
* One manual carries a dozen languages in contiguous blocks, but the per-page
  detector misfires on short pages, so the result is smoothed.
* Section headings are only trustworthy when they repeat across pages.
"""

import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

import py3langid as langid
import pymupdf

from nomanual.core.config import get_settings

settings = get_settings()

# The manuals we work with have corrupt embedded fonts; MuPDF is noisy about it.
pymupdf.TOOLS.mupdf_display_errors(False)

MIN_PAGE_CHARS = 40
MIN_LETTER_RATIO = 0.45
MAX_SECTION_CHARS = 60
# A heading has to appear on at least this many pages to count as one.
MIN_SECTION_REPEATS = 2
# Half-window used to smooth away one-off language misdetections.
LANGUAGE_SMOOTHING_WINDOW = 2
# Share of vowel-less words above which the page is font garbage.
GARBLED_THRESHOLD = 0.35
GARBLED_MIN_WORDS = 20

# Typographic ligatures and punctuation folded to ASCII, plus zero-width and
# soft hyphens removed.
_REPLACEMENTS = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "ft",
    "ﬆ": "st",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "…": "...",
    " ": " ",
    " ": " ",
    " ": " ",
    "​": "",
    "‌": "",
    "‍": "",
    "﻿": "",
    "­": "",
}
_REPLACE_RE = re.compile("|".join(map(re.escape, _REPLACEMENTS)))

# Glyphs the font could not map to Unicode. Almost always icons or bullets.
_CID_RE = re.compile(r"\(cid:\d+\)")
# Bullets the PDF emits as a dingbat plus control characters ("z\x03\x03", "\x84").
_BULLET_RE = re.compile(r"(?:^|(?<=\n))[z•▪●]?[\x00-\x1f\x7f-\x9f]+[ \t]*")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}")
_VOWELS = set("aeiouáéíóúüAEIOUÁÉÍÓÚÜ")


@dataclass(slots=True)
class Page:
    """One usable page of a manual."""

    # 1-indexed, matching what the reader sees. This ends up in the answer as
    # "see page 34", so it has to line up with the physical document.
    number: int
    text: str
    language: str
    section: str | None


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """Normalise raw page text into something worth embedding.

    The single most valuable line here is the lone-newline rule: PDFs break
    lines mid-sentence, and joining them without a space is what produces
    "Limpiezadelfiltrodeaire" - a token that resembles nothing and ruins both
    semantic and lexical search.
    """
    # NFC rather than NFKC: NFKC would wreck "ºC" into "oC" and "m²" into "m2".
    text = unicodedata.normalize("NFC", text)
    text = _CID_RE.sub(" ", text)
    text = _REPLACE_RE.sub(lambda m: _REPLACEMENTS[m.group()], text)

    # The degree glyph often arrives as a raised "o"/"º": "25 oC" -> "25 °C".
    text = re.sub(r"(\d)\s*[ºo]\s*([CF])\b", r"\1 °\2", text)

    text = _BULLET_RE.sub("• ", text)
    text = _CTRL_RE.sub(" ", text)

    # Words split by a hyphen at a line break: "inter-\nruttore" -> "interruttore".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # A lone newline inside a paragraph becomes a space. Double newlines (real
    # paragraphs) and the start of a bullet or numbered step are preserved.
    text = re.sub(r"(?<!\n)\n(?!\n)(?![•\d]\s|\s*$)", " ", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_garbled(text: str) -> bool:
    """Whether the page's embedded font produced letters that spell nothing.

    A font with no ToUnicode table returns its internal codes, which land as
    perfectly valid letters: "ÀXRULQDWR", or Greek glyphs spelling REFRIGERATOR.
    Character-class checks approve them. Words without a single vowel do not.
    """
    words = _WORD_RE.findall(text)
    if len(words) < GARBLED_MIN_WORDS:
        return False
    unreadable = sum(1 for word in words if not any(c in _VOWELS for c in word))
    return unreadable / len(words) > GARBLED_THRESHOLD


def is_usable(text: str) -> tuple[bool, str]:
    """Whether a page carries real text, and why not when it does not."""
    if len(text) < MIN_PAGE_CHARS:
        return False, "too short"
    if is_garbled(text):
        return False, "garbled font"
    letters = sum(1 for c in text if c.isalpha())
    if letters / len(text) < MIN_LETTER_RATIO:
        return False, "not enough letters"
    return True, ""


# --------------------------------------------------------------------------
# Extraction backends
# --------------------------------------------------------------------------


def _extract_pymupdf(data: bytes) -> list[str]:
    """Raw text per page via MuPDF. Default: fastest and best at word gaps."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        # Without TEXT_PRESERVE_LIGATURES, MuPDF expands fi/fl while extracting.
        return [
            page.get_text(
                flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES
            )
            for page in doc
        ]


def _extract_pdfplumber(data: bytes) -> list[str]:
    """Raw text per page via pdfminer. Slower and glues words more often, but
    MIT licensed where pymupdf is AGPL-3.0. Kept switchable so the two can be
    compared, and so licensing can decide without a rewrite."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


_BACKENDS = {
    "pymupdf": _extract_pymupdf,
    "pdfplumber": _extract_pdfplumber,
}


# --------------------------------------------------------------------------
# Labelling
# --------------------------------------------------------------------------


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
    prose does not repeat. Taking the first line at face value produced almost
    one "section" per page across twelve manuals - things like "Es-1", or the
    opening sentence of a paragraph.
    """
    counts = Counter(c for c in candidates if c)
    return [c if c and counts[c] >= MIN_SECTION_REPEATS else None for c in candidates]


def detect_language(text: str) -> str:
    # The first 1500 characters are plenty and keep this cheap on long pages.
    language, _ = langid.classify(text[:1500])
    return language


def _smooth_languages(languages: list[str]) -> list[str]:
    """Replace one-off detections with the local majority.

    langid misreads short or figure-heavy pages, reporting Luxembourgish in the
    middle of a Spanish block. Left alone, each of those forms its own chunking
    group and cuts the surrounding text in two.
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


def extract_pages(data: bytes, backend: str | None = None) -> list[Page]:
    """Extract usable pages, each labelled with its language and section.

    Returns an empty list for a scanned manual. That is not a parsing failure
    but a PDF made of images, and the caller decides what to do about it.
    """
    extractor = _BACKENDS[backend or settings.pdf_backend]

    numbers: list[int] = []
    texts: list[str] = []

    for number, raw in enumerate(extractor(data), start=1):
        text = clean_text(raw)
        usable, _ = is_usable(text)
        if usable:
            numbers.append(number)
            texts.append(text)

    if not texts:
        return []

    # Both passes need every page, so they run once the document is read.
    languages = _smooth_languages([detect_language(t) for t in texts])
    sections = _confirm_sections([_heading_candidate(t) for t in texts])

    return [
        Page(number=number, text=text, language=language, section=section)
        for number, text, language, section in zip(
            numbers, texts, languages, sections, strict=True
        )
    ]
