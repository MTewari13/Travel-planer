"""Base agent abstract class — foundation for all A2A agents."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.logger.agent_logger import AgentLogger


class BaseAgent(ABC):
    """Abstract base class for all agents in the travel planner system.

    Provides:
    - Auto-subscription to the agent's own channel
    - send() for publishing messages to other agents
    - Structured logging with agent name and correlation ID
    - Retry logic with exponential backoff
    """

    agent_type: AgentType
    max_retries: int = 3

    def __init__(self, bus: RedisBus):
        self._bus = bus
        self.logger = AgentLogger(self.agent_type.value)
        self._log = logging.getLogger(self.agent_type.value)

    @abstractmethod
    async def handle(self, message: AgentMessage) -> Any:
        """Process an incoming message. Must be implemented by each agent."""
        ...

    async def start(self):
        """Subscribe to this agent's channel and begin listening."""
        channel = self.agent_type.value
        await self._bus.subscribe(channel, self._on_message)
        self._log.info(f"🚀 {self.agent_type.value} started, listening on '{channel}'")

    async def _on_message(self, message: AgentMessage):
        """Internal message handler with retry logic."""
        self.logger.received(message)
        retries = 0

        while retries <= self.max_retries:
            try:
                result = await self.handle(message)

                # If the message has a reply_to channel, send the result back
                if message.reply_to and result is not None:
                    response = AgentMessage(
                        from_agent=self.agent_type,
                        to_agent=message.from_agent,
                        task=f"{message.task}_response",
                        payload=result if isinstance(result, dict) else {"result": result},
                        correlation_id=message.correlation_id,
                    )
                    await self._bus.publish(message.reply_to, response)
                    self.logger.sent(response)

                return result

            except Exception as e:
                retries += 1
                if retries > self.max_retries:
                    self.logger.error(
                        message.correlation_id,
                        f"Failed after {self.max_retries} retries: {e}",
                    )
                    # Send error response if reply_to exists
                    if message.reply_to:
                        error_response = AgentMessage(
                            from_agent=self.agent_type,
                            to_agent=message.from_agent,
                            task=f"{message.task}_error",
                            payload={"error": str(e)},
                            correlation_id=message.correlation_id,
                        )
                        await self._bus.publish(message.reply_to, error_response)
                    raise
                else:
                    wait_time = 2**retries * 0.5
                    self.logger.warning(
                        message.correlation_id,
                        f"Retry {retries}/{self.max_retries} after {wait_time}s: {e}",
                    )
                    await asyncio.sleep(wait_time)

    async def send(
        self,
        to: AgentType,
        task: str,
        payload: dict,
        correlation_id: str,
    ):
        """Send a fire-and-forget message to another agent."""
        message = AgentMessage(
            from_agent=self.agent_type,
            to_agent=to,
            task=task,
            payload=payload,
            correlation_id=correlation_id,
        )
        await self._bus.publish(to.value, message)
        self.logger.sent(message)

    async def request(
        self,
        to: AgentType,
        task: str,
        payload: dict,
        correlation_id: str,
        timeout: float = 120.0,
    ) -> AgentMessage | None:
        """Send a message to another agent and wait for the response."""
        message = AgentMessage(
            from_agent=self.agent_type,
            to_agent=to,
            task=task,
            payload=payload,
            correlation_id=correlation_id,
        )
        self.logger.sent(message)
        return await self._bus.request_response(to.value, message, timeout=timeout)
