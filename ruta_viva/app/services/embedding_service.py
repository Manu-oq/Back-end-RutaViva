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

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
            encoding_format="float",
        )
        return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]


class EmbeddingCache:
    def __init__(self, service: OpenAIEmbeddingService) -> None:
        self._service = service
        self._cache: dict[str, list[float]] = {}

    async def get_embedding(self, text: str) -> list[float]:
        if text not in self._cache:
            self._cache[text] = await self._service.get_embedding(text)
        return self._cache[text]


_embedding_service: OpenAIEmbeddingService | None = None


def get_embedding_service() -> OpenAIEmbeddingService:
    global _embedding_service

    if _embedding_service is None:
        _embedding_service = OpenAIEmbeddingService()

    return _embedding_service
