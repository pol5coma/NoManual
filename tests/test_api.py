"""The HTTP contract: what a client gets back, and what is written down.

The requests go through the real FastAPI app over an in-process transport, so
validation, dependencies and response models all run. Only the two things that
leave the process are faked: the Celery queue and the LLM.
"""

import pytest
from conftest import make_manual, make_product
from sqlalchemy import func, select

from nomanual.models import Manual, Product, QueryLog, manual_product
from nomanual.models.enums import ManualStatus

PDF = b"%PDF-1.4 a manual"


@pytest.fixture(autouse=True)
def no_celery(monkeypatch) -> list[str]:
    """Nothing reaches a worker: the queue call is recorded instead."""
    from nomanual.api import manuals as manuals_api

    sent: list[str] = []
    monkeypatch.setattr(
        manuals_api, "_queue_ingestion", lambda manual_id: sent.append(str(manual_id))
    )
    return sent


# --- Uploads ------------------------------------------------------------------


async def test_upload_accepts_a_pdf_and_queues_it(session, client, no_celery):
    response = await client.post(
        "/manuals/upload",
        data={
            "brand": "Haier",
            "model": "AS09FBAHRA",
            "product_type": "air_conditioner",
        },
        files={"file": ("manual.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    # 202, not 200: the work happens in the background and the client polls.
    assert body["status"] == ManualStatus.PROCESSING.value
    assert no_celery == [body["id"]]

    product = await session.scalar(select(Product))
    assert (product.brand, product.model) == ("Haier", "AS09FBAHRA")


async def test_a_file_that_is_not_a_pdf_is_rejected(client, no_celery):
    response = await client.post(
        "/manuals/upload",
        data={"brand": "Haier", "model": "AS09FBAHRA"},
        files={"file": ("manual.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 415
    assert no_celery == []


async def test_the_same_file_for_another_model_links_instead_of_reprocessing(
    session, client, no_celery
):
    """A family manual: same bytes, second model, no second ingestion."""
    first = await client.post(
        "/manuals/upload",
        data={"brand": "Haier", "model": "AS09FBAHRA"},
        files={"file": ("manual.pdf", PDF, "application/pdf")},
    )
    no_celery.clear()

    second = await client.post(
        "/manuals/upload",
        data={"brand": "Haier", "model": "AS12FBAHRA"},
        files={"file": ("manual.pdf", PDF, "application/pdf")},
    )

    assert second.json()["id"] == first.json()["id"]
    assert await session.scalar(select(func.count()).select_from(Manual)) == 1
    assert await session.scalar(select(func.count()).select_from(Product)) == 2
    # Both models point at the one manual.
    links = await session.scalar(select(func.count()).select_from(manual_product))
    assert links == 2
    # Already claimed by the first upload, so nothing is queued again.
    assert no_celery == []


async def test_brand_and_model_are_matched_case_insensitively(session, client):
    for model in ("AS09FBAHRA", "as09fbahra"):
        await client.post(
            "/manuals/upload",
            data={"brand": "haier", "model": model},
            files={"file": (f"{model}.pdf", PDF + model.encode(), "application/pdf")},
        )

    assert await session.scalar(select(func.count()).select_from(Product)) == 1


async def test_ingesting_a_ready_manual_returns_409(session, client):
    manual = await make_manual(session, status=ManualStatus.READY)
    await session.commit()

    response = await client.post(f"/manuals/{manual.id}/ingest")

    assert response.status_code == 409
    assert "already been processed" in response.json()["detail"]


# --- Products -----------------------------------------------------------------


async def test_products_are_listed_and_fetched(session, client):
    product = await make_product(session)
    await session.commit()

    listed = await client.get("/products")
    assert [item["model"] for item in listed.json()] == [product.model]

    fetched = await client.get(f"/products/{product.id}")
    assert fetched.json()["brand"] == product.brand


# --- Ask ----------------------------------------------------------------------


@pytest.fixture
def fake_answer(monkeypatch):
    """Replace the LangGraph run with a fixed state.

    What is under test here is the endpoint: what it logs and what it returns.
    The workflow itself is measured by the eval suite, not by unit tests.
    """
    from nomanual.api import ask as ask_api

    def _install(**state):
        async def _answer(question, product_id=None, history=None, summary=None):
            return {"answer": "Clean it every two weeks.", "intent": "how_to", **state}

        monkeypatch.setattr(ask_api, "answer_question", _answer)

    return _install


async def test_a_grounded_answer_is_logged_as_resolved(session, client, fake_answer):
    fake_answer(grounded=True, escalated=False, citations=[])
    product = await make_product(session)
    await session.commit()

    response = await client.post(
        "/ask",
        json={
            "question": "cada cuánto limpio el filtro",
            "product_id": str(product.id),
        },
    )

    assert response.status_code == 200
    assert response.json()["grounded"] is True

    log = await session.scalar(select(QueryLog))
    assert log.resolved is True
    assert log.normalized_question == "cada cuánto limpio el filtro"
    assert log.latency_ms >= 0


async def test_an_escalated_answer_is_not_resolved(session, client, fake_answer):
    fake_answer(grounded=True, escalated=True, citations=[])
    product = await make_product(session)
    await session.commit()

    await client.post(
        "/ask", json={"question": "cómo lo reparo", "product_id": str(product.id)}
    )

    log = await session.scalar(select(QueryLog))
    assert log.resolved is False


async def test_a_question_can_be_asked_by_public_token(session, client, monkeypatch):
    """The QR on the appliance carries a token, never an internal id."""
    from nomanual.api import ask as ask_api

    captured = {}

    async def _answer(question, product_id=None, history=None, summary=None):
        captured["product_id"] = product_id
        return {"answer": "ok", "intent": "how_to", "grounded": True, "citations": []}

    monkeypatch.setattr(ask_api, "answer_question", _answer)

    product = await make_product(session)
    await session.commit()

    await client.post(
        "/ask",
        json={
            "question": "cada cuánto limpio el filtro",
            "product_token": product.public_token,
        },
    )

    assert captured["product_id"] == product.id
