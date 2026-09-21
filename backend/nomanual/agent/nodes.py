"""The nodes of the answering graph.

Each one takes the state and returns only the keys it changes. Two are
deterministic (retrieve, verify) and two call a model (route, generate); the
split matters, because the deterministic ones are what make the workflow
trustworthy.
"""

import logging

from langchain_openai import ChatOpenAI

from nomanual.agent.guardrails import REJECTION_MESSAGES, prescreen
from nomanual.agent.state import AnswerState, DraftAnswer, Intent, Routing
from nomanual.core.config import get_settings
from nomanual.searching.search import PIVOT_LANGUAGE, hits_to_text, hybrid_search
from nomanual.searching.translate import translate_query

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_ATTEMPTS = 2
# Below this, the best chunk is not an answer but the least bad match. Drafting
# from it is inventing, so the graph escalates instead.
MIN_SIMILARITY = 0.35

_model = ChatOpenAI(
    model=settings.chat_model,
    api_key=settings.openai_api_key,
    temperature=0,
)

_ROUTER_PROMPT = """You classify a user's question about a household appliance.

error_code   asks what a specific code or error indicator means (E5, F03, a
             blinking light)
how_to       asks how to operate, configure, clean or maintain the appliance
safety       touches mains wiring, gas, refrigerant, dismantling the unit, or
             anything where a wrong instruction could injure someone
small_talk   a greeting, thanks, or asking who you are - social, not a
             request for information
out_of_scope not about an appliance or its manual at all

When a question could be how_to or safety, choose safety."""

# The rewrite that makes a conversation work. "And how long does it take?" is a
# perfectly clear question for a human and an empty one for a search engine:
# the vector carries pronouns and nothing else, and the lexical side has no term
# to match. Rewriting happens before retrieval because by the time the generator
# runs, the wrong chunks have already been chosen.
_CONDENSE_PROMPT = """You rewrite a follow-up message into a question that \
stands on its own.

You get the earlier conversation and the latest message. Return the latest \
message rewritten so it can be understood with no other context.

Rules:
- Replace pronouns and references with what they refer to ("it", "that mode", \
"the one you said").
- Keep the user's language, wording and level of detail. This is not a summary \
and not an improvement.
- Keep error codes, model numbers and button labels exactly as written.
- If the message already stands on its own, repeat it unchanged.
- Return the question only, with no preamble."""

_ANSWER_PROMPT = """You answer questions about household appliances using only \
the manual extracts provided.

Rules:
- Use only the extracts. Never add knowledge from anywhere else.
- Cite the chunk id of every extract you actually used.
- If the extracts do not answer the question, say so plainly and cite nothing.
- Answer in the same language as the question.
- Quote button and programme names exactly as they appear in the extract. They \
are printed on the appliance, and a translated label cannot be found by the user.

Manual extracts:
{context}"""

# Deliberately narrow. The risk is not that it greets badly, it is that a
# misrouted question reaches this node and gets answered with no retrieval, no
# citations and no grounding check - a back door around every guardrail. So the
# node refuses to leave its role even when the router hands it something else.
_CHAT_PROMPT = """You are the greeting half of an appliance manual assistant.

Reply to greetings, thanks and "who are you" in one short, warm sentence, then
steer the person towards their appliance: invite them to describe the problem or
name the model.

If the input is anything other than social courtesy - a factual question, a
request for instructions, anything at all - do not answer it. Say you only help
with appliance manuals and ask what appliance they mean.

Never state a fact about an appliance here. You have no manual extracts, so
anything you assert would be unsourced.

Reply in the language of the message."""

_SAFETY_ANSWER = (
    "This involves electrical, gas or refrigerant work. For your safety we do "
    "not provide instructions for it - contact the manufacturer's service "
    "centre or a qualified technician."
)
_OUT_OF_SCOPE_ANSWER = (
    "This does not look like a question about an appliance manual. Ask about "
    "operating, cleaning or troubleshooting your appliance."
)


def screen(state: AnswerState) -> AnswerState:
    """Reject obvious junk before the router costs a model call.

    Deterministic and instant. Whatever needs judgement is the router's job.
    """
    rejection = prescreen(state["question"])
    if rejection is None:
        return {"rejection": None}

    logger.info("Rejected %r: %s", state["question"][:60], rejection)
    return {
        "rejection": rejection,
        "answer": REJECTION_MESSAGES[rejection],
        "citations": [],
        "grounded": True,
    }


def _format_history(state: AnswerState) -> str:
    """The conversation so far, as the model reads it."""
    lines = []
    if state.get("summary"):
        lines.append(f"Notes on the conversation so far: {state['summary']}")

    lines += [f"{role}: {content}" for role, content in state.get("history") or []]
    return "\n".join(lines)


