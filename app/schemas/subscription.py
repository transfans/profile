import uuid
from datetime import datetime

from pydantic import BaseModel


class SubscriptionCreate(BaseModel):
    fan_id: uuid.UUID
    creator_id: uuid.UUID
    tier_id: uuid.UUID
    expires_at: datetime


class SubscriptionCheckResponse(BaseModel):
    has_access: bool
    tier_id: str | None = None


class SubscriptionCreatedResponse(BaseModel):
    subscription_id: uuid.UUID


class TierSummary(BaseModel):
    id: uuid.UUID
    name: str
    price: float

    model_config = {"from_attributes": True}


class FanSubscriptionItem(BaseModel):
    id: uuid.UUID
    creator_id: uuid.UUID
    tier: TierSummary
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}


class SubscriberItem(BaseModel):
    fan_id: uuid.UUID
    display_name: str | None = None
    tier: TierSummary
    since: datetime


class SubscribersResponse(BaseModel):
    items: list[SubscriberItem]
    total: int
