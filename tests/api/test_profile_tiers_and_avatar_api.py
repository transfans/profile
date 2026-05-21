from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from app.core.dependencies import CurrentUser, get_current_user, require_creator


@pytest.mark.asyncio
async def test_create_tier_rejects_non_creator_profile(monkeypatch, profile_client, profile_app: FastAPI):
    from app.api import tiers as tiers_api

    creator_id = uuid4()

    async def override_require_creator():
        return CurrentUser(id=creator_id, role="creator", email="creator@example.com")

    profile_app.dependency_overrides[require_creator] = override_require_creator
    monkeypatch.setattr(
        tiers_api,
        "get_or_create_profile",
        AsyncMock(return_value=SimpleNamespace(is_creator=False)),
    )

    response = await profile_client.post(
        "/tiers",
        json={"name": "Gold", "description": "Gold tier", "price": 10},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not a creator"


@pytest.mark.asyncio
async def test_update_tier_rejects_non_owner(monkeypatch, profile_client, profile_app: FastAPI):
    from app.api import tiers as tiers_api

    current_user_id = uuid4()
    tier_id = uuid4()

    async def override_require_creator():
        return CurrentUser(id=current_user_id, role="creator", email="creator@example.com")

    profile_app.dependency_overrides[require_creator] = override_require_creator
    monkeypatch.setattr(
        tiers_api,
        "get_tier_by_id",
        AsyncMock(return_value=SimpleNamespace(id=tier_id, creator_id=uuid4())),
    )

    response = await profile_client.patch(f"/tiers/{tier_id}", json={"name": "Updated"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Not the owner of this tier"


@pytest.mark.asyncio
async def test_avatar_upload_rejects_invalid_content_type(profile_client, profile_app: FastAPI):
    user_id = uuid4()

    async def override_get_current_user():
        return CurrentUser(id=user_id, role="user", email="user@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user

    response = await profile_client.post(
        "/profiles/me/avatar",
        files={"file": ("avatar.txt", b"not-image", "text/plain")},
    )

    assert response.status_code == 415


@pytest.mark.asyncio
async def test_avatar_upload_success(monkeypatch, profile_client, profile_app: FastAPI):
    from app.api import avatars as avatars_api

    user_id = uuid4()
    profile = SimpleNamespace(avatar_url=None, is_creator=False)

    async def override_get_current_user():
        return CurrentUser(id=user_id, role="user", email="user@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user
    monkeypatch.setattr(avatars_api, "get_or_create_profile", AsyncMock(return_value=profile))
    monkeypatch.setattr(avatars_api, "upload_avatar", AsyncMock(return_value=f"{user_id}/avatar.png"))
    monkeypatch.setattr(avatars_api, "set_avatar_url", AsyncMock())
    monkeypatch.setattr(avatars_api, "get_avatar_presigned_url", AsyncMock(return_value="http://signed-url"))

    response = await profile_client.post(
        "/profiles/me/avatar",
        files={"file": ("avatar.png", b"\x89PNGfake", "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["avatar_url"] == "http://signed-url"


@pytest.mark.asyncio
async def test_get_my_subscriptions_returns_serialized_items(monkeypatch, profile_client, profile_app: FastAPI):
    from app.api import subscriptions as subscriptions_api
    from app.models.enums import SubscriptionStatus

    fan_id = uuid4()
    creator_id = uuid4()
    tier_id = uuid4()

    async def override_get_current_user():
        return CurrentUser(id=fan_id, role="user", email="fan@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user
    monkeypatch.setattr(
        subscriptions_api,
        "get_fan_subscriptions",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=uuid4(),
                    creator_id=creator_id,
                    tier=SimpleNamespace(id=tier_id, name="Gold", price=20.0),
                    status=SubscriptionStatus.active,
                    expires_at=datetime.now(UTC),
                )
            ]
        ),
    )

    response = await profile_client.get("/subscriptions/my")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["creator_id"] == str(creator_id)
