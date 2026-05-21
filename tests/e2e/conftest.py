import os
from collections.abc import AsyncGenerator

import httpx
import pytest


@pytest.fixture
def live_auth_base_url() -> str:
    return os.getenv("AUTH_E2E_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture
def live_profile_base_url() -> str:
    return os.getenv("PROFILE_E2E_BASE_URL", "http://127.0.0.1:8002")


@pytest.fixture
def profile_internal_secret() -> str:
    return os.getenv("PROFILE_E2E_INTERNAL_SECRET", "secret")


@pytest.fixture
async def live_clients(
    live_auth_base_url: str,
    live_profile_base_url: str,
) -> AsyncGenerator[tuple[httpx.AsyncClient, httpx.AsyncClient], None]:
    timeout = httpx.Timeout(10.0, connect=2.0)

    async with (
        httpx.AsyncClient(base_url=live_auth_base_url, timeout=timeout) as auth_client,
        httpx.AsyncClient(base_url=live_profile_base_url, timeout=timeout) as profile_client,
    ):
        try:
            auth_health = await auth_client.get("/health")
            profile_health = await profile_client.get("/health")
        except httpx.HTTPError as exc:
            pytest.skip(f"profile e2e skipped: service not reachable ({exc})")

        if auth_health.status_code != 200 or profile_health.status_code != 200:
            pytest.skip(
                "profile e2e skipped: health failed "
                f"(auth={auth_health.status_code}, profile={profile_health.status_code})"
            )

        yield auth_client, profile_client
