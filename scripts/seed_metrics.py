"""
Seed script — creates realistic traffic against the profile service so Grafana
panels fill up with time-series data.

Usage (from the profile/ directory, stack must be running):
    python scripts/seed_metrics.py [options]

Options:
    --base-url   http://localhost:8002   Service base URL
    --creators   10                      Number of creator users to seed
    --fans       30                      Number of fan users to seed
    --duration   60                      Seconds to run continuous traffic
    --concurrency 40                     Concurrent async workers during traffic phase

Requirements: python-jose and httpx — both already in the project's dependencies.
"""

import argparse
import asyncio
import random
import time
import uuid
from collections import defaultdict
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
CONCURRENCY = 40


# ── helpers ────────────────────────────────────────────────────────────────────


def _mint(user_id: str, role: str, email: str) -> str:
    return jwt.encode(
        {"sub": user_id, "role": role, "email": email, "exp": datetime.now(UTC) + timedelta(hours=2)},
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
            json={
                "display_name": f"Fan {i}",
                "bio": f"Seeded fan #{i}",
            },
            headers=_auth(token),
        )

        fans.append({"id": uid, "token": token})
        print(f"  fan {i + 1}/{n}: {uid}")
    return fans


async def phase_subscriptions(client: httpx.AsyncClient, fans: list[dict], creators: list[dict]) -> list[dict]:
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
    print(f"  {len(created)} subscriptions created")
    return created


# ── continuous traffic ─────────────────────────────────────────────────────────


# Weighted action table: (weight, label, coroutine_factory)
# Higher weight = picked more often
def _build_actions(client, fans, creators, subscriptions):
    fan_tokens = [f["token"] for f in fans]
    creator_tokens = [c["token"] for c in creators]
    creator_ids = [c["id"] for c in creators]
    all_tier_ids = [tid for c in creators for tid in c["tier_ids"]]

    actions = [
        # weight, label, lambda → coroutine
        (30, "GET /profiles/me", lambda: client.get("/profiles/me", headers=_auth(random.choice(fan_tokens)))),
        (20, "GET /profiles/{id}", lambda: client.get(f"/profiles/{random.choice(creator_ids)}")),
        (10, "GET /creators", lambda: client.get("/creators")),
        (
            8,
            "PATCH /profiles/me",
            lambda: client.patch(
                "/profiles/me", json={"bio": f"bio {random.randint(0, 9999)}"}, headers=_auth(random.choice(fan_tokens))
            ),
        ),
        (6, "GET /subscriptions/my", lambda: client.get("/subscriptions/my", headers=_auth(random.choice(fan_tokens)))),
        (
            5,
            "PATCH /tiers/{id}",
            lambda: client.patch(
                f"/tiers/{random.choice(all_tier_ids)}",
                json={"name": f"tier {random.randint(0, 999)}"},
                headers=_auth(random.choice(creator_tokens)),
            ),
        ),
        (5, "GET /profiles/404", lambda: client.get(f"/profiles/{uuid.uuid4()}")),  # intentional 404
        (4, "POST /internal/subscriptions", lambda: _new_subscription(client, creators)),
        (2, "PATCH /internal/deactivate", lambda: _cancel_subscription(client, subscriptions)),
    ]
    return actions


