import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.services.analytics_client import analytics_get
from app.services.tier_service import get_tier_by_id

router = APIRouter(prefix="/analytics", tags=["analytics"])

_UNAVAILABLE: dict[str, Any] = {"analytics_unavailable": True, "data": None}


class AnalyticsProxyResponse(BaseModel):
    analytics_unavailable: bool = False
    data: Any | None = None


def _assert_own_or_admin(current_user: CurrentUser, target_id: uuid.UUID) -> None:
    if current_user.id != target_id and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


@router.get("/creator/{creator_id}", response_model=AnalyticsProxyResponse)
async def get_creator_analytics(
    creator_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalyticsProxyResponse:
    _assert_own_or_admin(current_user, creator_id)
    data = await analytics_get(
        f"/analytics/creator/{creator_id}",
        request_id=_request_id(request),
    )
    if data is None:
        return AnalyticsProxyResponse(**_UNAVAILABLE)
    return AnalyticsProxyResponse(data=data)


@router.get("/creator/{creator_id}/subscriptions", response_model=AnalyticsProxyResponse)
async def get_creator_subscriptions_analytics(
    creator_id: uuid.UUID,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalyticsProxyResponse:
    _assert_own_or_admin(current_user, creator_id)
    data = await analytics_get(
        f"/analytics/creator/{creator_id}/subscriptions",
        params={"offset": offset, "limit": limit},
        request_id=_request_id(request),
    )
    if data is None:
        return AnalyticsProxyResponse(**_UNAVAILABLE)
    return AnalyticsProxyResponse(data=data)


@router.get("/tier/{tier_id}", response_model=AnalyticsProxyResponse)
async def get_tier_analytics(
    tier_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalyticsProxyResponse:
    tier = await get_tier_by_id(db, tier_id)
    if tier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    _assert_own_or_admin(current_user, tier.creator_id)
    data = await analytics_get(
        f"/analytics/tier/{tier_id}",
        request_id=_request_id(request),
    )
    if data is None:
        return AnalyticsProxyResponse(**_UNAVAILABLE)
    return AnalyticsProxyResponse(data=data)


@router.get("/subscriber/{subscriber_id}", response_model=AnalyticsProxyResponse)
async def get_subscriber_analytics(
    subscriber_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalyticsProxyResponse:
    _assert_own_or_admin(current_user, subscriber_id)
    data = await analytics_get(
        f"/analytics/subscriber/{subscriber_id}",
        request_id=_request_id(request),
    )
    if data is None:
        return AnalyticsProxyResponse(**_UNAVAILABLE)
    return AnalyticsProxyResponse(data=data)


@router.get("/overview", response_model=AnalyticsProxyResponse)
async def get_analytics_overview(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalyticsProxyResponse:
    data = await analytics_get(
        "/analytics/overview",
        request_id=_request_id(request),
    )
    if data is None:
        return AnalyticsProxyResponse(**_UNAVAILABLE)
    return AnalyticsProxyResponse(data=data)
