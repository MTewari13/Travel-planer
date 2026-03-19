"""Redis Pub/Sub message bus for A2A communication."""

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import redis.asyncio as aioredis

from shared.types.message import AgentMessage

logger = logging.getLogger("message_bus")


class RedisBus:
    """Async Redis Pub/Sub wrapper for agent-to-agent messaging."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._publisher: aioredis.Redis | None = None
        self._subscriber: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._handlers: dict[str, list[Callable]] = {}
        self._listener_task: asyncio.Task | None = None
        self._running = False

    async def connect(self):
        """Initialize Redis connections for pub and sub."""
        self._publisher = aioredis.from_url(
            self._redis_url, decode_responses=True
        )
        self._subscriber = aioredis.from_url(
            self._redis_url, decode_responses=True
        )
        self._pubsub = self._subscriber.pubsub()
        self._running = True
        logger.info("✅ Redis message bus connected")

    async def publish(self, channel: str, message: AgentMessage):
        """Publish a message to a Redis channel."""
        if not self._publisher:
            raise RuntimeError("RedisBus not connected. Call connect() first.")

        payload = message.model_dump_json()
        await self._publisher.publish(channel, payload)
        logger.info(
            f"📤 [{message.from_agent}] → [{message.to_agent}] "
            f"task={message.task} corr={message.correlation_id[:8]}..."
        )

    async def subscribe(
        self,
        channel: str,
        handler: Callable[[AgentMessage], Coroutine[Any, Any, Any]],
    ):
        """Subscribe to a channel with an async handler."""
        if not self._pubsub:
            raise RuntimeError("RedisBus not connected. Call connect() first.")

        if channel not in self._handlers:
            self._handlers[channel] = []
            await self._pubsub.subscribe(channel)
            logger.info(f"📡 Subscribed to channel: {channel}")

        self._handlers[channel].append(handler)

    async def start_listening(self):
        """Start the background listener for all subscribed channels."""
        if self._listener_task and not self._listener_task.done():
            return

        self._listener_task = asyncio.create_task(self._listen())
        logger.info("🎧 Message bus listener started")

    async def _listen(self):
        """Background loop reading messages from Redis pub/sub."""
        while self._running:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message.get("type") == "message":
                    channel = message["channel"]
                    data = message["data"]

                    try:
                        agent_msg = AgentMessage.model_validate_json(data)
                    except Exception as e:
                        logger.error(f"Failed to parse message on {channel}: {e}")
                        continue

                    handlers = self._handlers.get(channel, [])
                    for handler in handlers:
                        try:
                            # Run concurrently so agent logic doesn't block the message loop
                            asyncio.create_task(handler(agent_msg))
                        except Exception as e:
                            logger.error(
                                f"Handler dispatcher error on {channel}: {e}", exc_info=True
                            )

                await asyncio.sleep(0.01)  # prevent tight loop
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Listener error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def request_response(
        self,
        channel: str,
        message: AgentMessage,
        timeout: float = 30.0,
    ) -> AgentMessage | None:
        """Send a message and wait for a correlated response."""
        import uuid
        # Use a unique response channel per request to avoid collisions
        # when multiple request_response calls share the same correlation_id
        request_id = str(uuid.uuid4())[:8]
        response_channel = f"response:{message.correlation_id}:{request_id}"
        future: asyncio.Future[AgentMessage] = asyncio.get_event_loop().create_future()

        async def _on_response(msg: AgentMessage):
            if not future.done():
                future.set_result(msg)

        await self.subscribe(response_channel, _on_response)
        message.reply_to = response_channel
        await self.publish(channel, message)

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(
                f"⏰ Timeout waiting for response on {response_channel} "
                f"(corr={message.correlation_id[:8]}...)"
            )
            return None
        finally:
            await self._pubsub.unsubscribe(response_channel)
            self._handlers.pop(response_channel, None)

    async def close(self):
        """Gracefully shut down the message bus."""
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._publisher:
            await self._publisher.close()
        if self._subscriber:
            await self._subscriber.close()
        logger.info("🔌 Redis message bus disconnected")
