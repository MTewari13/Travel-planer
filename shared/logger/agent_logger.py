"""Structured agent logger with decision tracing for observability."""

import logging
from datetime import datetime

from shared.types.message import AgentMessage


class AgentLogger:
    """Custom logger that formats messages with agent identity and correlation IDs.

    Output format: [AgentName] [corr_id] action — details
    This makes agent decision chains traceable across the entire system.
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self._logger = logging.getLogger(f"agent.{agent_name}")
        self._logs: list[str] = []

    def _format(self, correlation_id: str, action: str, details: str = "") -> str:
        timestamp = datetime.utcnow().isoformat()
        msg = f"[{self.agent_name}] [{correlation_id[:8]}] {action}"
        if details:
            msg += f" — {details}"
        return msg

    def decision(self, correlation_id: str, decision: str, reasoning: str = ""):
        """Log an agent decision with optional reasoning."""
        msg = self._format(correlation_id, f"DECISION: {decision}", reasoning)
        self._logger.info(msg)
        self._logs.append(msg)

    def received(self, message: AgentMessage):
        """Log that a message was received."""
        msg = self._format(
            message.correlation_id,
            f"RECEIVED task={message.task}",
            f"from={message.from_agent}",
        )
        self._logger.info(msg)
        self._logs.append(msg)

    def sent(self, message: AgentMessage):
        """Log that a message was sent."""
        msg = self._format(
            message.correlation_id,
            f"SENT task={message.task}",
            f"to={message.to_agent}",
        )
        self._logger.info(msg)
        self._logs.append(msg)

    def info(self, correlation_id: str, details: str):
        msg = self._format(correlation_id, "INFO", details)
        self._logger.info(msg)
        self._logs.append(msg)

    def warning(self, correlation_id: str, details: str):
        msg = self._format(correlation_id, "WARNING", details)
        self._logger.warning(msg)
        self._logs.append(msg)

    def error(self, correlation_id: str, details: str):
        msg = self._format(correlation_id, "ERROR", details)
        self._logger.error(msg)
        self._logs.append(msg)

    def get_logs(self) -> list[str]:
        """Return all captured logs for this agent."""
        return list(self._logs)

    def clear_logs(self):
        """Clear captured logs."""
        self._logs.clear()
