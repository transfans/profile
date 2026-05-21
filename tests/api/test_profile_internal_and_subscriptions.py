from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from app.core.dependencies import CurrentUser, get_current_user


@pytest.mark.asyncio
async def test_internal_requires_secret_header(profile_client):
    response = await profile_client.get(
        "/internal/subscriptions/check",
        params={"fan_id": str(uuid4()), "creator_id": str(uuid4())},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_internal_check_subscription_success(monkeypatch, profile_client):
    from app.api import internal as internal_api

    monkeypatch.setattr(
        internal_api,
        "check_subscription",
        AsyncMock(return_value={"has_access": True, "tier_id": str(uuid4())}),
    )

    response = await profile_client.get(
        "/internal/subscriptions/check",
        params={"fan_id": str(uuid4()), "creator_id": str(uuid4())},
        headers={"X-Internal-Secret": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["has_access"] is True


@pytest.mark.asyncio
async def test_internal_create_subscription_publishes_event(monkeypatch, profile_client):
    from app.api import internal as internal_api

    sub_id = uuid4()
    monkeypatch.setattr(internal_api, "create_subscription", AsyncMock(return_value=SimpleNamespace(id=sub_id)))
    monkeypatch.setattr(internal_api, "publish_event", AsyncMock())

    response = await profile_client.post(
        "/internal/subscriptions",
        headers={"X-Internal-Secret": "secret"},
        json={
            "fan_id": str(uuid4()),
            "creator_id": str(uuid4()),
            "tier_id": str(uuid4()),
            "expires_at": datetime.now(UTC).isoformat(),
        },
    )

    assert response.status_code == 201
    assert response.json()["subscription_id"] == str(sub_id)


@pytest.mark.asyncio
async def test_get_my_subscribers_requires_creator(profile_client, profile_app: FastAPI):
    async def override_get_current_user():
        return CurrentUser(id=uuid4(), role="user", email="user@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user

    response = await profile_client.get("/subscribers/my")

    assert response.status_code == 403
    assert response.json()["detail"] == "Creator privileges required"


@pytest.mark.asyncio
async def test_get_my_subscribers_success(monkeypatch, profile_client, profile_app: FastAPI):
    from app.api import subscriptions as subscriptions_api

    creator_id = uuid4()
    fan_id = uuid4()
    tier_id = uuid4()

    async def override_get_current_user():
        return CurrentUser(id=creator_id, role="creator", email="creator@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user

    monkeypatch.setattr(
        subscriptions_api,
        "get_profile_by_user_id",
        AsyncMock(
            side_effect=[
                SimpleNamespace(user_id=creator_id, is_creator=True, display_name="Creator"),
                SimpleNamespace(user_id=fan_id, is_creator=False, display_name="Fan"),
            ]
        ),
    )
    monkeypatch.setattr(
        subscriptions_api,
        "get_creator_subscribers",
        AsyncMock(
            return_value=(
                [
                    SimpleNamespace(
                        fan_id=fan_id,
                        tier=SimpleNamespace(id=tier_id, name="Gold", price=15.0),
                        created_at=datetime.now(UTC),
                    )
                ],
                1,
            )
        ),
    )

    response = await profile_client.get("/subscribers/my")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["fan_id"] == str(fan_id)
