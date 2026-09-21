"""The pipeline reports what it is doing, while it is doing it.

Progress is written in small transactions of its own, separate from the one
that swaps the chunks. These tests pin that difference: a step has to be
visible from another connection before the ingestion finishes, or the panel
showing it is decoration.
"""

from conftest import make_manual
from sqlalchemy import select

from nomanual.core.db import SessionLocal
from nomanual.ingestion.progress import STEPS, Progress
from nomanual.models import Manual


async def _progress_from_another_connection(manual_id) -> list[dict]:
    """What a request to the API would see right now."""
    async with SessionLocal() as session:
        return await session.scalar(
            select(Manual.progress).where(Manual.id == manual_id)
        )


async def test_every_step_is_listed_before_any_work_starts(session):
    """The UI shows what is coming, not steps appearing out of nowhere."""
    manual = await make_manual(session)
    await session.commit()

    await Progress(manual.id).start()

    steps = await _progress_from_another_connection(manual.id)
    assert [step["step"] for step in steps] == [name for name, _ in STEPS]
    assert {step["status"] for step in steps} == {"pending"}


async def test_a_running_step_is_visible_before_it_finishes(session):
    manual = await make_manual(session)
    await session.commit()

    progress = Progress(manual.id)
    await progress.start()

    async with progress.step("extract") as detail:
        # Mid-step: this is the moment the browser polls.
        running = await _progress_from_another_connection(manual.id)
        assert next(s for s in running if s["step"] == "extract")["status"] == "running"
        detail["pages"] = 130

    done = await _progress_from_another_connection(manual.id)
    extract = next(step for step in done if step["step"] == "extract")
    assert extract["status"] == "done"
    assert extract["detail"] == {"pages": 130}
    # Timed, because "extraction 1.4 s, embeddings 8.2 s" is the point of the
    # whole panel.
    assert extract["duration_ms"] >= 0


async def test_a_failing_step_records_the_error_and_re_raises(session):
    manual = await make_manual(session)
    await session.commit()

    progress = Progress(manual.id)
    await progress.start()

    try:
        async with progress.step("embed"):
            raise RuntimeError("OpenAI is down")
    except RuntimeError:
        pass
    else:  # pragma: no cover - the context manager must not swallow it
        raise AssertionError("the exception has to reach the caller")

    steps = await _progress_from_another_connection(manual.id)
    embed = next(step for step in steps if step["step"] == "embed")
    assert embed["status"] == "failed"
    assert "OpenAI is down" in embed["error"]
    # The steps after it stay pending rather than looking finished.
    assert next(s for s in steps if s["step"] == "index")["status"] == "pending"


async def test_steps_do_not_overwrite_each_other(session):
    manual = await make_manual(session)
    await session.commit()

    progress = Progress(manual.id)
    await progress.start()

    async with progress.step("read") as detail:
        detail["bytes"] = 1024
    async with progress.step("extract") as detail:
        detail["pages"] = 3

    steps = await _progress_from_another_connection(manual.id)
    finished = {step["step"]: step["status"] for step in steps}
    assert finished["read"] == "done"
    assert finished["extract"] == "done"
    assert finished["chunk"] == "pending"
