from langchain_openai import OpenAIEmbeddings

from nomanual.core import config

settings = config.get_settings()

embeddings = OpenAIEmbeddings(
    model=settings.embedding_model,
    dimensions=settings.embedding_dimensions,
    api_key=settings.openai_api_key,
)


async def embed_texts(text: list[str]) -> list[list[float]]:

    vector = await embeddings.aembed_documents(texts=text)
    return vector
