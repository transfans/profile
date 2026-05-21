from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from app.core.dependencies import get_current_user


def _build_profile(current_user_id, *, is_creator=False):
    return SimpleNamespace(
        user_id=current_user_id,
        display_name="display_name",
        bio="bio",
        avatar_url=None,
        is_creator=is_creator,
        email="profile@example.com",
        tiers=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_get_profiles_me_requires_auth(profile_client):
    response = await profile_client.get("/profiles/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_profiles_me_updates_profile(monkeypatch, profile_client, profile_app: FastAPI, current_user):
    from app.api import profiles as profiles_api

    async def override_get_current_user():
        return current_user

    profile_app.dependency_overrides[get_current_user] = override_get_current_user

    monkeypatch.setattr(
        profiles_api,
        "get_or_create_profile",
        AsyncMock(return_value=_build_profile(current_user.id, is_creator=False)),
    )
    monkeypatch.setattr(
        profiles_api,
        "update_profile",
        AsyncMock(return_value=_build_profile(current_user.id, is_creator=False)),
    )
    monkeypatch.setattr(profiles_api, "publish_event", AsyncMock())

    response = await profile_client.patch(
        "/profiles/me",
        json={"display_name": "updated_name", "bio": "updated bio"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == str(current_user.id)
    assert payload["display_name"] == "display_name"
    assert payload["is_creator"] is False


@pytest.mark.asyncio
async def test_activate_creator_success(monkeypatch, profile_client, profile_app: FastAPI, current_user):
    from app.api import creators as creators_api

    async def override_get_current_user():
        return current_user

    profile_app.dependency_overrides[get_current_user] = override_get_current_user

    monkeypatch.setattr(
        creators_api,
        "get_or_create_profile",
        AsyncMock(return_value=_build_profile(current_user.id, is_creator=False)),
    )
    monkeypatch.setattr(creators_api, "activate_creator", AsyncMock())
    monkeypatch.setattr(creators_api, "publish_event", AsyncMock())

    response = await profile_client.patch("/profiles/me/activate-creator")

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_creator"] is True


@pytest.mark.asyncio
async def test_activate_creator_conflict_when_already_creator(
    monkeypatch,
    profile_client,
    profile_app: FastAPI,
    current_user,
):
    from app.api import creators as creators_api

    async def override_get_current_user():
        return current_user

    profile_app.dependency_overrides[get_current_user] = override_get_current_user

    monkeypatch.setattr(
        creators_api,
        "get_or_create_profile",
        AsyncMock(return_value=_build_profile(current_user.id, is_creator=True)),
    )
    monkeypatch.setattr(creators_api, "publish_event", AsyncMock())

    response = await profile_client.patch("/profiles/me/activate-creator")

    assert response.status_code == 409
    assert response.json()["detail"] == "Already a creator"
