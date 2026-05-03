from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    bookmarks,
    categories,
    itineraries,
    media,
    pois,
    reviews,
    users,
)


api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth")
api_router.include_router(users.router, prefix="/users")
api_router.include_router(categories.router, prefix="/categories")
api_router.include_router(pois.router, prefix="/pois")
api_router.include_router(itineraries.router, prefix="/itineraries")
api_router.include_router(reviews.router, prefix="/reviews")
api_router.include_router(media.router, prefix="/media")
api_router.include_router(bookmarks.router, prefix="/bookmarks")
