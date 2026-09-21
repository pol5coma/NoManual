"""Recording what the ingestion pipeline is doing, while it does it.

Two kinds of writes happen in this task and they want opposite things. The
chunks are one transaction at the end: either the new index replaces the old
one or the old one keeps serving. The progress is the reverse - many tiny
writes, each committed immediately, because a step nobody can see until the
job finishes is not progress, it is a log.

So each step opens its own session, writes one row and closes it. That costs a
handful of UPDATEs on a task that already takes a minute, and it buys a view of
the pipeline that survives a page reload, a worker restart and a week.
"""

import logging
import time
from typing import Any
from uuid import UUID

from nomanual.core.db import worker_session
from nomanual.models import Manual

logger = logging.getLogger(__name__)

# The pipeline, in order. Declared here rather than inferred from what has been
# written so far, so the UI can show the steps still to come instead of making
# them appear one by one out of nowhere.
STEPS: tuple[tuple[str, str], ...] = (
    ("read", "Reading the file from storage"),
    ("extract", "Extracting text from the PDF"),
    ("clean", "Cleaning text and detecting languages"),
    ("chunk", "Splitting into chunks"),
    ("embed", "Generating embeddings"),
    ("index", "Writing chunks and indexes"),
)


def plan() -> list[dict[str, Any]]:
    """Every step as pending, written before any work starts."""
    return [
        {"step": step, "label": label, "status": "pending"} for step, label in STEPS
    ]


class Progress:
    """Writes one step at a time to the manual row.

    Used as an async context manager per step:

        async with progress.step("extract") as detail:
            pages = extract_pages(data)
            detail["pages"] = len(pages)

    Whatever the block puts in `detail` is stored with the step, which is how
    the panel ends up showing 130 pages and 214 chunks rather than a row of
    green ticks that could mean anything.
    """

    def __init__(self, manual_id: UUID) -> None:
        self.manual_id = manual_id

    async def start(self) -> None:
        await self._write(plan())

    def step(self, name: str) -> "_Step":
        return _Step(self, name)

    async def fail(self, name: str, message: str) -> None:
        await self._update(name, {"status": "failed", "error": message})

    async def _update(self, name: str, changes: dict[str, Any]) -> None:
        """Merge changes into one step, leaving the rest untouched."""
        async with worker_session() as session:
            manual = await session.get(Manual, self.manual_id)
            if manual is None:
                return

            steps = list(manual.progress or plan())
            for index, step in enumerate(steps):
                if step["step"] == name:
                    steps[index] = {**step, **changes}
                    break

            # JSONB is replaced wholesale, not mutated in place: SQLAlchemy
            # cannot see a change inside a mutable column and would skip the
            # UPDATE entirely.
            manual.progress = steps
            await session.commit()

    async def _write(self, steps: list[dict[str, Any]]) -> None:
        async with worker_session() as session:
            manual = await session.get(Manual, self.manual_id)
            if manual is None:
                return
            manual.progress = steps
            await session.commit()


class _Step:
    """One step: marks it running, times it, and records what it produced."""

    def __init__(self, progress: Progress, name: str) -> None:
        self.progress = progress
        self.name = name
        self.detail: dict[str, Any] = {}

    async def __aenter__(self) -> dict[str, Any]:
        self.started = time.perf_counter()
        await self.progress._update(self.name, {"status": "running"})
        return self.detail

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        duration_ms = int((time.perf_counter() - self.started) * 1000)

        if exc_type is not None:
            # The step that failed is the most interesting row on the screen,
            # so it is marked rather than left hanging as "running".
            await self.progress._update(
                self.name,
                {
                    "status": "failed",
                    "duration_ms": duration_ms,
                    "error": f"{exc_type.__name__}: {exc}",
                },
            )
            # False: the caller still has to handle the exception.
            return False

        await self.progress._update(
            self.name,
            {"status": "done", "duration_ms": duration_ms, "detail": self.detail},
        )
        return False
