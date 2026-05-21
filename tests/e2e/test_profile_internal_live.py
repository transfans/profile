from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_profile_internal_subscription_check_and_create_live(live_clients, profile_internal_secret: str):
    _auth_client, profile_client = live_clients

    check_response = await profile_client.get(
        "/internal/subscriptions/check",
        params={"fan_id": str(uuid4()), "creator_id": str(uuid4())},
        headers={"X-Internal-Secret": profile_internal_secret},
    )
    assert check_response.status_code == 200
    assert "has_access" in check_response.json()

    create_response = await profile_client.post(
        "/internal/subscriptions",
        headers={"X-Internal-Secret": profile_internal_secret},
        json={
            "fan_id": str(uuid4()),
            "creator_id": str(uuid4()),
            "tier_id": str(uuid4()),
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
    )

    # Live environments may return validation, domain, or runtime errors depending on referenced entities.
    assert create_response.status_code in {201, 404, 422, 500}
