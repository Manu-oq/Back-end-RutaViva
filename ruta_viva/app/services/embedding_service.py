from __future__ import annotations

import time
import asyncio

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


class GlobalEmbeddingCache:
    """Cache de embeddings a nivel de proceso con TTL. Sobrevive entre requests."""

    def __init__(self, service: OpenAIEmbeddingService, ttl_seconds: int = 900) -> None:
        self._service = service
        self._cache: dict[str, tuple[float, list[float]]] = {}
        self._ttl = ttl_seconds
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_embedding(self, text: str) -> list[float]:
        now = time.monotonic()
        if text in self._cache:
            expires, emb = self._cache[text]
            if now < expires:
                return emb

        lock = self._locks.setdefault(text, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            if text in self._cache:
                expires, emb = self._cache[text]
                if now < expires:
                    return emb

            emb = await self._service.get_embedding(text)
            self._cache[text] = (now + self._ttl, emb)
            self._locks.pop(text, None)
            return emb


class EmbeddingCache:
    """Cache request-scoped que delega al GlobalEmbeddingCache para compartir entre requests."""

    def __init__(self, service: OpenAIEmbeddingService) -> None:
        self._service = service
        self._local: dict[str, list[float]] = {}
        self._global = get_global_embedding_cache()

    async def get_embedding(self, text: str) -> list[float]:
        if text not in self._local:
            self._local[text] = await self._global.get_embedding(text)
        return self._local[text]


_global_embedding_cache: GlobalEmbeddingCache | None = None


def get_global_embedding_cache() -> GlobalEmbeddingCache:
    global _global_embedding_cache
    if _global_embedding_cache is None:
        _global_embedding_cache = GlobalEmbeddingCache(OpenAIEmbeddingService())
    return _global_embedding_cache


_embedding_service: OpenAIEmbeddingService | None = None


def get_embedding_service() -> OpenAIEmbeddingService:
    global _embedding_service

    if _embedding_service is None:
        _embedding_service = OpenAIEmbeddingService()

    return _embedding_service
