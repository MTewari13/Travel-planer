"""Context Agent — provides weather, events, crowd data, and tips."""

import json
import os
from datetime import datetime
from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "context.json")

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]


class ContextAgent(BaseAgent):
    agent_type = AgentType.CONTEXT

    def __init__(self, bus: RedisBus):
        super().__init__(bus)
        with open(DATA_PATH, "r") as f:
            self._data = json.load(f)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        destination = payload.get("destination", "").strip()
        travel_month = payload.get("month", "").lower()
        duration = payload.get("duration", 3)

        # Default to current month if not specified
        if not travel_month:
            travel_month = MONTH_NAMES[datetime.utcnow().month - 1]

        self.logger.decision(
            message.correlation_id,
            f"Fetching context for {destination}",
            f"month={travel_month}",
        )

        # Find destination
        dest_key = None
        for key in self._data:
            if key.lower() == destination.lower():
                dest_key = key
                break

        if not dest_key:
            self.logger.warning(
                message.correlation_id,
                f"No context data for '{destination}', using defaults",
            )
            return {
                "weather": {"condition": "Data not available", "temp_high": 30, "temp_low": 20},
                "events": [],
                "crowd_level": "unknown",
                "best_time_to_visit": "Check local tourism website",
                "tips": [],
            }

        dest_data = self._data[dest_key]

        # Weather for the travel month
        weather_data = dest_data["weather"]
        weather = weather_data.get(travel_month, weather_data.get("default", {}))

        # Events during travel period
        events = [
            event for event in dest_data.get("events", [])
            if event.get("month", "").lower() == travel_month
        ]

        # Crowd level
        crowd_info = dest_data.get("crowd_level", {})
        if travel_month in crowd_info.get("peak", []):
            crowd_level = "high"
        elif travel_month in crowd_info.get("moderate", []):
            crowd_level = "moderate"
        else:
            crowd_level = "low"

        best_time = dest_data.get("best_time_to_visit", "")
        tips = dest_data.get("tips", [])

        # Enhance tips with Cohere if available
        if cohere_service.is_available:
            prompt = (
                f"Give 2-3 specific, practical travel tips for visiting {destination} in {travel_month}. "
                f"Weather: {weather.get('condition', 'N/A')}. Crowd level: {crowd_level}. "
                f"Duration: {duration} days. Be concise, one line per tip."
            )
            llm_tips = await cohere_service.generate(prompt, max_tokens=200, temperature=0.5)
            if llm_tips:
                extra_tips = [t.strip().lstrip("•-123456789. ") for t in llm_tips.split("\n") if t.strip()]
                tips = tips + extra_tips[:3]
                self.logger.decision(
                    message.correlation_id,
                    "Enhanced tips with Cohere LLM",
                )

        self.logger.info(
            message.correlation_id,
            f"Context: weather={weather.get('condition')}, crowd={crowd_level}, events={len(events)}",
        )

        return {
            "weather": weather,
            "events": events,
            "crowd_level": crowd_level,
            "best_time_to_visit": best_time,
            "tips": tips,
        }
