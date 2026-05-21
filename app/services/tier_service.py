import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tier import Tier


async def create_tier(
    db: AsyncSession,
    creator_id: uuid.UUID,
    name: str,
    description: str,
    price: float,
) -> Tier:
    tier = Tier(
        creator_id=creator_id,
        name=name,
        description=description,
        price=price,
    )
    db.add(tier)
    await db.commit()
    await db.refresh(tier)
    return tier


async def get_tier_by_id(db: AsyncSession, tier_id: uuid.UUID) -> Tier | None:
    result = await db.execute(select(Tier).where(Tier.id == tier_id))
    return result.scalar_one_or_none()


async def get_tiers_by_creator(db: AsyncSession, creator_id: uuid.UUID) -> list[Tier]:
    result = await db.execute(select(Tier).where(Tier.creator_id == creator_id).order_by(Tier.created_at))
    return list(result.scalars().all())


async def update_tier(
    db: AsyncSession,
    tier: Tier,
    name: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> Tier:
    if name is not None:
        tier.name = name
    if description is not None:
        tier.description = description
    if is_active is not None:
        tier.is_active = is_active
    await db.commit()
    await db.refresh(tier)
    return tier
