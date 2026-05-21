"""
Seed script — creates realistic traffic against the profile service for ~60s so
Grafana panels fill up with time-series data instead of a single spike.

Usage (from the profile/ directory, stack must be running):
    python scripts/seed_metrics.py [--base-url http://localhost:8002] \
                                   [--creators 10] [--fans 30] \
                                   [--duration 60]

Requirements: python-jose and httpx — both already in the project's dependencies.
"""

import argparse
import asyncio
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from jose import jwt

# ── defaults ───────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8002"
JWT_SECRET = "super-secret-key-change-in-production-min-32-chars"
JWT_ALGORITHM = "HS256"
INTERNAL_SECRET = "secret"
N_CREATORS = 10
N_FANS = 30
DURATION_SECS = 60


# ── helpers ────────────────────────────────────────────────────────────────────

def _mint(user_id: str, role: str, email: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "role": role,
            "email": email,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _internal() -> dict:
    return {"X-Internal-Secret": INTERNAL_SECRET}


# ── setup phases ───────────────────────────────────────────────────────────────

async def phase_creators(client: httpx.AsyncClient, n: int) -> list[dict]:
    creators = []
    for i in range(n):
        uid = str(uuid.uuid4())
        email = f"creator_{i}_{uid[:8]}@example.com"
        token = _mint(uid, "creator", email)

        await client.get("/profiles/me", headers=_auth(token))

        r = await client.patch("/profiles/me/activate-creator", headers=_auth(token))
        if r.status_code not in (200, 409):
            print(f"  [warn] activate-creator {uid}: {r.status_code}")

        tier_ids = []
        for t in range(2):
            r = await client.post(
                "/tiers",
                json={
                    "name": f"Tier {t + 1} — creator {i}",
                    "description": f"Auto-seeded tier {t + 1}",
                    "price": round(random.uniform(3.99, 19.99), 2),
                },
                headers=_auth(token),
            )
            if r.status_code == 201:
                tier_ids.append(r.json()["id"])

        creators.append({"id": uid, "token": token, "tier_ids": tier_ids})
        print(f"  creator {i + 1}/{n}: {uid} — {len(tier_ids)} tiers")

    return creators


async def phase_fans(client: httpx.AsyncClient, n: int) -> list[dict]:
    fans = []
    for i in range(n):
        uid = str(uuid.uuid4())
        email = f"fan_{i}_{uid[:8]}@example.com"
        token = _mint(uid, "fan", email)

        await client.get("/profiles/me", headers=_auth(token))
        await client.patch(
            "/profiles/me",
            json={"display_name": f"Fan {i}", "bio": f"Seeded fan #{i}"},
            headers=_auth(token),
        )

        fans.append({"id": uid, "token": token})
        print(f"  fan {i + 1}/{n}: {uid}")

    return fans


async def phase_subscriptions(
    client: httpx.AsyncClient, fans: list[dict], creators: list[dict]
) -> list[dict]:
    """Subscribe every fan to one random creator tier. Returns subscription records."""
    created = []
    for fan in fans:
        creator = random.choice(creators)
        if not creator["tier_ids"]:
            continue
        tier_id = random.choice(creator["tier_ids"])
        r = await client.post(
            "/internal/subscriptions",
            json={
                "fan_id": fan["id"],
                "creator_id": creator["id"],
                "tier_id": tier_id,
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
            headers=_internal(),
        )
        if r.status_code == 201:
            created.append(
                {
                    "id": r.json()["subscription_id"],
                    "fan_id": fan["id"],
                    "creator_id": creator["id"],
                }
            )
        else:
            print(f"  [warn] subscribe {fan['id']}: {r.status_code} {r.text[:80]}")
    return created


# ── continuous traffic ─────────────────────────────────────────────────────────

async def _one_wave(
    client: httpx.AsyncClient,
    fans: list[dict],
    creators: list[dict],
    subscriptions: list[dict],
    wave: int,
) -> None:
    """Fire a burst of mixed requests that produces varied metrics."""
    tasks = []

    # fan profile reads (most common in a real app)
    sample_fans = random.sample(fans, min(8, len(fans)))
    for fan in sample_fans:
        tasks.append(client.get("/profiles/me", headers=_auth(fan["token"])))

    # creator profile reads by fans
    sample_creators = random.sample(creators, min(5, len(creators)))
    for creator in sample_creators:
        tasks.append(client.get(f"/profiles/{creator['id']}"))

    # creator list browsing
    tasks.append(client.get("/creators"))
    tasks.append(client.get(f"/creators?q=creator+{random.randint(0, 9)}"))

    # intentional 404s — non-existent lookups (generates error-rate signal)
    for _ in range(3):
        tasks.append(client.get(f"/profiles/{uuid.uuid4()}"))

    # profile updates
    for fan in random.sample(fans, min(3, len(fans))):
        tasks.append(
            client.patch(
                "/profiles/me",
                json={"bio": f"Updated in wave {wave}"},
                headers=_auth(fan["token"]),
            )
        )

    # tier updates from creators
    for creator in random.sample(creators, min(2, len(creators))):
        if creator["tier_ids"]:
            tid = random.choice(creator["tier_ids"])
            tasks.append(
                client.patch(
                    f"/tiers/{tid}",
                    json={"name": f"Wave-{wave} tier"},
                    headers=_auth(creator["token"]),
                )
            )

    # occasionally subscribe a new fan mid-run (keeps subscriptions_created rising)
    if random.random() < 0.3:
        uid = str(uuid.uuid4())
        token = _mint(uid, "fan", f"latecomer_{uid[:8]}@example.com")
        await client.get("/profiles/me", headers=_auth(token))
        creator = random.choice(creators)
        if creator["tier_ids"]:
            await client.post(
                "/internal/subscriptions",
                json={
                    "fan_id": uid,
                    "creator_id": creator["id"],
                    "tier_id": random.choice(creator["tier_ids"]),
                    "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                },
                headers=_internal(),
            )

    # occasionally cancel a subscription (keeps subscriptions_cancelled non-zero)
    if subscriptions and random.random() < 0.2:
        sub = random.choice(subscriptions)
        await client.patch(
            f"/internal/subscriptions/{sub['id']}/deactivate",
            headers=_internal(),
        )

    await asyncio.gather(*tasks, return_exceptions=True)


async def continuous_traffic(
    client: httpx.AsyncClient,
    fans: list[dict],
    creators: list[dict],
    subscriptions: list[dict],
    duration: float,
) -> None:
    deadline = time.monotonic() + duration
    wave = 0
    while time.monotonic() < deadline:
        wave += 1
        remaining = deadline - time.monotonic()
        print(f"  wave {wave} — {remaining:.0f}s remaining")
        await _one_wave(client, fans, creators, subscriptions, wave)
        await asyncio.sleep(random.uniform(1.5, 3.0))  # vary inter-wave gap


# ── main ───────────────────────────────────────────────────────────────────────

async def run(base_url: str, n_creators: int, n_fans: int, duration: float) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        r = await client.get("/health")
        if r.status_code != 200:
            raise SystemExit(f"Service not reachable at {base_url} — got {r.status_code}")
        print(f"Service healthy at {base_url}\n")

        print(f"=== Phase 1: creating {n_creators} creators ===")
        creators = await phase_creators(client, n_creators)

        print(f"\n=== Phase 2: creating {n_fans} fans ===")
        fans = await phase_fans(client, n_fans)

        print(f"\n=== Phase 3: initial subscriptions ===")
        subscriptions = await phase_subscriptions(client, fans, creators)
        print(f"  {len(subscriptions)} subscriptions created")

        print(f"\n=== Phase 4: continuous traffic for ~{duration:.0f}s ===")
        await continuous_traffic(client, fans, creators, subscriptions, duration)

        print("\nDone. Open Grafana at http://localhost:3000 (admin / admin).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed profile-service with mock traffic")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--creators", type=int, default=N_CREATORS)
    parser.add_argument("--fans", type=int, default=N_FANS)
    parser.add_argument("--duration", type=float, default=DURATION_SECS, help="Seconds to run continuous traffic")
    args = parser.parse_args()

    asyncio.run(run(args.base_url, args.creators, args.fans, args.duration))
