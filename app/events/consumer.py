import json
import logging
import uuid
from datetime import datetime

import aio_pika

from app.core.logging import correlation_id_var
from app.db.session import async_session_factory
from app.events.publisher import get_channel, publish_event
from app.services.subscription_service import (
    create_subscription,
    deactivate_subscription,
    get_subscription_by_id,
)

logger = logging.getLogger(__name__)

CREATE_QUEUE = "profile.subscription_create_request"
DEACTIVATE_QUEUE = "profile.subscription_deactivate_request"

_consumer_tags: list[tuple[str, str]] = []


async def _handle_create_subscription(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    async with message.process():
        envelope = json.loads(message.body)
        request_id = envelope.get("request_id")
        data = envelope.get("data", {})

        cid = message.correlation_id or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        logger.info("Received subscription.create.request  fan=%s  creator=%s", data.get("fan_id"), data.get("creator_id"))

        try:
            fan_id = uuid.UUID(data["fan_id"])
            creator_id = uuid.UUID(data["creator_id"])
            tier_id = uuid.UUID(data["tier_id"])
            expires_at = datetime.fromisoformat(data["expires_at"])

            async with async_session_factory() as db:
                created = await create_subscription(
                    db,
                    fan_id=fan_id,
                    creator_id=creator_id,
                    tier_id=tier_id,
                    expires_at=expires_at,
                )

            await publish_event(
                "subscription.created",
                {
                    "subscription_id": str(created.id),
                    "fan_id": str(fan_id),
                    "creator_id": str(creator_id),
                    "tier_id": str(tier_id),
                },
            )
            await publish_event(
                "subscription.create.succeeded",
                {
                    "request_id": request_id,
                    "subscription_id": str(created.id),
                    "fan_id": str(fan_id),
                    "creator_id": str(creator_id),
                    "tier_id": str(tier_id),
                },
            )
        except Exception as exc:
            logger.error("Failed to process subscription.create.request  fan=%s", data.get("fan_id"), exc_info=True)
            await publish_event(
                "subscription.create.failed",
                {
                    "request_id": request_id,
                    "reason_code": "create_failed",
                    "reason_message": str(exc),
                    "fan_id": data.get("fan_id"),
                    "creator_id": data.get("creator_id"),
                    "tier_id": data.get("tier_id"),
                },
            )
        finally:
            correlation_id_var.reset(token)


async def _handle_deactivate_subscription(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    async with message.process():
        envelope = json.loads(message.body)
        request_id = envelope.get("request_id")
        data = envelope.get("data", {})
        subscription_id_value = data.get("subscription_id")

        cid = message.correlation_id or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        logger.info("Received subscription.deactivate.request  sub=%s", subscription_id_value)

        try:
            if not subscription_id_value:
                raise ValueError("subscription_id is required")

            subscription_id = uuid.UUID(subscription_id_value)
            async with async_session_factory() as db:
                subscription = await get_subscription_by_id(db, subscription_id)
                if not subscription:
                    raise ValueError("Subscription not found")
                await deactivate_subscription(db, subscription)

            await publish_event(
                "subscription.cancelled",
                {"subscription_id": str(subscription_id)},
            )
            await publish_event(
                "subscription.deactivate.succeeded",
                {
                    "request_id": request_id,
                    "subscription_id": str(subscription_id),
                    "status": "cancelled",
                },
            )
        except Exception as exc:
            logger.error("Failed to process subscription.deactivate.request  sub=%s", subscription_id_value, exc_info=True)
            await publish_event(
                "subscription.deactivate.failed",
                {
                    "request_id": request_id,
                    "reason_code": "deactivate_failed",
                    "reason_message": str(exc),
                    "subscription_id": subscription_id_value,
                },
            )
        finally:
            correlation_id_var.reset(token)


async def start_consuming() -> None:
    global _consumer_tags
    channel = get_channel()
    if not channel:
        logger.warning("RabbitMQ channel not available, skipping consumer setup")
        return

    try:
        create_queue = await channel.get_queue(CREATE_QUEUE)
        create_tag = await create_queue.consume(_handle_create_subscription)
        _consumer_tags.append((CREATE_QUEUE, create_tag))

        deactivate_queue = await channel.get_queue(DEACTIVATE_QUEUE)
        deactivate_tag = await deactivate_queue.consume(_handle_deactivate_subscription)
        _consumer_tags.append((DEACTIVATE_QUEUE, deactivate_tag))

        logger.info("Started async subscription consumers")
    except Exception:
        logger.error("Failed to start subscription consumers", exc_info=True)


async def stop_consuming() -> None:
    global _consumer_tags
    if not _consumer_tags:
        return

    channel = get_channel()
    if not channel:
        return

    for queue_name, consumer_tag in _consumer_tags:
        try:
            queue = await channel.get_queue(queue_name)
            await queue.cancel(consumer_tag)
        except Exception:
            logger.error("Failed to stop consumer for queue %s", queue_name, exc_info=True)

    _consumer_tags = []
