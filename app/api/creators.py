from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.events.publisher import publish_event
from app.models.profile import Profile
from app.schemas.profile import (
    ActivateCreatorResponse,
    CreatorListItem,
    CreatorListResponse,
)
from app.services.avatar_service import get_avatar_presigned_url
from app.services.profile_service import activate_creator, get_or_create_profile

router = APIRouter(tags=["creators"])


@router.patch("/profiles/me/activate-creator", response_model=ActivateCreatorResponse)
async def activate_creator_mode(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivateCreatorResponse:
    email = current_user.email or f"{current_user.id}@unknown"
    profile = await get_or_create_profile(db, current_user.id, email)

    if profile.is_creator:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already a creator",
        )

    await activate_creator(db, profile)
    await publish_event(
        "creator.activated",
        {"user_id": str(current_user.id)},
    )

    return ActivateCreatorResponse(
        is_creator=True,
        message="Creator mode activated. Please refresh your token.",
    )


@router.get("/creators", response_model=CreatorListResponse)
async def list_creators(
    q: str | None = Query(None, description="Search query"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> CreatorListResponse:
    base_filter = Profile.is_creator.is_(True)

    count_query = select(func.count()).select_from(Profile).where(base_filter)
    if q:
        search = f"%{q}%"
        count_query = count_query.where(Profile.display_name.ilike(search))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * limit
    query = select(Profile).where(base_filter).order_by(Profile.created_at.desc()).offset(offset).limit(limit)
    if q:
        search = f"%{q}%"
        query = query.where(Profile.display_name.ilike(search))

    result = await db.execute(query)
    creators = list(result.scalars().all())

    items = []
    for creator in creators:
        avatar = await get_avatar_presigned_url(creator.avatar_url) if creator.avatar_url else None
        items.append(
            CreatorListItem(
                user_id=creator.user_id,
                display_name=creator.display_name,
                avatar_url=avatar,
                bio=creator.bio,
            )
        )

    return CreatorListResponse(items=items, total=total, page=page)
