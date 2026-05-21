import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import SubscriptionStatus
from app.models.subscription import Subscription


async def check_subscription(db: AsyncSession, fan_id: uuid.UUID, creator_id: uuid.UUID) -> dict:
    result = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.fan_id == fan_id,
                Subscription.creator_id == creator_id,
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > datetime.now(UTC),
            )
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        return {"has_access": True, "tier_id": str(sub.tier_id)}
    return {"has_access": False, "tier_id": None}


async def create_subscription(
    db: AsyncSession,
    fan_id: uuid.UUID,
    creator_id: uuid.UUID,
    tier_id: uuid.UUID,
    expires_at: datetime,
) -> Subscription:
    subscription = Subscription(
        fan_id=fan_id,
        creator_id=creator_id,
        tier_id=tier_id,
        expires_at=expires_at,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def get_subscription_by_id(db: AsyncSession, subscription_id: uuid.UUID) -> Subscription | None:
    result = await db.execute(select(Subscription).where(Subscription.id == subscription_id))
    return result.scalar_one_or_none()


async def deactivate_subscription(db: AsyncSession, subscription: Subscription) -> Subscription:
    subscription.status = SubscriptionStatus.cancelled
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def get_fan_subscriptions(
    db: AsyncSession, fan_id: uuid.UUID, status_filter: str = "active"
) -> list[Subscription]:
    query = select(Subscription).where(Subscription.fan_id == fan_id).options(selectinload(Subscription.tier))

    if status_filter == "active":
        query = query.where(Subscription.status == SubscriptionStatus.active)
    elif status_filter == "cancelled":
        query = query.where(Subscription.status == SubscriptionStatus.cancelled)

    result = await db.execute(query.order_by(Subscription.created_at.desc()))
    return list(result.scalars().all())


async def get_creator_subscribers(
    db: AsyncSession, creator_id: uuid.UUID, page: int = 1, limit: int = 20
) -> tuple[list[Subscription], int]:
    count_query = (
        select(func.count())
        .select_from(Subscription)
        .where(
            and_(
                Subscription.creator_id == creator_id,
                Subscription.status == SubscriptionStatus.active,
            )
        )
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * limit
    query = (
        select(Subscription)
        .where(
            and_(
                Subscription.creator_id == creator_id,
                Subscription.status == SubscriptionStatus.active,
            )
        )
        .options(selectinload(Subscription.tier))
        .order_by(Subscription.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def count_active_subscriptions(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(Subscription).where(Subscription.status == SubscriptionStatus.active)
    )
    return result.scalar() or 0


async def expire_overdue_subscriptions(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    result = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at < now,
            )
        )
    )
    expired = list(result.scalars().all())
    for sub in expired:
        sub.status = SubscriptionStatus.expired
    if expired:
        await db.commit()
    return len(expired)
