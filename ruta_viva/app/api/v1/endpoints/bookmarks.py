from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.bookmark_repository import BookmarkRepository
from app.schemas.bookmark import BookmarkResponse, BookmarkStatusResponse
from app.schemas.poi import POIResponse


router = APIRouter(tags=["bookmarks"])
bookmark_repository = BookmarkRepository()


def _ensure_tourist_user(current_user: User) -> None:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can manage bookmarks.",
        )


@router.get("/", response_model=list[POIResponse])
async def list_my_bookmarks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[POIResponse]:
    _ensure_tourist_user(current_user)
    return await bookmark_repository.list_bookmarked_pois(db, tourist_id=current_user.id)


@router.get("/{poi_id}", response_model=BookmarkStatusResponse)
async def get_bookmark_status(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookmarkStatusResponse:
    _ensure_tourist_user(current_user)
    return BookmarkStatusResponse(
        poi_id=poi_id,
        is_bookmarked=await bookmark_repository.is_bookmarked(db, current_user.id, poi_id),
    )


@router.post("/{poi_id}", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookmarkResponse:
    _ensure_tourist_user(current_user)
    try:
        return await bookmark_repository.create_bookmark(db, tourist_id=current_user.id, poi_id=poi_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{poi_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _ensure_tourist_user(current_user)
    await bookmark_repository.delete_bookmark(db, tourist_id=current_user.id, poi_id=poi_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
