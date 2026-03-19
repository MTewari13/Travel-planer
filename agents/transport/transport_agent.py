"""Transport Agent — finds flights, trains, and buses for a given destination."""

import json
import os
from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "transport.json")


class TransportAgent(BaseAgent):
    agent_type = AgentType.TRANSPORT

    def __init__(self, bus: RedisBus):
        super().__init__(bus)
        with open(DATA_PATH, "r") as f:
            self._data = json.load(f)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        destination = payload.get("destination", "").strip()
        budget = payload.get("budget", float("inf"))
        preferences = payload.get("preferences", [])

        self.logger.decision(
            message.correlation_id,
            f"Searching transport to {destination}",
            f"budget={budget}, preferences={preferences}",
        )

        # Find destination data (case-insensitive)
        dest_key = None
        for key in self._data:
            if key.lower() == destination.lower():
                dest_key = key
                break

        if not dest_key:
            self.logger.warning(
                message.correlation_id,
                f"No transport data for '{destination}', returning defaults",
            )
            dest_key = list(self._data.keys())[0]

        dest_data = self._data[dest_key]

        # Collect all options
        all_options = []
        for mode_key in ["flights", "trains", "buses"]:
            options = dest_data.get(mode_key, [])
            all_options.extend(options)

        # Filter by budget (transport shouldn't exceed 40% of total budget)
        transport_budget = budget * 0.4
        affordable = [opt for opt in all_options if opt["price"] <= transport_budget]
        if not affordable:
            affordable = sorted(all_options, key=lambda x: x["price"])[:3]

        self.logger.decision(
            message.correlation_id,
            f"Found {len(affordable)} affordable options",
            f"transport_budget={transport_budget}",
        )

        # Use Cohere to rank if available and preferences exist
        if cohere_service.is_available and preferences:
            query = f"Best transport to {destination} for someone who prefers: {', '.join(preferences)}"
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
            # Fallback: sort by price-to-rating ratio
            ranked_options = sorted(
                affordable,
                key=lambda x: x["price"] / max(x.get("rating", 3.0), 1),
            )

        # Compute total price for each (round trip ≈ 2x)
        result_options = []
        for opt in ranked_options:
            result_options.append({
                **opt,
                "total_price": opt["price"] * 2,  # round-trip estimate
            })

        return {
            "destination": destination,
            "options": result_options,
            "cheapest": result_options[-1] if result_options else None,
            "recommended": result_options[0] if result_options else None,
        }
