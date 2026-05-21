import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

_SILENT_PATHS = frozenset({"/metrics", "/health"})

_NOISY_LOGGERS = (
    "aio_pika",
    "aiormq",
    "sqlalchemy.engine",
    "urllib3",
    "watchfiles",
    "watchfiles.main",
)


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()  # type: ignore[attr-defined]
        return True


def configure_logging(debug: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s]: %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(_CorrelationFilter())

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.handlers = []
    root.addHandler(handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    _log = logging.getLogger("app.http")

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SILENT_PATHS:
            return await call_next(request)

        cid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        t0 = time.monotonic()
        status = 500

        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = cid
            return response
        finally:
            ms = (time.monotonic() - t0) * 1000
            self._log.info("%s %s → %d  %.0fms", request.method, request.url.path, status, ms)
            correlation_id_var.reset(token)
