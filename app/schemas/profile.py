import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tier import TierResponse


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=100)
    bio: str | None = None


class ProfilePublicResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    bio: str | None
    avatar_url: str | None
    is_creator: bool
    tiers: list[TierResponse] = []

    model_config = {"from_attributes": True}


class ProfileMeResponse(ProfilePublicResponse):
    email: str

    model_config = {"from_attributes": True}


class AvatarResponse(BaseModel):
    avatar_url: str


class CreatorListItem(BaseModel):
    user_id: uuid.UUID
    display_name: str
    avatar_url: str | None
    bio: str | None

    model_config = {"from_attributes": True}


class CreatorListResponse(BaseModel):
    items: list[CreatorListItem]
    total: int
    page: int


class ActivateCreatorResponse(BaseModel):
    is_creator: bool
    message: str
