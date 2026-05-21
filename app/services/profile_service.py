import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.metrics import profiles_created_total
from app.models.profile import Profile


async def get_profile_by_user_id(db: AsyncSession, user_id: uuid.UUID) -> Profile | None:
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id).options(selectinload(Profile.tiers))
    )
    return result.scalar_one_or_none()


async def get_or_create_profile(db: AsyncSession, user_id: uuid.UUID, email: str) -> Profile:
    profile = await get_profile_by_user_id(db, user_id)
    if profile:
        return profile

    display_name = email.split("@")[0] if email else f"user_{str(user_id)[:8]}"
    profile = Profile(
        user_id=user_id,
        display_name=display_name,
        email=email,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile, attribute_names=["tiers"])
    profiles_created_total.inc()
    return profile


async def update_profile(
    db: AsyncSession,
    profile: Profile,
    display_name: str | None = None,
    bio: str | None = None,
) -> Profile:
    if display_name is not None:
        profile.display_name = display_name
    if bio is not None:
        profile.bio = bio
    profile.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(profile, attribute_names=["tiers"])
    return profile


async def set_avatar_url(db: AsyncSession, profile: Profile, avatar_url: str | None) -> Profile:
    profile.avatar_url = avatar_url
    profile.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(profile)
    return profile


async def activate_creator(db: AsyncSession, profile: Profile) -> Profile:
    profile.is_creator = True
    profile.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(profile, attribute_names=["tiers"])
    return profile
