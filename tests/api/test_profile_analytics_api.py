from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from app.core.dependencies import CurrentUser, get_current_user


@pytest.mark.asyncio
async def test_creator_analytics_denies_non_owner_non_admin(profile_client, profile_app: FastAPI):
    from app.api import analytics as analytics_api

    creator_id = uuid4()

    async def override_get_current_user():
        return CurrentUser(id=uuid4(), role="user", email="other@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user
    analytics_api.analytics_get = AsyncMock(return_value={"value": 1})

    response = await profile_client.get(f"/analytics/creator/{creator_id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_creator_analytics_returns_unavailable_payload_when_backend_fails(
    profile_client,
    profile_app: FastAPI,
):
    from app.api import analytics as analytics_api

    creator_id = uuid4()

    async def override_get_current_user():
        return CurrentUser(id=creator_id, role="creator", email="creator@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user
    analytics_api.analytics_get = AsyncMock(return_value=None)

    response = await profile_client.get(
        f"/analytics/creator/{creator_id}",
        headers={"X-Request-ID": "req-123"},
    )

    assert response.status_code == 200
    assert response.json()["analytics_unavailable"] is True
