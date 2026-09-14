"""Translate a question into the language a manual is written in.

Embeddings from OpenAI do work across languages, but they degrade: measured on
an English-only oven manual, Spanish questions retrieved the right passages at
a similarity of 0.36-0.50 against 0.56-0.59 for same-language search. Close
enough to find something, too close to noise to trust.

Translating the question rather than the corpus keeps that gap closed without
touching the sources. The manual stays in the manufacturer's own words, which
is what "page 22" has to point at.
"""

import logging

from langchain_openai import ChatOpenAI

from nomanual.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_model = ChatOpenAI(
    model=settings.chat_model,
    api_key=settings.openai_api_key,
    # Temperature 0: identical questions must translate identically, or the
    # same query would hit different chunks on different days.
    temperature=0,
)

# Appliance questions carry references that must survive untouched. A model
# left to its own devices will happily turn "E5" into "E5 (error cinco)" or
# translate a model name, and then the lexical search finds nothing.
_SYSTEM_PROMPT = (
    "You translate a single user question into {target}. "
    "Reply with the translation only: no quotes, no explanation, no preamble. "
    "Keep error codes, model numbers and button labels exactly as written "
    "(E5, F03, AS09FBAHRA, MODE). "
    "If the question is already in {target}, repeat it unchanged."
)

# ISO codes the detector emits, spelled out so the prompt reads naturally.
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "hr": "Croatian",
    "el": "Greek",
}


async def translate_query(text: str, target_language: str) -> str:
    """Translate a question, falling back to the original if anything fails.

    A failed translation should degrade the search, not break it: cross-language
    retrieval still returns something, an exception returns nothing.
    """
    target = LANGUAGE_NAMES.get(target_language, target_language)

    try:
        response = await _model.ainvoke(
            [
                ("system", _SYSTEM_PROMPT.format(target=target)),
                ("human", text),
            ]
        )
        translated = response.content.strip()
    except Exception:
        logger.exception("Could not translate %r to %s", text, target_language)
        return text

    if not translated:
        return text

    logger.info("Translated %r -> %r (%s)", text, translated, target_language)
    return translated
