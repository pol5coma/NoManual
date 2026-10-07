"""Tracing: seeing what a question did on its way to an answer.

An answer here is the result of five or six model calls and a retrieval - route,
condense, search, generate, verify. When one comes back wrong, the log line
"escalated" says what happened and nothing about why. A trace shows the whole
tree: what each node received, what it returned, how long it took and what it
cost.

LangSmith needs no instrumentation of its own: LangChain and LangGraph are
already wired to it, and it turns on from environment variables. The only work
is the one thing that is not obvious - pydantic-settings reads `.env` into a
Settings object, it does not export those values to the process environment,
so a key sitting in `.env` would never reach the tracer. This module copies
them across at startup.

Off unless a key is present. Nothing is sent, and nothing is slowed down, in a
checkout that has not opted in.
"""

import logging
import os

from nomanual.core.config import get_settings

logger = logging.getLogger(__name__)


def configure_tracing() -> bool:
    """Turn tracing on if it is configured. True when it is active.

    Called once at startup by every entrypoint that runs the graph: the API,
    the worker and the eval runner.
    """
    settings = get_settings()

    if not settings.langsmith_api_key:
        # Explicitly off rather than merely absent: an inherited LANGSMITH_
        # variable from the shell should not switch tracing on behind our back.
        os.environ["LANGSMITH_TRACING"] = "false"
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint

    logger.info("Tracing to LangSmith project %r", settings.langsmith_project)
    return True
