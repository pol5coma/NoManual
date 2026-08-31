from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.core.config import get_settings
from nomanual.models.base import Base, TimestampMixin, UUIDMixin

EMBEDDING_DIMENSIONS = get_settings().embedding_dimensions


class Chunk(UUIDMixin, TimestampMixin, Base):
    """A retrievable fragment of a manual.

    Page numbers are kept so an answer can say "page 34" instead of quoting
    text with no traceable origin. That citation is what makes the answer
    verifiable, which is the whole difference from a generic chatbot.
    """

    __tablename__ = "chunk"
    __table_args__ = (
        # Cosine distance, matching the <=> operator used at query time.
        Index(
            "ix_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Lexical search: error codes like E18 and E19 sit almost on top of
        # each other in embedding space but mean completely different things.
        Index("ix_chunk_content_tsv", "content_tsv", postgresql_using="gin"),
        Index("ix_chunk_applies_to", "applies_to", postgresql_using="gin"),
    )

    manual_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("manual.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Denormalised on purpose: every retrieval filters by tenant, and we do not
    # want a join back to manual on the hot path.
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_from: Mapped[int] = mapped_column(Integer, nullable=False)
    page_to: Mapped[int] = mapped_column(Integer, nullable=False)

    # "4.2 Child lock" - carried into the embedding so a fragment that reads
    # "hold the button for 3 seconds" is not stranded without context.
    section_path: Mapped[str | None] = mapped_column(String(512))

    # Detected per chunk, not per manual: a single PDF often carries five
    # languages, one after another.
    language: Mapped[str] = mapped_column(String(8), nullable=False, index=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 'simple' rather than a language configuration: no stemming, so error
    # codes survive tokenisation intact.
    content_tsv = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', content)", persisted=True),
        nullable=True,
    )

    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=False
    )

    # Which models this fragment actually applies to. NULL means it applies to
    # every product the manual covers. This is what stops us explaining a
    # feature the user's appliance does not have.
    applies_to: Mapped[list[UUID] | None] = mapped_column(ARRAY(PgUUID(as_uuid=True)))

    # The sentence the applicability was derived from, kept for debugging and
    # for showing our work: "only on models with a digital display".
    applies_condition: Mapped[str | None] = mapped_column(Text)
