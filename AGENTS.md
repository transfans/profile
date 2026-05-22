# Profile Service — Implementation Details


## Service Overview

The Profile service (:8002) owns user profiles, subscription tiers, subscriptions, creator search, and avatar storage. It is a self-contained FastAPI microservice with its own PostgreSQL database (`profile_db`), MinIO instance (avatars), and RabbitMQ connection.

## Architecture Decisions

### JWT Validation — Local, No token_version

The service decodes JWTs locally using `JWT_SECRET_KEY` (shared across all services). It extracts `sub` (user_id), `role`, and `exp` from claims. Unlike the Auth service, it does **not** check `token_version` — it trusts the JWT signature. This avoids cross-service DB lookups and keeps the service fully independent.

See: `app/core/security.py` — only contains `decode_access_token`.

### Profile Lazy Initialization

Profiles are not pre-created. When `GET /profiles/me` is called and no profile exists for the JWT's `user_id`, one is created on the fly with `display_name` derived from the email. This means the Profile service does not need to consume `user.registered` events from RabbitMQ.

See: `app/services/profile_service.py` → `get_or_create_profile`.

### is_creator is Profile-Only

The `is_creator` boolean lives exclusively in the Profile DB. When activated via `PATCH /profiles/me/activate-creator`, the service publishes a `creator.activated` RabbitMQ event so the Auth service can optionally update its role enum. The client must call `POST /auth/refresh` afterward to get a new JWT with the updated role claim.

### Avatar Storage (MinIO)

- Bucket: configured via `MINIO_BUCKET_NAME` (default: `avatars`)
- Object key pattern: `{user_id}/{uuid}.{ext}`
- Allowed types: `image/jpeg`, `image/png`, `image/webp`
- Max size: 5 MB
- The MinIO Python SDK is synchronous; all calls are wrapped in `asyncio.to_thread()`
- The `avatar_url` column stores the MinIO object path (not a full URL). Presigned URLs are generated on read with a 1-hour expiry.
- Old avatars are deleted when a new one is uploaded.
- Bucket is auto-created on startup via the lifespan handler.

See: `app/services/avatar_service.py`.

### Internal Routes

All `/internal/*` endpoints are protected by `X-Internal-Secret` header validated against the `INTERNAL_SECRET` env var. These endpoints are called by the Payment and Content services and must never be exposed through Nginx.

Endpoints:

- `GET /internal/subscriptions/check` — Content service checks fan access
- `GET /internal/subscriptions?fan_id=` — Content service lists active subscribed creator IDs (feed)
- `POST /internal/subscriptions` — Payment service creates subscriptions (legacy sync path during migration)
- `GET /internal/tiers/{tier_id}` — Payment service fetches tier price
- `PATCH /internal/subscriptions/{id}/deactivate` — Payment service cancels (legacy sync path during migration)

Async message flow is the target architecture for create/deactivate operations. Synchronous endpoints above are temporary compatibility bridges.

#### Async Internal Contract (RabbitMQ)

Exchange: `transfans.events` (type: `topic`, durable: `true`).

Request routing keys:

- `subscription.create.request`
- `subscription.deactivate.request`

Base envelope (required):

```json
{
  "event": "routing.key",
  "timestamp": "iso8601",
  "message_id": "uuid",
  "request_id": "uuid",
  "initiator_service": "payment-service",
  "data": {}
}
```

`subscription.create.request` payload:

```json
{
  "fan_id": "uuid",
  "creator_id": "uuid",
  "tier_id": "uuid",
  "expires_at": "iso8601"
}
```

`subscription.deactivate.request` payload:

```json
{
  "subscription_id": "uuid",
  "reason": "string|null"
}
```

#### Delivery and Reliability Guarantees

- Delivery semantics are **at-least-once**.
- Consumers must be **idempotent** and safe for duplicate deliveries.
- `message_id` is the deduplication key; `request_id` is for tracing across services.
- Failed processing should be retried; repeated failures should be routed to a dead-letter queue (DLQ) according to broker policy.

#### Result/Response Contract

Outcome events:

- `subscription.create.succeeded`
- `subscription.create.failed`
- `subscription.deactivate.succeeded`
- `subscription.deactivate.failed`

Result envelope follows the same base fields (`event`, `timestamp`, `message_id`, `request_id`, `initiator_service`, `data`).

Success payloads:

- `subscription.create.succeeded`: `{ "subscription_id": "uuid", "fan_id": "uuid", "creator_id": "uuid", "tier_id": "uuid" }`
- `subscription.deactivate.succeeded`: `{ "subscription_id": "uuid", "status": "cancelled" }`

Failure payloads:

- `subscription.create.failed`: `{ "reason_code": "string", "reason_message": "string", "fan_id": "uuid", "creator_id": "uuid", "tier_id": "uuid" }`
- `subscription.deactivate.failed`: `{ "reason_code": "string", "reason_message": "string", "subscription_id": "uuid" }`