async def _new_subscription(client, creators):
    uid = str(uuid.uuid4())
    token = _mint(uid, "fan", f"lt_{uid[:8]}@example.com")
    await client.get("/profiles/me", headers=_auth(token))
    creator = random.choice(creators)
    if not creator["tier_ids"]:
        return
    return await client.post(
        "/internal/subscriptions",
        json={
            "fan_id": uid,
            "creator_id": creator["id"],
            "tier_id": random.choice(creator["tier_ids"]),
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
        headers=_internal(),
    )


async def _cancel_subscription(client, subscriptions):
    if not subscriptions:
        return
    sub = random.choice(subscriptions)
    return await client.patch(
        f"/internal/subscriptions/{sub['id']}/deactivate",
        headers=_internal(),
    )


async def _worker(
    client: httpx.AsyncClient,
    actions: list,
    deadline: float,
    counters: dict,
) -> None:
    weights = [a[0] for a in actions]
    total_weight = sum(weights)
    thresholds = []
    cumulative = 0
    for w, label, _ in actions:
        cumulative += w
        thresholds.append((cumulative / total_weight, label))

    while time.monotonic() < deadline:
        r = random.random()
        chosen_label = thresholds[-1][1]
        chosen_fn = actions[-1][2]
        for i, (threshold, label) in enumerate(thresholds):
            if r < threshold:
                chosen_label = label
                chosen_fn = actions[i][2]
                break

        try:
            await chosen_fn()
            counters[chosen_label] += 1
        except Exception:
            counters["errors"] += 1

        await asyncio.sleep(0)  # yield to event loop without blocking


async def continuous_traffic(
    client: httpx.AsyncClient,
    fans: list[dict],
    creators: list[dict],
    subscriptions: list[dict],
    duration: float,
    concurrency: int,
) -> None:
    actions = _build_actions(client, fans, creators, subscriptions)
    counters: dict = defaultdict(int)
    deadline = time.monotonic() + duration

    workers = [_worker(client, actions, deadline, counters) for _ in range(concurrency)]

    t0 = time.monotonic()

    # progress reporter
    async def _reporter():
        while time.monotonic() < deadline:
            await asyncio.sleep(5)
            elapsed = time.monotonic() - t0
            total = sum(v for k, v in counters.items() if k != "errors")
            print(f"  {elapsed:.0f}s  {total} reqs  {total / elapsed:.0f} req/s")

    await asyncio.gather(*workers, _reporter())

    elapsed = time.monotonic() - t0
    total = sum(v for k, v in counters.items() if k != "errors")
    print(f"\n  Finished: {total} requests in {elapsed:.1f}s = {total / elapsed:.0f} req/s")
    if counters["errors"]:
        print(f"  Errors: {counters['errors']}")
    print("\n  Breakdown:")
    for label, count in sorted(counters.items(), key=lambda x: -x[1]):
        if label != "errors" and count:
            print(f"    {count:>6}  {label}")


# ── main ───────────────────────────────────────────────────────────────────────


async def run(base_url: str, n_creators: int, n_fans: int, duration: float, concurrency: int) -> None:
    limits = httpx.Limits(max_connections=concurrency + 20, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0, limits=limits) as client:
        r = await client.get("/health")
        if r.status_code != 200:
            raise SystemExit(f"Service not reachable at {base_url} — got {r.status_code}")
        print(f"Service healthy at {base_url}\n")

        print(f"=== Phase 1: creating {n_creators} creators ===")
        creators = await phase_creators(client, n_creators)

        print(f"\n=== Phase 2: creating {n_fans} fans ===")
        fans = await phase_fans(client, n_fans)

        print("\n=== Phase 3: initial subscriptions ===")
        subscriptions = await phase_subscriptions(client, fans, creators)

        print(f"\n=== Phase 4: {concurrency} concurrent workers for {duration:.0f}s ===")
        await continuous_traffic(client, fans, creators, subscriptions, duration, concurrency)

        print("\nDone. Open Grafana at http://localhost:3000 (admin / admin).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed profile-service with mock traffic")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--creators", type=int, default=N_CREATORS)
    parser.add_argument("--fans", type=int, default=N_FANS)
    parser.add_argument("--duration", type=float, default=DURATION_SECS)
    parser.add_argument(
        "--concurrency", type=int, default=CONCURRENCY, help="Number of concurrent async workers during traffic phase"
    )
    args = parser.parse_args()

    asyncio.run(run(args.base_url, args.creators, args.fans, args.duration, args.concurrency))
