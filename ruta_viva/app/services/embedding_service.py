from __future__ import annotations

from openai import AsyncOpenAI

from app.core.config import settings


class OpenAIEmbeddingService:
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required to generate embeddings.")

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "text-embedding-3-small"

    async def get_embedding(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
            encoding_format="float",
        )
        return response.data[0].embedding


_embedding_service: OpenAIEmbeddingService | None = None


def get_embedding_service() -> OpenAIEmbeddingService:
    global _embedding_service

    if _embedding_service is None:
        _embedding_service = OpenAIEmbeddingService()

    return _embedding_service