async def condense(state: AnswerState) -> AnswerState:
    """Turn a follow-up into a question that can be searched for on its own.

    Skipped entirely on the first message of a conversation, which is most of
    them: with no history there is nothing to resolve, and paying for a model
    call to copy a string is waste.

    On failure the original question is used. A worse search is recoverable;
    an exception is not.
    """
    question = state["question"]
    if not state.get("history") and not state.get("summary"):
        return {"search_question": question}

    try:
        response = await _model.ainvoke(
            [
                ("system", _CONDENSE_PROMPT),
                ("human", f"{_format_history(state)}\n\nLatest message: {question}"),
            ]
        )
        rewritten = response.content.strip()
    except Exception:
        logger.exception("Could not condense %r", question)
        return {"search_question": question}

    if not rewritten:
        return {"search_question": question}

    logger.info("Condensed %r -> %r", question, rewritten)
    return {"search_question": rewritten}


def _searchable(state: AnswerState) -> str:
    """What the rest of the graph works with: the rewrite, or the raw question."""
    return state.get("search_question") or state["question"]


async def route(state: AnswerState) -> AnswerState:
    """Classify the question before spending anything on retrieval.

    Structured output rather than free text: the branch depends on this value,
    and parsing prose to decide control flow is how workflows break.
    """
    question = _searchable(state)
    result = await _model.with_structured_output(Routing).ainvoke(
        [("system", _ROUTER_PROMPT), ("human", question)]
    )
    logger.info("Routed %r as %s: %s", question, result.intent, result.reason)
    return {"intent": result.intent, "reason": result.reason}


async def retrieve(state: AnswerState) -> AnswerState:
    """Fetch supporting chunks, hybrid search with the question translated too."""
    question = _searchable(state)
    translated = await translate_query(question, PIVOT_LANGUAGE)
    if translated.casefold() == question.casefold():
        translated = None

    hits = await hybrid_search(question, translated, product_id=state.get("product_id"))
    logger.info(
        "Retrieved %d chunks for product %s, best similarity %.3f",
        len(hits),
        state.get("product_id"),
        hits[0].similarity if hits else 0.0,
    )
    return {"hits": hits, "translated_query": translated}


async def generate(state: AnswerState) -> AnswerState:
    """Draft an answer from the retrieved extracts.

    On a retry the previous failure is appended to the prompt. Re-running an
    identical prompt and hoping for a different result is not a correction.
    """
    context = hits_to_text(state["hits"])
    messages = [("system", _ANSWER_PROMPT.format(context=context))]

    # The conversation is context for how to word the reply, never a source:
    # the answer still has to come from the extracts above.
    conversation = _format_history(state)
    if conversation:
        messages.append(
            (
                "system",
                "Earlier in this conversation (context only, never a source "
                f"of facts):\n{conversation}",
            )
        )

    if state.get("feedback"):
        messages.append(
            ("system", f"Your previous attempt was rejected: {state['feedback']}")
        )

    messages.append(("human", _searchable(state)))

    draft = await _model.with_structured_output(DraftAnswer).ainvoke(messages)
    return {
        "answer": draft.answer,
        "citations": draft.citations,
        "attempts": state.get("attempts", 0) + 1,
    }


def verify(state: AnswerState) -> AnswerState:
    """Check the answer is grounded in what was actually retrieved.

    This is a set comparison, not a judgement. A model asked "is this
    grounded?" can be wrong or agreeable; a cited chunk id either was in the
    context or it was not. That is the difference between a guardrail and a
    hopeful prompt.
    """
    citations = state.get("citations") or []
    retrieved = {hit.chunk_id for hit in state["hits"]}
    cited = {citation.chunk_id for citation in citations}

    if not cited:
        return {
            "grounded": False,
            "feedback": "You cited nothing. Either cite the extracts you used, "
            "or state that the manual does not cover this.",
        }

    invented = cited - retrieved
    if invented:
        return {
            "grounded": False,
            "feedback": f"You cited {len(invented)} chunk id(s) that were not "
            "in the extracts provided. Cite only ids you were given.",
        }

    return {"grounded": True, "feedback": None}


async def chat(state: AnswerState) -> AnswerState:
    """Answer social messages without retrieving anything.

    Goes straight to END: there is nothing to verify, because there is nothing
    to ground. That is exactly why the prompt is so restrictive - this is the
    one path where an answer leaves the graph without a citation.
    """
    response = await _model.ainvoke(
        [("system", _CHAT_PROMPT), ("human", state["question"])]
    )
    return {
        "answer": response.content.strip(),
        "citations": [],
        # Nothing was claimed, so nothing is unsupported. Analytics should
        # exclude this intent rather than read it as a resolved question.
        "grounded": True,
    }


def refuse(state: AnswerState) -> AnswerState:
    """Answer safety and out-of-scope questions without retrieving anything."""
    answer = (
        _SAFETY_ANSWER if state["intent"] is Intent.SAFETY else _OUT_OF_SCOPE_ANSWER
    )
    return {"answer": answer, "citations": [], "grounded": True}


def escalate(state: AnswerState) -> AnswerState:
    """Give up honestly rather than answer without support."""
    logger.info(
        "Escalating %r after %d attempts", state["question"], state.get("attempts", 0)
    )
    return {
        "escalated": True,
        "answer": "I could not find a reliable answer to this in the manual. "
        "Passing it to the manufacturer's support team.",
        "grounded": False,
    }
