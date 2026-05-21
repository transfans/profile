import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_creator
from app.db.session import get_db
from app.events.publisher import publish_event
from app.metrics import tiers_created_total, tiers_updated_total
from app.schemas.tier import TierCreate, TierResponse, TierUpdate
from app.services.profile_service import get_or_create_profile
from app.services.tier_service import create_tier, get_tier_by_id, update_tier

router = APIRouter(prefix="/tiers", tags=["tiers"])


@router.post("", response_model=TierResponse, status_code=status.HTTP_201_CREATED)
async def create_new_tier(
    body: TierCreate,
    current_user: CurrentUser = Depends(require_creator),
    db: AsyncSession = Depends(get_db),
) -> TierResponse:
    email = current_user.email or f"{current_user.id}@unknown"
    profile = await get_or_create_profile(db, current_user.id, email)

    if not profile.is_creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a creator",
        )

    tier = await create_tier(
        db,
        creator_id=current_user.id,
        name=body.name,
        description=body.description,
        price=body.price,
    )
    tiers_created_total.inc()
    await publish_event("tier.created", {"tier_id": str(tier.id), "creator_id": str(current_user.id)})
    return TierResponse.model_validate(tier)


@router.patch("/{tier_id}", response_model=TierResponse)
async def update_existing_tier(
    tier_id: uuid.UUID,
    body: TierUpdate,
    current_user: CurrentUser = Depends(require_creator),
    db: AsyncSession = Depends(get_db),
) -> TierResponse:
    tier = await get_tier_by_id(db, tier_id)
    if not tier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")

    if tier.creator_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the owner of this tier")

    tier = await update_tier(
        db,
        tier,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
    )
    tiers_updated_total.inc()
    await publish_event("tier.updated", {"tier_id": str(tier.id), "creator_id": str(tier.creator_id)})
    return TierResponse.model_validate(tier)