#### Migration Policy

- Full async flow is the target state for internal subscription create/deactivate operations.
- New integrations should publish async requests first and consume async result events.
- Sync endpoints remain available only as transitional compatibility paths.
- Sync create/deactivate endpoints can be removed after all internal callers migrate to async flow and stability SLOs are met.

See: `app/api/internal.py`, `app/core/dependencies.py` → `require_internal`.

### Subscription Expiry Background Job

An `asyncio.create_task` is launched in the app lifespan that runs every 5 minutes. It queries subscriptions where `status = 'active' AND expires_at < now()` and sets their status to `expired`. On each cycle it also updates the `active_subscriptions` Prometheus gauge to the authoritative DB count.

See: `app/tasks/subscription_expiry.py`.

### RabbitMQ Events

The service publishes to the `transfans.events` topic exchange:

- `creator.activated` — when a user activates creator mode
- `profile.updated` — when a user updates their profile

See: `app/events/publisher.py`, root-level `event-contract.md`.

### Metrics (Prometheus + Grafana)

HTTP instrumentation is provided by `prometheus-fastapi-instrumentator`. It exposes a `/metrics` endpoint on port 8002 and records:

- `http_request_duration_seconds` histogram (latency per route/method/status)
- `http_requests_inprogress` gauge (concurrent in-flight requests)

Business counters and gauges are defined in `app/metrics.py` and incremented at the point of the event:

| Metric                                   | Type    | Where incremented                                                                              |
| ---------------------------------------- | ------- | ---------------------------------------------------------------------------------------------- |
| `profiles_created_total`                 | Counter | `profile_service.py` → `get_or_create_profile` (new only)                                      |
| `creators_activated_total`               | Counter | `api/creators.py` → `activate_creator_mode`                                                    |
| `tiers_created_total`                    | Counter | `api/tiers.py` → `create_new_tier`                                                             |
| `tiers_updated_total`                    | Counter | `api/tiers.py` → `update_existing_tier`                                                        |
| `subscriptions_created_total`            | Counter | `api/internal.py` → `create_new_subscription`                                                  |
| `subscriptions_cancelled_total`          | Counter | `api/internal.py` → `deactivate_subscription_endpoint`                                         |
| `subscriptions_expired_total`            | Counter | `tasks/subscription_expiry.py`                                                                 |
| `active_subscriptions`                   | Gauge   | `api/internal.py` (inc/dec on create/cancel) + expiry task (authoritative DB sync every 5 min) |
| `analytics_proxy_requests_total{result}` | Counter | `services/analytics_client.py` (result=`success`\|`unavailable`)                               |

Prometheus scrapes `profile-service:8002/metrics` every 15s. Grafana is provisioned automatically on startup with a pre-built dashboard (`monitoring/grafana/dashboards/profile_service.json`) containing HTTP and Business Events rows.

Both are added to `docker-compose.yml` alongside the existing services.

### Structured Logging and Correlation IDs

All logging is configured in `app/core/logging.py` via `configure_logging()` called at module load in `main.py`. Key points:

- Format: `%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s]: %(message)s`
- `correlation_id_var` is a `ContextVar[str]` (default `"-"`). A `logging.Filter` injects its value into every log record automatically.
- `RequestLoggingMiddleware` (Starlette `BaseHTTPMiddleware`) reads `X-Request-ID` from the incoming request header (or generates a UUID), sets the ContextVar for the duration of the request, logs `METHOD /path → STATUS  Xms` at INFO, and echoes the ID in the response `X-Request-ID` header. `/metrics` and `/health` are excluded from access logging.
- Outgoing RabbitMQ messages carry `correlation_id` set from the ContextVar so consumers on other services can resume the trace.
- Event consumers (`app/events/consumer.py`) read `message.correlation_id`, set the ContextVar before processing, and reset it in `finally`.
- Third-party loggers silenced to `WARNING`: `aio_pika`, `aiormq`, `sqlalchemy.engine`, `urllib3`, `watchfiles`.
- SQLAlchemy `echo` is hardcoded to `False` in `session.py` (was `echo=settings.DEBUG`).

## Database

PostgreSQL 16, database name `profile_db`. Three tables:

| Table           | PK               | Key columns                                                                 |
| --------------- | ---------------- | --------------------------------------------------------------------------- |
| `profiles`      | `user_id` (UUID) | display_name, bio, avatar_url, email, is_creator                            |
| `tiers`         | `id` (UUID)      | creator_id FK→profiles, name, description, price (immutable), is_active     |
| `subscriptions` | `id` (UUID)      | fan_id, creator_id FK→profiles, tier_id FK→tiers, status (enum), expires_at |

Price on tiers is immutable after creation. To change price, deactivate the tier and create a new one.

## Directory Layout

