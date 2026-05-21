import asyncio
import logging
import random
import time
from enum import Enum

import httpx

from app.core.config import settings
from app.metrics import analytics_proxy_requests_total

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_BASE_BACKOFF_S = 0.1
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_CB_FAILURE_THRESHOLD = 5
_CB_RECOVERY_TIMEOUT_S = 20.0


class _CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"


class _CircuitBreaker:
    def __init__(
        self, failure_threshold: int = _CB_FAILURE_THRESHOLD, recovery_timeout_s: float = _CB_RECOVERY_TIMEOUT_S
    ) -> None:
        self._threshold = failure_threshold
        self._recovery = recovery_timeout_s
        self._failures = 0
        self._state = _CircuitState.CLOSED
        self._opened_at: float | None = None

    @property
    def is_available(self) -> bool:
        if self._state == _CircuitState.OPEN:
            if self._opened_at and time.monotonic() - self._opened_at >= self._recovery:
                logger.info("Circuit breaker recovery timeout elapsed — resetting to CLOSED")
                self._state = _CircuitState.CLOSED
                self._failures = 0
                self._opened_at = None
                return True
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._state = _CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._state = _CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "Circuit breaker OPENED after %d consecutive failures — blocking for %.0fs",
                self._failures,
                self._recovery,
            )


_breaker = _CircuitBreaker()
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.ANALYTICS_BASE_URL,
            timeout=settings.ANALYTICS_TIMEOUT_SECONDS,
        )
    return _client


async def close_analytics_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Analytics HTTP client closed")


async def analytics_get(
    path: str,
    params: dict | None = None,
    request_id: str | None = None,
) -> dict | None:
    if not _breaker.is_available:
        logger.warning("Analytics circuit OPEN — skipping call to %s", path)
        analytics_proxy_requests_total.labels(result="unavailable").inc()
        return None

    headers: dict[str, str] = {
        "X-Request-Timeout": str(int(settings.ANALYTICS_TIMEOUT_SECONDS * 1000)),
    }
    if request_id:
        headers["X-Request-ID"] = request_id

    client = _get_client()
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            backoff = _BASE_BACKOFF_S * (2 ** (attempt - 1))
            jitter = random.uniform(0.0, backoff * 0.5)
            await asyncio.sleep(backoff + jitter)
            logger.debug("Retrying analytics call to %s (attempt %d)", path, attempt + 1)

        try:
            response = await client.get(path, params=params, headers=headers)

            if response.status_code == 200:
                _breaker.record_success()
                analytics_proxy_requests_total.labels(result="success").inc()
                return response.json()

            if response.status_code not in _RETRYABLE_STATUS:
                _breaker.record_success()
                analytics_proxy_requests_total.labels(result="success").inc()
                return response.json()

            logger.warning(
                "Analytics returned %d for %s (attempt %d/%d)",
                response.status_code,
                path,
                attempt + 1,
                _MAX_RETRIES + 1,
            )
            last_exc = None

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning(
                "Analytics request failed for %s (attempt %d/%d): %s",
                path,
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
            )
            last_exc = exc

    _breaker.record_failure()
    analytics_proxy_requests_total.labels(result="unavailable").inc()
    logger.error("Analytics: all retries exhausted for %s — last_error=%s", path, last_exc)
    return None
