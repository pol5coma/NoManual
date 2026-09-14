"""The answering graph.

    question
       │
       ▼
    screen ─── junk / injection ───────────────► END
       │
       ▼
    route ──── safety / out_of_scope ──────────► refuse ──► END
       │
       ▼
    retrieve ── nothing relevant ──────────────► escalate ► END
       │
       ▼
    generate ◄──── retry with feedback ──┐
       │                                  │
       ▼                                  │
    verify ──── not grounded ─────────────┤
       │                                  │
       │        attempts exhausted ───────┴──► escalate ► END
       ▼
      END

The loop is what makes this a graph rather than a chain: verify can send the
flow backwards. Everything else would be a sequence of function calls.
"""

from langgraph.graph import END, StateGraph

from nomanual.agent.nodes import (
    MAX_ATTEMPTS,
    MIN_SIMILARITY,
    escalate,
    generate,
    refuse,
    retrieve,
    route,
    screen,
    verify,
)
from nomanual.agent.state import AnswerState, Intent


def after_screen(state: AnswerState) -> str:
    """A rejected question is already answered; nothing else needs to run."""
    return END if state.get("rejection") else "route"


def after_route(state: AnswerState) -> str:
    """Safety and out-of-scope questions never reach retrieval.

    Cutting here is not only about correctness: a question we will not answer
    should not cost an embedding call and a generation.
    """
    if state["intent"] in (Intent.SAFETY, Intent.OUT_OF_SCOPE):
        return "refuse"
    return "retrieve"


def after_retrieve(state: AnswerState) -> str:
    """Escalate when nothing retrieved is good enough to answer from.

    Below the threshold the best chunk is not an answer, it is the least bad
    match in the corpus. Drafting from it produces something fluent and wrong,
    which is worse than admitting we do not know.
    """
    hits = state.get("hits") or []
    if not hits or hits[0].similarity < MIN_SIMILARITY:
        return "escalate"
    return "generate"


def after_verify(state: AnswerState) -> str:
    """Retry a rejected answer, but not forever.

    Each retry is a full generation. Two failures usually mean the manual does
    not contain the answer, not that the model needs another go.
    """
    if state.get("grounded"):
        return END
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        return "escalate"
    return "generate"


def build_graph():
    """Wire the nodes together and compile."""
    builder = StateGraph(AnswerState)

    builder.add_node("screen", screen)
    builder.add_node("route", route)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    builder.add_node("verify", verify)
    builder.add_node("refuse", refuse)
    builder.add_node("escalate", escalate)

    builder.set_entry_point("screen")
    builder.add_conditional_edges("screen", after_screen, ["route", END])
    builder.add_conditional_edges("route", after_route, ["refuse", "retrieve"])
    builder.add_conditional_edges("retrieve", after_retrieve, ["generate", "escalate"])
    builder.add_edge("generate", "verify")
    builder.add_conditional_edges("verify", after_verify, ["generate", "escalate", END])
    builder.add_edge("refuse", END)
    builder.add_edge("escalate", END)

    return builder.compile()


# Compiled once: building the graph on every request would re-create the model
# clients too.
answer_graph = build_graph()


async def answer_question(question: str) -> AnswerState:
    """Run a question through the graph and return the final state."""
    return await answer_graph.ainvoke({"question": question, "attempts": 0})
