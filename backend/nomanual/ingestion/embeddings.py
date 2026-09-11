from langchain_openai import OpenAIEmbeddings

from nomanual.core import config

settings = config.get_settings()

embeddings = OpenAIEmbeddings(
    model=settings.embedding_model,
    dimensions=settings.embedding_dimensions,
    api_key=settings.openai_api_key,
)


async def embed_texts(text: list[str]) -> list[list[float]]:
    """Embeds text and converts it as vectors. Using OpenAIEmbeddings."""
    vector = await embeddings.aembed_documents(texts=text)
    return vector


# ---------------------------------------------------------------------------
# For reference: the same thing on ChromaDB
# ---------------------------------------------------------------------------
#
# Kept as a comment to show what the Postgres + pgvector path buys us. Chroma
# is the shortest route to a working prototype, and that brevity hides three
# things that matter here.
#
#     import chromadb
#
#     client = chromadb.Client()                  # in memory: gone on exit
#     # client = chromadb.PersistentClient("./chroma")   # survives a restart
#     collection = client.get_or_create_collection("knowledge_base")
#
#     # Indexing. No vectors passed, so Chroma embeds the text itself with its
#     # default model (all-MiniLM-L6-v2, local, 384 dimensions) instead of
#     # calling OpenAI. Free and offline, but markedly weaker and worse across
#     # languages than text-embedding-3-small at 1536 dimensions.
#     collection.add(
#         documents=[chunk.content for chunk in chunks],
#         ids=[f"{manual_id}_{chunk.ordinal}" for chunk in chunks],
#         metadatas=[
#             {"page": chunk.page_from, "lang": chunk.language} for chunk in chunks
#         ],
#     )
#
#     # Querying.
#     results = collection.query(
#         query_texts=["cada cuanto limpio el filtro"], n_results=5
#     )
#
# Why we do not use it:
#
# 1. Persistence. chromadb.Client() lives in memory, which is why the version
#    this is taken from re-parsed the whole PDF on every single question.
#
# 2. Filtering. Metadata is a flat dict and `where` supports equality and a few
#    operators. Our retrieval needs "chunks of this tenant, in this language,
#    whose manual is linked to this product" - and that last one is a join to
#    manual_product. In Chroma you would denormalise it into every document, or
#    over-fetch and filter in Python.
#
# 3. Consistency. Two stores drift apart: delete a manual in Postgres and its
#    vectors stay in Chroma unless you remember to remove them. With pgvector
#    the chunks go in the same transaction, and ON DELETE CASCADE handles it.
#
# What Chroma is genuinely better at: being running in five minutes. For a
# notebook or a spike it is the right tool.
