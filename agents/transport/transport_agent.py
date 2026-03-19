"""Transport Agent — uses Cohere LLM to generate transport options for any destination."""

from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


FALLBACK_OPTIONS = [
    {"mode": "flight", "provider": "Standard Airlines", "departure": "08:00", "arrival": "12:00", "duration_hours": 4.0, "price": 5000, "rating": 4.0},
    {"mode": "train", "provider": "Express Rail", "departure": "16:00", "arrival": "06:00+1", "duration_hours": 14.0, "price": 1500, "rating": 4.2},
    {"mode": "bus", "provider": "Comfort Bus", "departure": "20:00", "arrival": "08:00+1", "duration_hours": 12.0, "price": 800, "rating": 3.8},
]


class TransportAgent(BaseAgent):
    agent_type = AgentType.TRANSPORT

    def __init__(self, bus: RedisBus):
        super().__init__(bus)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        destination = payload.get("destination", "").strip()
        origin = payload.get("origin", "Delhi").strip()
        budget = payload.get("budget", float("inf"))
        preferences = payload.get("preferences", [])

        self.logger.decision(
            message.correlation_id,
            f"Searching transport from {origin} to {destination}",
            f"budget={budget}, preferences={preferences}",
        )

        # ── Generate transport options via Cohere LLM ──
        prompt = (
            f"Generate exactly 6 realistic transport options from {origin} to {destination}. "
            f"Include a mix of flights, trains, and buses (or only flights if international). "
            f"For each option provide: mode (flight/train/bus), provider (real airline/train/bus company name), "
            f"departure (HH:MM format), arrival (HH:MM or HH:MM+1 for next day), "
            f"duration_hours (number), price (in Indian Rupees ₹, realistic), rating (1.0-5.0).\n\n"
            f"Return a JSON array of objects. Example format:\n"
            f'[{{"mode": "flight", "provider": "IndiGo", "departure": "06:00", "arrival": "08:30", '
            f'"duration_hours": 2.5, "price": 4500, "rating": 4.2}}]\n\n'
            f"Make prices realistic for {origin} to {destination} route. "
            f"Sort by a mix of value (price/rating ratio)."
        )

        options = await cohere_service.generate_json(
            prompt=prompt,
            fallback=FALLBACK_OPTIONS,
            max_tokens=1500,
            temperature=0.6,
        )

        # Validate we got a list
        if not isinstance(options, list) or len(options) == 0:
            self.logger.warning(
                message.correlation_id,
                f"LLM returned invalid transport data, using fallback",
            )
            options = FALLBACK_OPTIONS

        # Ensure all options have required fields
        valid_options = []
        for opt in options:
            if isinstance(opt, dict) and "price" in opt and "provider" in opt:
                opt.setdefault("mode", "flight")
                opt.setdefault("departure", "08:00")
                opt.setdefault("arrival", "12:00")
                opt.setdefault("duration_hours", 4.0)
                opt.setdefault("rating", 3.5)
                opt["price"] = float(opt["price"])
                opt["rating"] = float(opt.get("rating", 3.5))
                opt["duration_hours"] = float(opt.get("duration_hours", 4.0))
                valid_options.append(opt)

        if not valid_options:
            valid_options = FALLBACK_OPTIONS

        # Filter by budget (transport shouldn't exceed 40% of total budget)
        transport_budget = budget * 0.4
        affordable = [opt for opt in valid_options if opt["price"] <= transport_budget]
        if not affordable:
            affordable = sorted(valid_options, key=lambda x: x["price"])[:3]

        self.logger.decision(
            message.correlation_id,
            f"Found {len(affordable)} affordable options from {len(valid_options)} total",
            f"transport_budget={transport_budget}",
        )

        # Use Cohere to rank if preferences exist
        if cohere_service.is_available and preferences:
            query = f"Best transport from {origin} to {destination} for someone who prefers: {', '.join(preferences)}"
            descriptions = [
                f"{opt['mode']} by {opt['provider']} — ₹{opt['price']}, {opt['duration_hours']}h, rating: {opt.get('rating', 'N/A')}"
                for opt in affordable
            ]
            rankings = await cohere_service.rank_options(query, descriptions)
            ranked_options = [affordable[r["index"]] for r in rankings]
            self.logger.decision(
                message.correlation_id,
                "Ranked transport options using Cohere reranker",
            )
        else:
            ranked_options = sorted(
                affordable,
                key=lambda x: x["price"] / max(x.get("rating", 3.0), 1),
            )

        # Compute total price for each (round trip ≈ 2x)
        result_options = []
        for opt in ranked_options:
            result_options.append({
                **opt,
                "total_price": opt["price"] * 2,
            })

        return {
            "destination": destination,
            "options": result_options,
            "cheapest": result_options[-1] if result_options else None,
            "recommended": result_options[0] if result_options else None,
        }
