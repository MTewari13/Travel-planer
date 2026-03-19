"""Stay Agent — finds hotels, hostels, and resorts for a given destination."""

import json
import os
from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "stays.json")


class StayAgent(BaseAgent):
    agent_type = AgentType.STAY

    def __init__(self, bus: RedisBus):
        super().__init__(bus)
        with open(DATA_PATH, "r") as f:
            self._data = json.load(f)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        destination = payload.get("destination", "").strip()
        budget = payload.get("budget", float("inf"))
        duration = payload.get("duration", 1)
        preferences = payload.get("preferences", [])

        self.logger.decision(
            message.correlation_id,
            f"Searching stays in {destination}",
            f"budget={budget}, duration={duration} nights, preferences={preferences}",
        )

        # Find destination data
        dest_key = None
        for key in self._data:
            if key.lower() == destination.lower():
                dest_key = key
                break

        if not dest_key:
            self.logger.warning(
                message.correlation_id,
                f"No stay data for '{destination}', returning defaults",
            )
            dest_key = list(self._data.keys())[0]

        stays = self._data[dest_key]

        # Calculate stay budget (roughly 35% of total budget)
        stay_budget = budget * 0.35
        max_per_night = stay_budget / max(duration, 1)

        # Add total_price and filter
        enriched = []
        for stay in stays:
            total = stay["price_per_night"] * duration
            enriched.append({**stay, "total_price": total})

        affordable = [s for s in enriched if s["price_per_night"] <= max_per_night]
        if not affordable:
            affordable = sorted(enriched, key=lambda x: x["price_per_night"])[:3]

        self.logger.decision(
            message.correlation_id,
            f"Found {len(affordable)} affordable stays",
            f"max_per_night={max_per_night:.0f}",
        )

        # Determine stay type preference
        luxury_prefs = {"luxury", "spa", "resort", "premium"}
        budget_prefs = {"budget", "backpacker", "hostel", "cheap"}
        pref_set = set(p.lower() for p in preferences)

        if pref_set & luxury_prefs:
            preferred_types = ["resort", "hotel"]
        elif pref_set & budget_prefs:
            preferred_types = ["hostel", "hotel"]
        else:
            preferred_types = ["hotel", "resort", "hostel"]

        # Use Cohere to rank if available
        if cohere_service.is_available and preferences:
            query = f"Best accommodation in {destination} for: {', '.join(preferences)}. Budget ₹{max_per_night:.0f}/night."
            descriptions = [
                f"{s['name']} ({s['type']}) — ₹{s['price_per_night']}/night, rating: {s['rating']}, {s['distance_to_center_km']}km from center, amenities: {', '.join(s.get('amenities', []))}"
                for s in affordable
            ]
            rankings = await cohere_service.rank_options(query, descriptions)
            ranked = [affordable[r["index"]] for r in rankings]
            self.logger.decision(
                message.correlation_id,
                "Ranked stays using Cohere reranker",
            )
        else:
            # Fallback: score by type preference, rating, and price
            def score(stay):
                type_score = 10 if stay["type"] in preferred_types[:1] else 5 if stay["type"] in preferred_types else 0
                return type_score + stay["rating"] - (stay["price_per_night"] / 5000)

            ranked = sorted(affordable, key=score, reverse=True)

        return {
            "destination": destination,
            "duration": duration,
            "options": ranked,
            "recommended": ranked[0] if ranked else None,
            "cheapest": min(ranked, key=lambda x: x["price_per_night"]) if ranked else None,
        }
