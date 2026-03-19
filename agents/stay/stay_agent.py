"""Stay Agent — uses Cohere LLM to generate accommodation options for any destination."""

from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


FALLBACK_STAYS = [
    {"name": "Standard Hotel", "type": "hotel", "price_per_night": 3000, "rating": 4.0, "distance_to_center_km": 2.0, "amenities": ["wifi", "restaurant"]},
    {"name": "Budget Inn", "type": "hotel", "price_per_night": 1200, "rating": 3.5, "distance_to_center_km": 1.0, "amenities": ["wifi", "breakfast"]},
    {"name": "Backpacker Hostel", "type": "hostel", "price_per_night": 500, "rating": 4.0, "distance_to_center_km": 0.8, "amenities": ["wifi", "common_area"]},
]


class StayAgent(BaseAgent):
    agent_type = AgentType.STAY

    def __init__(self, bus: RedisBus):
        super().__init__(bus)

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

        # ── Generate stay options via Cohere LLM ──
        prompt = (
            f"Generate exactly 6 realistic accommodation options in {destination}. "
            f"Include a mix of luxury resorts, mid-range hotels, and budget hostels. "
            f"For each provide: name (real or realistic hotel name), type (resort/hotel/hostel), "
            f"price_per_night (in Indian Rupees ₹, realistic for {destination}), "
            f"rating (1.0-5.0), distance_to_center_km (number), "
            f"amenities (array of strings like pool, spa, wifi, restaurant, gym, beach_access).\n\n"
            f"Return a JSON array of objects. Example format:\n"
            f'[{{"name": "Taj Palace", "type": "hotel", "price_per_night": 5000, '
            f'"rating": 4.5, "distance_to_center_km": 2.0, '
            f'"amenities": ["pool", "restaurant", "wifi"]}}]\n\n'
            f"Make prices realistic for {destination}. Sort by rating descending."
        )

        stays = await cohere_service.generate_json(
            prompt=prompt,
            fallback=FALLBACK_STAYS,
            max_tokens=1500,
            temperature=0.6,
        )

        # Validate we got a list
        if not isinstance(stays, list) or len(stays) == 0:
            self.logger.warning(
                message.correlation_id,
                f"LLM returned invalid stay data, using fallback",
            )
            stays = FALLBACK_STAYS

        # Ensure all stays have required fields and compute total_price
        enriched = []
        for stay in stays:
            if isinstance(stay, dict) and "price_per_night" in stay and "name" in stay:
                stay.setdefault("type", "hotel")
                stay.setdefault("rating", 3.5)
                stay.setdefault("distance_to_center_km", 2.0)
                stay.setdefault("amenities", ["wifi"])
                stay["price_per_night"] = float(stay["price_per_night"])
                stay["rating"] = float(stay.get("rating", 3.5))
                stay["distance_to_center_km"] = float(stay.get("distance_to_center_km", 2.0))
                total = stay["price_per_night"] * duration
                enriched.append({**stay, "total_price": total})

        if not enriched:
            enriched = [{**s, "total_price": s["price_per_night"] * duration} for s in FALLBACK_STAYS]

        # Calculate stay budget (roughly 35% of total budget)
        stay_budget = budget * 0.35
        max_per_night = stay_budget / max(duration, 1)

        affordable = [s for s in enriched if s["price_per_night"] <= max_per_night]
        if not affordable:
            affordable = sorted(enriched, key=lambda x: x["price_per_night"])[:3]

        self.logger.decision(
            message.correlation_id,
            f"Found {len(affordable)} affordable stays from {len(enriched)} total",
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
