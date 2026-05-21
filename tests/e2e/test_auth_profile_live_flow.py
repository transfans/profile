from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_auth_to_profile_live_user_flow(live_clients):
    auth_client, profile_client = live_clients

    email = f"cross_{uuid4().hex[:10]}@example.com"
    username = f"cross_user_{uuid4().hex[:10]}"
    password = "Password123!"

    register_response = await auth_client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    assert register_response.status_code == 201
    access_token = register_response.json()["access_token"]

    me_response = await profile_client.get(
        "/profiles/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 200
    me_payload = me_response.json()
    assert me_payload["email"]
    assert me_payload["is_creator"] is False

    activate_response = await profile_client.patch(
        "/profiles/me/activate-creator",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["is_creator"] is True
