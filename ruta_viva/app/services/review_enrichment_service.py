from __future__ import annotations

import logging
from uuid import UUID

from app.db.session import AsyncSessionLocal
from app.models.review import Review
from app.models.tourist_profile import TouristProfile
from app.services.embedding_service import OpenAIEmbeddingService


PROFILE_DECAY_WEIGHT = 0.9
REVIEW_SIGNAL_WEIGHT = 0.1
logger = logging.getLogger("ruta_viva.reviews")


def _update_interests_embedding(
    current_embedding: list[float] | None,
    review_embedding: list[float],
) -> list[float]:
    if current_embedding is None:
        return review_embedding

    if len(current_embedding) != len(review_embedding):
        raise ValueError(
            "Cannot update tourist interests embedding because current profile and review embedding dimensions differ."
        )

    return [
        (current_value * PROFILE_DECAY_WEIGHT) + (review_value * REVIEW_SIGNAL_WEIGHT)
        for current_value, review_value in zip(current_embedding, review_embedding, strict=True)
    ]


async def generate_review_embedding_and_update_profile(
    review_id: UUID,
    embedding_service: OpenAIEmbeddingService,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            review = await db.get(Review, review_id)
            if review is None:
                return

            if review.text_embedding is not None:
                return

            if not review.text_content:
                return

            tourist_profile = await db.get(TouristProfile, review.tourist_id)
            if tourist_profile is None:
                return

            review_embedding = await embedding_service.get_embedding(review.text_content)

            review.text_embedding = review_embedding
            tourist_profile.interests_embedding = _update_interests_embedding(
                current_embedding=tourist_profile.interests_embedding,
                review_embedding=review_embedding,
            )

            await db.commit()
    except Exception:
        logger.exception("Failed to enrich review %s with embedding in background task.", review_id)
