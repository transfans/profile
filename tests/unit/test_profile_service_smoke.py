from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import profile_service


@pytest.mark.asyncio
async def test_get_or_create_profile_returns_existing(monkeypatch, fake_db):
    existing = SimpleNamespace(user_id=uuid4(), display_name="existing", email="existing@example.com", tiers=[])

    async def fake_get_profile_by_user_id(_db, _user_id):
        return existing

    monkeypatch.setattr(profile_service, "get_profile_by_user_id", fake_get_profile_by_user_id)

    result = await profile_service.get_or_create_profile(fake_db, existing.user_id, existing.email)

    assert result is existing


@pytest.mark.asyncio
async def test_get_or_create_profile_creates_new(monkeypatch):
    created = []
    call_log: dict[str, int] = {"commit": 0, "refresh": 0}

    async def fake_get_profile_by_user_id(_db, _user_id):
        return None

    class FakeDb:
        def add(self, value):
            created.append(value)

        async def commit(self):
            call_log["commit"] += 1

        async def refresh(self, _profile, attribute_names=None):
            if attribute_names == ["tiers"]:
                call_log["refresh"] += 1

    monkeypatch.setattr(profile_service, "get_profile_by_user_id", fake_get_profile_by_user_id)

    user_id = uuid4()
    db = FakeDb()
    profile = await profile_service.get_or_create_profile(db, user_id, "new_user@example.com")

    assert profile.user_id == user_id
    assert profile.display_name == "new_user"
    assert len(created) == 1
    assert call_log["commit"] == 1
    assert call_log["refresh"] == 1


@pytest.mark.asyncio
async def test_update_profile_updates_fields(fake_db):
    profile = SimpleNamespace(
        display_name="before",
        bio="before bio",
        updated_at=datetime.now(UTC),
        tiers=[],
    )

    commit_calls = 0
    refresh_calls = 0

    async def fake_commit():
        nonlocal commit_calls
        commit_calls += 1

    async def fake_refresh(_profile, attribute_names=None):
        nonlocal refresh_calls
        if attribute_names == ["tiers"]:
            refresh_calls += 1

    fake_db.commit = fake_commit
    fake_db.refresh = fake_refresh

    updated = await profile_service.update_profile(
        fake_db,
        profile,
        display_name="after",
        bio="after bio",
    )

    assert updated.display_name == "after"
    assert updated.bio == "after bio"
    assert commit_calls == 1
    assert refresh_calls == 1
