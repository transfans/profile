import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.events.publisher import publish_event
from app.schemas.profile import ProfileMeResponse, ProfilePublicResponse, ProfileUpdate
from app.services.avatar_service import get_avatar_presigned_url
from app.services.profile_service import get_or_create_profile, get_profile_by_user_id, update_profile

router = APIRouter(prefix="/profiles", tags=["profiles"])


async def _resolve_avatar_url(avatar_url: str | None) -> str | None:
    if not avatar_url:
        return None
    return await get_avatar_presigned_url(avatar_url)


@router.get("/me", response_model=ProfileMeResponse)
async def get_my_profile(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = current_user.email or f"{current_user.id}@unknown"
    profile = await get_or_create_profile(db, current_user.id, email)
    presigned = await _resolve_avatar_url(profile.avatar_url)

    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "avatar_url": presigned,
        "is_creator": profile.is_creator,
        "email": profile.email,
        "tiers": profile.tiers,
    }


@router.get("/{user_id}", response_model=ProfilePublicResponse)
async def get_profile(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile = await get_profile_by_user_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    presigned = await _resolve_avatar_url(profile.avatar_url)

    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "avatar_url": presigned,
        "is_creator": profile.is_creator,
        "tiers": profile.tiers,
    }


@router.patch("/me", response_model=ProfileMeResponse)
async def update_my_profile(
    body: ProfileUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = current_user.email or f"{current_user.id}@unknown"
    profile = await get_or_create_profile(db, current_user.id, email)
    profile = await update_profile(db, profile, display_name=body.display_name, bio=body.bio)

    await publish_event("profile.updated", {"user_id": str(current_user.id)})
    if profile.is_creator:
        await publish_event("creator.updated", {"creator_id": str(current_user.id)})

    presigned = await _resolve_avatar_url(profile.avatar_url)

    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "avatar_url": presigned,
        "is_creator": profile.is_creator,
        "email": profile.email,
        "tiers": profile.tiers,
    }
