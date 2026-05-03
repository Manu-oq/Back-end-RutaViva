from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import get_current_user
from app.models.user import User
from app.services.image_service import save_image


router = APIRouter(tags=["media"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    url = await save_image(file)
    return {"url": url}
