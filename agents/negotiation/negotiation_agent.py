"""Negotiation Agent — resolves budget conflicts by finding cheaper alternatives."""

from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


class NegotiationAgent(BaseAgent):
    agent_type = AgentType.NEGOTIATION

    def __init__(self, bus: RedisBus):
        super().__init__(bus)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        budget = payload.get("budget", 0)
        overshoot = payload.get("overshoot", 0)
        transport_options = payload.get("transport_options", [])
        stay_options = payload.get("stay_options", [])
        current_transport = payload.get("current_transport", {})
        current_stay = payload.get("current_stay", {})
        suggestions = payload.get("suggestions", [])

        self.logger.decision(
            message.correlation_id,
            f"Negotiating — need to save ₹{overshoot:.0f}",
            f"Current transport: ₹{current_transport.get('price', 0) * 2}, stay: ₹{current_stay.get('total_price', 0)}",
        )

        changes = []
        new_transport = None
        new_stay = None
        total_saved = 0

        # Strategy 1: Find cheaper transport
        if transport_options and current_transport:
            current_transport_total = current_transport.get("price", 0) * 2
            cheaper_transports = [
                t for t in transport_options
                if (t.get("price", 0) * 2) < current_transport_total
            ]
            if cheaper_transports:
                # Pick the best value (cheapest with decent rating)
                cheaper_transports.sort(
                    key=lambda x: x["price"] / max(x.get("rating", 3.0), 1)
                )
                new_transport = cheaper_transports[0]
                saving = current_transport_total - (new_transport["price"] * 2)
                total_saved += saving
                changes.append(
                    f"🔄 Switch transport: {current_transport.get('provider', '?')} → "
                    f"{new_transport['provider']} (save ₹{saving:.0f})"
                )
                self.logger.decision(
                    message.correlation_id,
                    f"Transport switch: save ₹{saving:.0f}",
                    f"{current_transport.get('provider')} → {new_transport['provider']}",
                )

        # Strategy 2: Find cheaper stay
        if stay_options and current_stay and total_saved < overshoot:
            current_stay_total = current_stay.get("total_price", 0)
            cheaper_stays = [
                s for s in stay_options
                if s.get("total_price", 0) < current_stay_total
            ]
            if cheaper_stays:
                # Pick the one with best rating among cheaper options
                cheaper_stays.sort(key=lambda x: -x.get("rating", 0))
                new_stay = cheaper_stays[0]
                saving = current_stay_total - new_stay["total_price"]
                total_saved += saving
                changes.append(
                    f"🏨 Switch stay: {current_stay.get('name', '?')} → "
                    f"{new_stay['name']} (save ₹{saving:.0f})"
                )
                self.logger.decision(
                    message.correlation_id,
                    f"Stay switch: save ₹{saving:.0f}",
                    f"{current_stay.get('name')} → {new_stay['name']}",
                )

        # Strategy 3: Use Cohere for creative suggestions
        if cohere_service.is_available and total_saved < overshoot:
            remaining = overshoot - total_saved
            prompt = (
                f"A traveler needs to save ₹{remaining:.0f} more on their trip. "
                f"Current budget: ₹{budget}. Overshoot: ₹{overshoot:.0f}. "
                f"Already saving ₹{total_saved:.0f} by switching transport/hotel. "
                f"Give 2-3 creative, specific cost-saving tips. One line each."
            )
            llm_tips = await cohere_service.generate(prompt, max_tokens=200, temperature=0.5)
            if llm_tips:
                for tip in llm_tips.strip().split("\n"):
                    tip = tip.strip().lstrip("•-123456789. ")
                    if tip:
                        changes.append(f"💡 {tip}")

        resolved = total_saved >= overshoot

        self.logger.decision(
            message.correlation_id,
            f"Negotiation {'✅ RESOLVED' if resolved else '⚠️ PARTIAL'}",
            f"Saved ₹{total_saved:.0f} of ₹{overshoot:.0f} needed",
        )

        original_cost = (
            current_transport.get("price", 0) * 2 + current_stay.get("total_price", 0)
        )
        optimized_cost = original_cost - total_saved

        return {
            "resolved": resolved,
            "original_cost": original_cost,
            "optimized_cost": optimized_cost,
            "total_saved": total_saved,
            "changes": changes,
            "new_transport": new_transport,
            "new_stay": new_stay,
        }
