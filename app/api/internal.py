import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_internal
from app.db.session import get_db
from app.events.publisher import publish_event
from app.schemas.subscription import SubscriptionCheckResponse, SubscriptionCreate, SubscriptionCreatedResponse
from app.schemas.tier import TierInternalResponse
from app.services.subscription_service import (
    check_subscription,
    create_subscription,
    deactivate_subscription,
    get_subscription_by_id,
)
from app.services.tier_service import get_tier_by_id

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal)])


@router.get("/subscriptions/check", response_model=SubscriptionCheckResponse)
async def check_subscription_access(
    fan_id: uuid.UUID = Query(...),
    creator_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionCheckResponse:
    result = await check_subscription(db, fan_id, creator_id)
    return SubscriptionCheckResponse(**result)


@router.post("/subscriptions", response_model=SubscriptionCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_new_subscription(
    body: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
) -> SubscriptionCreatedResponse:
    subscription = await create_subscription(
        db,
        fan_id=body.fan_id,
        creator_id=body.creator_id,
        tier_id=body.tier_id,
        expires_at=body.expires_at,
    )
    await publish_event(
        "subscription.created",
        {
            "subscription_id": str(subscription.id),
            "fan_id": str(body.fan_id),
            "creator_id": str(body.creator_id),
            "tier_id": str(body.tier_id),
        },
    )
    return SubscriptionCreatedResponse(subscription_id=subscription.id)


@router.get("/tiers/{tier_id}", response_model=TierInternalResponse)
async def get_tier_internal(
    tier_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TierInternalResponse:
    tier = await get_tier_by_id(db, tier_id)
    if not tier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    return TierInternalResponse.model_validate(tier)


@router.patch("/subscriptions/{subscription_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_subscription_endpoint(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    subscription = await get_subscription_by_id(db, subscription_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    await deactivate_subscription(db, subscription)
    await publish_event("subscription.cancelled", {"subscription_id": str(subscription_id)})
