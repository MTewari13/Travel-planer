"""Context Agent — uses Cohere LLM to provide weather, events, crowd data, and tips for any destination."""

from datetime import datetime
from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]

FALLBACK_CONTEXT = {
    "weather": {"temp_high": 30, "temp_low": 20, "rainfall_mm": 50, "humidity": 60, "condition": "Pleasant weather"},
    "events": [],
    "crowd_level": "moderate",
    "best_time_to_visit": "Check local tourism website",
    "tips": ["Research local customs before visiting", "Book accommodation in advance", "Stay hydrated"],
}


class ContextAgent(BaseAgent):
    agent_type = AgentType.CONTEXT

    def __init__(self, bus: RedisBus):
        super().__init__(bus)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        destination = payload.get("destination", "").strip()
        travel_month = payload.get("month", "").lower()
        duration = payload.get("duration", 3)
        preferences = payload.get("preferences", [])

        # Default to current month if not specified
        if not travel_month:
            travel_month = MONTH_NAMES[datetime.utcnow().month - 1]

        self.logger.decision(
            message.correlation_id,
            f"Fetching context for {destination}",
            f"month={travel_month}",
        )

        # ── Generate context data via Cohere LLM ──
        prompt = (
            f"Provide travel context information for {destination} during {travel_month}. "
            f"Return a JSON object with these exact keys:\n"
            f"- weather: {{temp_high (°C number), temp_low (°C number), rainfall_mm (number), humidity (number 0-100), condition (string description)}}\n"
            f"- events: array of {{name, month, description}} for events happening around {travel_month}\n"
            f"- crowd_level: one of 'high', 'moderate', or 'low'\n"
            f"- best_time_to_visit: string\n"
            f"- tips: array of 4-5 practical travel tip strings\n\n"
            f"Make all data realistic and specific to {destination} in {travel_month}.\n"
            f'Example: {{"weather": {{"temp_high": 35, "temp_low": 25, "rainfall_mm": 10, "humidity": 40, '
            f'"condition": "Hot and dry"}}, "events": [{{"name": "Festival", "month": "{travel_month}", '
            f'"description": "Annual cultural festival"}}], "crowd_level": "moderate", '
            f'"best_time_to_visit": "November to February", "tips": ["Carry sunscreen"]}}'
        )

        context_data = await cohere_service.generate_json(
            prompt=prompt,
            fallback=FALLBACK_CONTEXT,
            max_tokens=1500,
            temperature=0.6,
        )

        # Validate the response structure
        if not isinstance(context_data, dict):
            self.logger.warning(
                message.correlation_id,
                "LLM returned invalid context data, using fallback",
            )
            context_data = FALLBACK_CONTEXT

        # Ensure all required keys exist with defaults
        weather = context_data.get("weather", FALLBACK_CONTEXT["weather"])
        if not isinstance(weather, dict):
            weather = FALLBACK_CONTEXT["weather"]
        weather.setdefault("temp_high", 30)
        weather.setdefault("temp_low", 20)
        weather.setdefault("rainfall_mm", 50)
        weather.setdefault("humidity", 60)
        weather.setdefault("condition", "Data not available")

        # Ensure numeric types
        for key in ["temp_high", "temp_low", "rainfall_mm", "humidity"]:
            try:
                weather[key] = float(weather[key])
            except (ValueError, TypeError):
                weather[key] = FALLBACK_CONTEXT["weather"][key]

        events = context_data.get("events", [])
        if not isinstance(events, list):
            events = []

        crowd_level = context_data.get("crowd_level", "moderate")
        if crowd_level not in ("high", "moderate", "low"):
            crowd_level = "moderate"

        best_time = context_data.get("best_time_to_visit", "Check local tourism website")
        tips = context_data.get("tips", [])
        if not isinstance(tips, list):
            tips = []

        # Enhance tips with Cohere if preferences given
        if cohere_service.is_available and preferences:
            enhance_prompt = (
                f"Give 2-3 specific, practical travel tips for visiting {destination} in {travel_month}. "
                f"Weather: {weather.get('condition', 'N/A')}. Crowd level: {crowd_level}. "
                f"Traveler preferences: {', '.join(preferences)}. "
                f"Duration: {duration} days. Be concise, one line per tip."
            )
            llm_tips = await cohere_service.generate(enhance_prompt, max_tokens=200, temperature=0.5)
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
