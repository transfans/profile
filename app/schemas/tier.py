import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TierCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: str
    price: float = Field(..., gt=0)


class TierUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    description: str | None = None
    is_active: bool | None = None


class TierResponse(BaseModel):
    id: uuid.UUID
    creator_id: uuid.UUID
    name: str
    description: str
    price: float
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TierInternalResponse(BaseModel):
    id: uuid.UUID
    creator_id: uuid.UUID
    price: float
    is_active: bool

    model_config = {"from_attributes": True}
