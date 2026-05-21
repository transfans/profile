import json
import logging
from datetime import UTC, datetime

import aio_pika

from app.core.config import settings
from app.core.logging import correlation_id_var

logger = logging.getLogger(__name__)

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_channel: aio_pika.abc.AbstractChannel | None = None

EXCHANGE_NAME = "transfans.events"


async def connect_rabbitmq() -> None:
    global _connection, _channel
    try:
        _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        _channel = await _connection.channel()
        exchange = await _channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)

        auth_creator_queue = await _channel.declare_queue("auth.creator_activated", durable=True)
        await auth_creator_queue.bind(exchange, routing_key="creator.activated")

        create_request_queue = await _channel.declare_queue("profile.subscription_create_request", durable=True)
        await create_request_queue.bind(exchange, routing_key="subscription.create.request")

        deactivate_request_queue = await _channel.declare_queue("profile.subscription_deactivate_request", durable=True)
        await deactivate_request_queue.bind(exchange, routing_key="subscription.deactivate.request")

        logger.info("Connected to RabbitMQ, queues declared")
    except Exception:
        logger.warning("Failed to connect to RabbitMQ — events will not be published", exc_info=True)


async def disconnect_rabbitmq() -> None:
    global _connection, _channel
    if _channel:
        await _channel.close()
        _channel = None
    if _connection:
        await _connection.close()
        _connection = None


def get_channel() -> aio_pika.abc.AbstractChannel | None:
    return _channel


async def publish_event(routing_key: str, data: dict) -> None:
    if not _channel:
        logger.warning("RabbitMQ not connected, skipping event: %s", routing_key)
        return

    try:
        exchange = await _channel.get_exchange(EXCHANGE_NAME)
        cid = correlation_id_var.get()
        message = aio_pika.Message(
            body=json.dumps(
                {
                    "event": routing_key,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": data,
                }
            ).encode(),
            content_type="application/json",
            correlation_id=cid,
        )
        await exchange.publish(message, routing_key=routing_key)
        logger.debug("Published %s  cid=%s", routing_key, cid)
    except Exception:
        logger.error("Failed to publish event: %s", routing_key, exc_info=True)
