from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from app.core.dependencies import CurrentUser, get_current_user


@pytest.mark.asyncio
async def test_activate_creator_publishes_cross_service_events(monkeypatch, profile_client, profile_app: FastAPI):
    from app.api import creators as creators_api

    creator_id = uuid4()

    async def override_get_current_user():
        return CurrentUser(id=creator_id, role="user", email="creator@example.com")

    profile_app.dependency_overrides[get_current_user] = override_get_current_user

    monkeypatch.setattr(
        creators_api,
        "get_or_create_profile",
        AsyncMock(
            return_value=SimpleNamespace(
                user_id=creator_id,
                display_name="Creator",
                bio=None,
                avatar_url=None,
                is_creator=False,
                email="creator@example.com",
                tiers=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        ),
    )
    monkeypatch.setattr(creators_api, "activate_creator", AsyncMock())
    publish_event = AsyncMock()
    monkeypatch.setattr(creators_api, "publish_event", publish_event)

    response = await profile_client.patch("/profiles/me/activate-creator")

    assert response.status_code == 200
    assert publish_event.await_count == 2

    first_event, first_payload = publish_event.await_args_list[0].args
    second_event, second_payload = publish_event.await_args_list[1].args
    assert first_event == "creator.activated"
    assert first_payload["user_id"] == str(creator_id)
    assert second_event == "creator.created"
    assert second_payload["creator_id"] == str(creator_id)
