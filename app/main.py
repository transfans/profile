import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.analytics import router as analytics_router
from app.api.avatars import router as avatars_router
from app.api.creators import router as creators_router
from app.api.internal import router as internal_router
from app.api.profiles import router as profiles_router
from app.api.subscriptions import router as subscriptions_router
from app.api.tiers import router as tiers_router
from app.core.config import settings
from app.events.consumer import start_consuming, stop_consuming
from app.events.publisher import connect_rabbitmq, disconnect_rabbitmq
from app.services.analytics_client import close_analytics_client
from app.services.avatar_service import ensure_bucket_exists
from app.tasks.subscription_expiry import subscription_expiry_loop

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_rabbitmq()
    await start_consuming()

    try:
        await asyncio.to_thread(ensure_bucket_exists)
        logger.info("MinIO bucket verified")
    except Exception:
        logger.warning("Failed to verify MinIO bucket — avatar uploads may fail", exc_info=True)

    expiry_task = asyncio.create_task(subscription_expiry_loop())

    yield

    expiry_task.cancel()
    try:
        await expiry_task
    except asyncio.CancelledError:
        pass

    await stop_consuming()
    await disconnect_rabbitmq()
    await close_analytics_client()


app = FastAPI(
    title="TransFans Profile Service",
    description="Profile, tiers, and subscriptions microservice",
    version="1.0.0",
    lifespan=lifespan,
)

Instrumentator(
    should_instrument_requests_inprogress=True,
    inprogress_name="http_requests_inprogress",
    excluded_handlers=["/metrics"],
).instrument(app).expose(app)

app.include_router(analytics_router)
app.include_router(profiles_router)
app.include_router(avatars_router)
app.include_router(creators_router)
app.include_router(tiers_router)
app.include_router(subscriptions_router)
app.include_router(internal_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
