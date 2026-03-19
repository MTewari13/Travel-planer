"""A2A message types and agent registry."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class AgentType(str, Enum):
    PLANNER = "planner-agent"
    TRANSPORT = "transport-agent"
    STAY = "stay-agent"
    ITINERARY = "itinerary-agent"
    BUDGET = "budget-agent"
    CONTEXT = "context-agent"
    NEGOTIATION = "negotiation-agent"
    GATEWAY = "api-gateway"


class AgentMessage(BaseModel):
    """Standard A2A message format for inter-agent communication."""

    from_agent: AgentType
    to_agent: AgentType
    task: str
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    reply_to: Optional[str] = None  # channel to send response back to

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}
