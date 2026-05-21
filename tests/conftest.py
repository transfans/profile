from collections.abc import AsyncGenerator
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api.analytics import router as analytics_router
from app.api.avatars import router as avatars_router
from app.api.creators import router as creators_router
from app.api.internal import router as internal_router
from app.api.profiles import router as profiles_router
from app.api.subscriptions import router as subscriptions_router
from app.api.tiers import router as tiers_router
from app.core.dependencies import CurrentUser
from app.db.session import get_db
import app.models.tier as _tier_model  # noqa: F401
import app.models.subscription as _subscription_model  # noqa: F401


class DummyDbSession:
    async def execute(self, *_args, **_kwargs):  # pragma: no cover - helper
        return None

    async def commit(self):  # pragma: no cover - helper
        return None

    async def refresh(self, *_args, **_kwargs):  # pragma: no cover - helper
        return None

    def add(self, *_args, **_kwargs):  # pragma: no cover - helper
        return None


@pytest.fixture
def profile_app() -> FastAPI:
    app = FastAPI()
    app.include_router(analytics_router)
    app.include_router(profiles_router)
    app.include_router(avatars_router)
    app.include_router(creators_router)
    app.include_router(tiers_router)
    app.include_router(subscriptions_router)
    app.include_router(internal_router)
    return app


@pytest.fixture
def fake_db() -> DummyDbSession:
    return DummyDbSession()


@pytest.fixture
def current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), role="user", email="profile@example.com")


@pytest.fixture
async def profile_client(
    profile_app: FastAPI,
    fake_db: DummyDbSession,
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[DummyDbSession, None]:
        yield fake_db

    profile_app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=profile_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    profile_app.dependency_overrides.clear()
