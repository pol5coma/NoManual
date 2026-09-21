"""Reading and writing conversations.

The database side of conversation memory, kept away from both the API and the
graph: the endpoint decides what to answer with, the graph decides how to
answer, and this module owns how a thread is stored and how much of it travels.

What the model sees on any turn is the summary plus the last
`conversation_window` messages. The split is recorded per conversation in
`summarised_through`, so nothing is summarised twice and nothing slips between
the notes and the transcript.
"""

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.conversations.summary import update_summary
from nomanual.core.config import get_settings
from nomanual.models import Conversation, Message
from nomanual.models.enums import MessageRole

logger = logging.getLogger(__name__)


async def start(
    session: AsyncSession, tenant_id: UUID, product_id: UUID | None
) -> Conversation:
    """Open a thread about one appliance."""
    conversation = Conversation(tenant_id=tenant_id, product_id=product_id)
    session.add(conversation)
    await session.flush()
    return conversation


async def get(session: AsyncSession, conversation_id: UUID) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


# Long enough to recognise a thread, short enough for a sidebar row.
TITLE_MAX_CHARS = 80


def _title_from(question: str) -> str:
    """The first question, trimmed to fit a list."""
    text = " ".join(question.split())
    if len(text) <= TITLE_MAX_CHARS:
        return text
    return text[: TITLE_MAX_CHARS - 1].rstrip() + "…"


async def list_for_product(
    session: AsyncSession, product_id: UUID
) -> list[tuple[Conversation, int, object]]:
    """Threads about one appliance, most recently active first.

    The message count and the time of the last message come from a grouped
    join rather than from loading every thread's messages: a sidebar must not
    get slower as the conversations grow.
    """
    rows = await session.execute(
        select(
            Conversation,
            func.count(Message.id),
            func.max(Message.created_at),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.product_id == product_id)
        .group_by(Conversation.id)
        .order_by(
            # A thread with no messages yet still has to appear somewhere, so
            # its creation time stands in for activity it does not have.
            func.coalesce(func.max(Message.created_at), Conversation.created_at).desc()
        )
    )
    return [(conversation, count, last) for conversation, count, last in rows.all()]


async def delete(session: AsyncSession, conversation: Conversation) -> None:
    """Remove a thread. Its messages go with it, by ON DELETE CASCADE."""
    await session.delete(conversation)


async def recent_messages(
    session: AsyncSession, conversation_id: UUID, limit: int | None = None
) -> list[Message]:
    """The last messages of a thread, oldest first.

    Ordered by ordinal, not by created_at: the two messages of a turn are
    written in the same transaction and can share a timestamp to the
    microsecond.
    """
    if limit is None:
        limit = get_settings().conversation_window

    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.ordinal.desc())
        .limit(limit)
    )
    return list(reversed(rows.all()))


async def history(
    session: AsyncSession, conversation_id: UUID, limit: int | None = None
) -> list[tuple[str, str]]:
    """The recent turns as (role, content) pairs, ready for a prompt."""
    messages = await recent_messages(session, conversation_id, limit)
    return [(message.role.value, message.content) for message in messages]


async def all_messages(session: AsyncSession, conversation_id: UUID) -> list[Message]:
    """The whole thread, for showing it back to the user."""
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.ordinal)
    )
    return list(rows.all())


async def append_turn(
    session: AsyncSession,
    conversation: Conversation,
    question: str,
    answer: str,
    citations: list[dict] | None = None,
) -> None:
    """Store the user's message and the assistant's reply, in order.

    Both are written together because a turn is not half a turn: a question
    stored without its answer would come back as context that the assistant
    appears to have ignored.
    """
    last = await session.scalar(
        select(func.coalesce(func.max(Message.ordinal), -1)).where(
            Message.conversation_id == conversation.id
        )
    )

    # The first question names the thread.
    if conversation.title is None:
        conversation.title = _title_from(question)

    session.add_all(
        [
            Message(
                conversation_id=conversation.id,
                ordinal=last + 1,
                role=MessageRole.USER,
                content=question,
            ),
            Message(
                conversation_id=conversation.id,
                ordinal=last + 2,
                role=MessageRole.ASSISTANT,
                content=answer,
                citations=citations or [],
            ),
        ]
    )
    await session.flush()


async def maybe_summarise(session: AsyncSession, conversation: Conversation) -> None:
    """Fold everything older than the window into the summary.

    Only runs when a conversation has outgrown its window, which most never do.
    That is the whole point: a summary on every turn would double the cost of
    the short conversations that make up almost all of the traffic.
    """
    window = get_settings().conversation_window

    total = await session.scalar(
        select(func.count()).where(Message.conversation_id == conversation.id)
    )
    # Messages already summarised, plus the ones we still send verbatim.
    if total - conversation.summarised_through <= window:
        return

    # Everything between the notes and the window: old enough to be dropped
    # from the transcript, new enough that the notes do not cover it yet.
    pending = await session.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.ordinal >= conversation.summarised_through,
            Message.ordinal < total - window,
        )
        .order_by(Message.ordinal)
    )
    messages = list(pending.all())
    if not messages:
        return

    transcript = "\n".join(f"{m.role.value}: {m.content}" for m in messages)
    conversation.summary = await update_summary(conversation.summary, transcript)
    conversation.summarised_through = messages[-1].ordinal + 1
    await session.flush()
