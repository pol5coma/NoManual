"""Conversation memory: what is stored, and what the graph gets to see.

The valuable test here is not that messages are saved - it is that a follow-up
reaches retrieval as a question that can actually be searched for. "And how
long does it take?" is clear to a person and empty to a vector search, so the
rewrite is the feature and the rest is bookkeeping around it.
"""

import pytest
from conftest import make_product
from sqlalchemy import func, select

from nomanual.agent import nodes
from nomanual.agent.graph import answer_question
from nomanual.agent.state import Intent, Routing
from nomanual.conversations import service
from nomanual.models import Conversation, Message, QueryLog
from nomanual.models.enums import MessageRole


@pytest.fixture
def captured_question(monkeypatch) -> dict:
    """Record what retrieval was actually asked for."""
    seen = {}

    async def _hybrid_search(query, translated=None, top_k=5, product_id=None):
        seen["query"] = query
        return []

    async def _translate(text, target):
        return text

    monkeypatch.setattr(nodes, "hybrid_search", _hybrid_search)
    monkeypatch.setattr(nodes, "translate_query", _translate)
    return seen


class _FakeModel:
    """Stands in for the shared ChatOpenAI instance.

    Replacing the whole object rather than one of its methods: ChatOpenAI is a
    pydantic model, and pydantic refuses assignment to a field it does not
    declare.
    """

    def __init__(self, reply: str = "", error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.prompts: list[str] = []

    async def ainvoke(self, messages, **kwargs):
        self.prompts.append("\n".join(str(message) for message in messages))
        if self.error is not None:
            raise self.error

        class _Response:
            content = self.reply

        return _Response()

    def with_structured_output(self, schema, **kwargs):
        """The router's path. It has to route somewhere for the graph to run."""

        class _Structured:
            async def ainvoke(_self, messages, **kwargs):
                return Routing(intent=Intent.HOW_TO, reason="fake")

        return _Structured()


@pytest.fixture
def fake_rewrite(monkeypatch):
    """Install a model that returns a fixed rewrite, and record its prompts."""

    def _install(rewritten: str = "", error: Exception | None = None) -> _FakeModel:
        model = _FakeModel(reply=rewritten, error=error)
        monkeypatch.setattr(nodes, "_model", model)
        return model

    return _install


# --- The rewrite ---------------------------------------------------------------


async def test_a_follow_up_is_searched_for_as_a_standalone_question(
    captured_question, fake_rewrite
):
    model = fake_rewrite("¿cuánto tarda el programa con inicio diferido?")

    state = await answer_question(
        "¿y cuánto tarda?",
        history=[
            ("user", "cómo programo el inicio diferido"),
            ("assistant", "Pulsa el botón de inicio diferido y elige las horas."),
        ],
    )

    # What retrieval received, which is the whole point of the node.
    assert (
        captured_question["query"] == "¿cuánto tarda el programa con inicio diferido?"
    )
    # The original question is never overwritten: it is what gets logged and
    # shown back to the user.
    assert state["question"] == "¿y cuánto tarda?"
    assert "inicio diferido" in model.prompts[0]


async def test_the_first_question_is_searched_for_unchanged(
    captured_question, fake_rewrite
):
    """No history, no rewrite: a model call to copy a string is waste."""
    model = fake_rewrite("this rewrite must never be used")

    await answer_question("cada cuánto limpio el filtro")

    assert captured_question["query"] == "cada cuánto limpio el filtro"
    # Only the router called the model. Condensing did not.
    assert model.prompts == []


async def test_a_failed_rewrite_falls_back_to_the_original(
    captured_question, fake_rewrite
):
    """A worse search is recoverable; a 500 in the user's face is not."""
    fake_rewrite(error=RuntimeError("the model is down"))

    await answer_question("¿y cuánto tarda?", history=[("user", "hola")])

    assert captured_question["query"] == "¿y cuánto tarda?"


async def test_the_summary_reaches_the_rewrite(captured_question, fake_rewrite):
    """Notes replace the messages that fell out of the window."""
    model = fake_rewrite("¿cuánto tarda el programa eco?")

    await answer_question(
        "¿y cuánto tarda?",
        summary={"goal": "programar el lavavajillas en modo eco"},
        history=[("user", "vale")],
    )

    assert "modo eco" in model.prompts[0]


# --- Storage -------------------------------------------------------------------


async def test_a_turn_is_stored_as_two_messages_in_order(session):
    product = await make_product(session)
    conversation = await service.start(session, product.tenant_id, product.id)

    await service.append_turn(
        session, conversation, "cada cuánto limpio el filtro", "Cada dos semanas."
    )
    await service.append_turn(session, conversation, "¿y cuánto tarda?", "Un minuto.")
    await session.commit()

    messages = await service.all_messages(session, conversation.id)

    assert [m.ordinal for m in messages] == [0, 1, 2, 3]
    assert [m.role for m in messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert messages[2].content == "¿y cuánto tarda?"


async def test_history_is_cut_to_the_window(session):
    product = await make_product(session)
    conversation = await service.start(session, product.tenant_id, product.id)

    for number in range(5):
        await service.append_turn(session, conversation, f"q{number}", f"a{number}")
    await session.commit()

    history = await service.history(session, conversation.id, limit=4)

    # The most recent four, still in reading order.
    assert history == [
        ("user", "q3"),
        ("assistant", "a3"),
        ("user", "q4"),
        ("assistant", "a4"),
    ]


async def test_a_short_conversation_is_never_summarised(session, monkeypatch):
    async def _update(previous, transcript):
        raise AssertionError("a conversation inside its window must not be summarised")

    monkeypatch.setattr(service, "update_summary", _update)

    product = await make_product(session)
    conversation = await service.start(session, product.tenant_id, product.id)
    for number in range(3):
        await service.append_turn(session, conversation, f"q{number}", f"a{number}")

    await service.maybe_summarise(session, conversation)

    assert conversation.summary is None
    assert conversation.summarised_through == 0


async def test_older_messages_are_folded_into_the_summary(session, monkeypatch):
    """What falls out of the window becomes notes, and only once."""
    transcripts = []

    async def _update(previous, transcript):
        transcripts.append(transcript)
        return {"goal": "clean the filter", "tried": ["opened the lid"]}

    monkeypatch.setattr(service, "update_summary", _update)

    product = await make_product(session)
    conversation = await service.start(session, product.tenant_id, product.id)
    for number in range(5):
        await service.append_turn(session, conversation, f"q{number}", f"a{number}")

    await service.maybe_summarise(session, conversation)

    assert conversation.summary == {
        "goal": "clean the filter",
        "tried": ["opened the lid"],
    }
    # 10 messages and a window of 6: the four oldest are summarised, which is
    # the first two turns. The rest still travel verbatim.
    assert conversation.summarised_through == 4
    assert "q0" in transcripts[0] and "q1" in transcripts[0]
    assert "q2" not in transcripts[0]

    # Running it again with nothing new must not re-summarise.
    await service.maybe_summarise(session, conversation)
    assert len(transcripts) == 1


# --- The endpoint --------------------------------------------------------------


@pytest.fixture
def fake_answer(monkeypatch):
    """Replace the graph, capturing the history it was handed."""
    from nomanual.api import ask as ask_api

    seen = {}

    async def _answer(question, product_id=None, history=None, summary=None):
        seen["question"] = question
        seen["product_id"] = product_id
        seen["history"] = history
        seen["summary"] = summary
        return {
            "answer": f"answer to {question}",
            "intent": "how_to",
            "grounded": True,
            "citations": [],
        }

    monkeypatch.setattr(ask_api, "answer_question", _answer)
    return seen


async def test_asking_without_a_conversation_opens_one(session, client, fake_answer):
    product = await make_product(session)
    await session.commit()

    response = await client.post(
        "/ask",
        json={
            "question": "cada cuánto limpio el filtro",
            "product_id": str(product.id),
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["conversation_id"]

    conversation = await session.get(Conversation, body["conversation_id"])
    assert conversation.product_id == product.id
    assert await session.scalar(select(func.count()).select_from(Message)) == 2
    # The analytics row knows which thread it belongs to.
    log = await session.scalar(select(QueryLog))
    assert str(log.conversation_id) == body["conversation_id"]


async def test_a_second_question_continues_the_same_thread(
    session, client, fake_answer
):
    product = await make_product(session)
    await session.commit()

    first = await client.post(
        "/ask",
        json={"question": "cómo pongo el temporizador", "product_id": str(product.id)},
    )
    conversation_id = first.json()["conversation_id"]

    second = await client.post(
        "/ask",
        json={"question": "¿y cuánto tarda?", "conversation_id": conversation_id},
    )

    assert second.json()["conversation_id"] == conversation_id
    # The graph was given the first turn, and the product came from the thread.
    assert fake_answer["history"] == [
        ("user", "cómo pongo el temporizador"),
        ("assistant", "answer to cómo pongo el temporizador"),
    ]
    assert fake_answer["product_id"] == product.id
    assert await session.scalar(select(func.count()).select_from(Message)) == 4


async def test_a_question_must_name_an_appliance(client):
    """No product and no thread means retrieval across every manual indexed."""
    response = await client.post(
        "/ask", json={"question": "cada cuánto limpio el filtro"}
    )

    assert response.status_code == 422


async def test_an_unknown_conversation_is_a_404(client, fake_answer):
    from uuid import uuid4

    response = await client.post(
        "/ask", json={"question": "hola", "conversation_id": str(uuid4())}
    )

    assert response.status_code == 404


async def test_a_conversation_cannot_be_moved_to_another_product(
    session, client, fake_answer
):
    oven = await make_product(session, brand="Balay", model="3HB4331X0")
    aircon = await make_product(session, brand="Haier", model="AS09FBAHRA")
    await session.commit()

    first = await client.post(
        "/ask", json={"question": "cómo precaliento", "product_id": str(oven.id)}
    )

    response = await client.post(
        "/ask",
        json={
            "question": "y el filtro",
            "product_id": str(aircon.id),
            "conversation_id": first.json()["conversation_id"],
        },
    )

    assert response.status_code == 409


async def test_a_conversation_can_be_read_back(session, client, fake_answer):
    product = await make_product(session)
    await session.commit()

    asked = await client.post(
        "/ask",
        json={
            "question": "cada cuánto limpio el filtro",
            "product_id": str(product.id),
        },
    )
    conversation_id = asked.json()["conversation_id"]

    response = await client.get(f"/conversations/{conversation_id}")

    body = response.json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "cada cuánto limpio el filtro"
    assert body["product_id"] == str(product.id)
