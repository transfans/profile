from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_creator
from app.db.session import get_db
from app.schemas.subscription import FanSubscriptionItem, SubscriberItem, SubscribersResponse, TierSummary
from app.services.profile_service import get_profile_by_user_id
from app.services.subscription_service import get_creator_subscribers, get_fan_subscriptions

router = APIRouter(tags=["subscriptions"])


@router.get("/subscriptions/my", response_model=list[FanSubscriptionItem])
async def get_my_subscriptions(
    status_filter: str = Query("active", alias="status", pattern="^(active|cancelled|all)$"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FanSubscriptionItem]:
    subs = await get_fan_subscriptions(db, current_user.id, status_filter)

    return [
        FanSubscriptionItem(
            id=sub.id,
            creator_id=sub.creator_id,
            tier=TierSummary(id=sub.tier.id, name=sub.tier.name, price=float(sub.tier.price)),
            status=sub.status.value,
            expires_at=sub.expires_at,
        )
        for sub in subs
    ]


@router.get("/subscribers/my", response_model=SubscribersResponse)
async def get_my_subscribers(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: CurrentUser = Depends(require_creator),
    db: AsyncSession = Depends(get_db),
) -> SubscribersResponse:
    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile or not profile.is_creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a creator",
        )

    subs, total = await get_creator_subscribers(db, current_user.id, page, limit)

    items = []
    for sub in subs:
        fan_profile = await get_profile_by_user_id(db, sub.fan_id)
        display_name = fan_profile.display_name if fan_profile else None

        items.append(
            SubscriberItem(
                fan_id=sub.fan_id,
                display_name=display_name,
                tier=TierSummary(id=sub.tier.id, name=sub.tier.name, price=float(sub.tier.price)),
                since=sub.created_at,
            )
        )

    return SubscribersResponse(items=items, total=total)