```
app/
├── main.py              # FastAPI app, lifespan, router wiring, metrics + middleware setup
├── metrics.py           # All Prometheus counters and gauges (single source of truth)
├── api/                 # Route handlers
│   ├── profiles.py      # /profiles/me, /profiles/{user_id}
│   ├── avatars.py       # /profiles/me/avatar
│   ├── creators.py      # /profiles/me/activate-creator, /creators
│   ├── tiers.py         # /tiers
│   ├── subscriptions.py # /subscriptions/my, /subscribers/my
│   ├── analytics.py     # /analytics/* (proxy to analytics service)
│   └── internal.py      # /internal/* (service-to-service)
├── core/
│   ├── config.py        # Pydantic Settings
│   ├── security.py      # JWT decode
│   ├── dependencies.py  # get_current_user, require_creator, require_internal
│   └── logging.py       # correlation_id ContextVar, logging filter, middleware, configure_logging()
├── db/
│   ├── base.py          # SQLAlchemy DeclarativeBase
│   └── session.py       # async engine + session factory
├── events/
│   ├── publisher.py     # RabbitMQ topic publisher (propagates correlation_id)
│   └── consumer.py      # RabbitMQ consumers (reads correlation_id from message)
├── models/              # SQLAlchemy ORM models
│   ├── enums.py
│   ├── profile.py
│   ├── tier.py
│   └── subscription.py
├── schemas/             # Pydantic request/response schemas
│   ├── profile.py
│   ├── tier.py
│   └── subscription.py
├── services/            # Business logic
│   ├── profile_service.py
│   ├── tier_service.py
│   ├── subscription_service.py
│   ├── avatar_service.py
│   └── analytics_client.py  # HTTP client for analytics service (circuit breaker)
└── tasks/
    └── subscription_expiry.py  # Background expiry loop + active_subscriptions gauge sync

monitoring/
├── prometheus.yml                          # Scrape config (profile-service:8002/metrics)
└── grafana/
    ├── provisioning/
    │   ├── datasources/prometheus.yml      # Auto-provisioned Prometheus datasource
    │   └── dashboards/dashboards.yml       # Dashboard file provider config
    └── dashboards/
        └── profile_service.json            # Pre-built dashboard (HTTP + Business Events rows)

scripts/
└── seed_metrics.py      # Self-contained traffic generator; mints JWTs, runs ~60s of mixed load
```

## Running Locally

```bash
cd profile
cp .env.example .env
docker compose up -d
# Wait for services to be healthy, then run migrations:
alembic upgrade head
# Start the dev server:
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

## Docker Compose Services

| Service          | Port (host)  | Purpose                                              |
| ---------------- | ------------ | ---------------------------------------------------- |
| profile-postgres | 5433         | PostgreSQL 16 (`profile_db`)                         |
| profile-rabbitmq | 5673 / 15673 | RabbitMQ (AMQP / management UI)                      |
| minio            | 9000 / 9001  | MinIO (S3 API / console)                             |
| profile-service  | 8002         | FastAPI application + `/metrics` endpoint            |
| prometheus       | 9090         | Prometheus (scrapes profile-service every 15s)       |
| grafana          | 3000         | Grafana (admin / admin — dashboard auto-provisioned) |

Ports are offset from the Auth service to avoid collision during local development.

## Seeding Metrics

```bash
# Stack must be running; run from the profile/ directory
python scripts/seed_metrics.py

# Options
python scripts/seed_metrics.py --base-url http://localhost:8002 \
                                --creators 10 \
                                --fans 30 \
                                --duration 60
```

Phases: (1) create N creators + tiers, (2) create N fans, (3) subscribe fans to creator tiers, (4) continuous mixed traffic for `--duration` seconds — reads, profile updates, tier updates, new subscriptions, cancellations, and intentional 404s.

## Environment Variables

| Variable             | Description                                                             |
| -------------------- | ----------------------------------------------------------------------- |
| `DATABASE_URL`       | PostgreSQL async connection string                                      |
| `JWT_SECRET_KEY`     | Shared JWT secret (must match Auth service)                             |
| `JWT_ALGORITHM`      | JWT algorithm (HS256)                                                   |
| `MINIO_ENDPOINT`     | MinIO host:port                                                         |
| `MINIO_ACCESS_KEY`   | MinIO access key                                                        |
| `MINIO_SECRET_KEY`   | MinIO secret key                                                        |
| `MINIO_BUCKET_NAME`  | Bucket for avatars                                                      |
| `MINIO_USE_SSL`      | Whether to use TLS for MinIO                                            |
| `RABBITMQ_URL`       | AMQP connection string                                                  |
| `INTERNAL_SECRET`    | Shared secret for X-Internal-Secret header                              |
| `ANALYTICS_BASE_URL` | Base URL of the analytics service                                       |
| `APP_ENV`            | Environment name                                                        |
| `DEBUG`              | Enable DEBUG log level (third-party loggers stay at WARNING regardless) |
