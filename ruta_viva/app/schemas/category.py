from pydantic import BaseModel, ConfigDict


class CategoryResponse(BaseModel):
    id: int
    name: str
    icon_url: str | None = None
    parent_id: int | None = None
    model_config = ConfigDict(from_attributes=True)
