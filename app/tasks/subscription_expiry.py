import asyncio
import logging

from app.db.session import async_session_factory
from app.services.subscription_service import expire_overdue_subscriptions

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300  # 5 minutes


async def subscription_expiry_loop() -> None:
    while True:
        try:
            async with async_session_factory() as db:
                count = await expire_overdue_subscriptions(db)
                if count > 0:
                    logger.info("Expired %d overdue subscriptions", count)
        except Exception:
            logger.error("Error in subscription expiry task", exc_info=True)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
