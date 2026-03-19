"""Budget Agent — aggregates costs and enforces budget constraints."""

from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus


class BudgetAgent(BaseAgent):
    agent_type = AgentType.BUDGET

    def __init__(self, bus: RedisBus):
        super().__init__(bus)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        budget = payload.get("budget", 0)
        transport_cost = payload.get("transport_cost", 0)
        stay_cost = payload.get("stay_cost", 0)
        activities_cost = payload.get("activities_cost", 0)
        food_estimate = payload.get("food_estimate", 0)
        duration = payload.get("duration", 1)

        # Estimate food cost if not provided (₹500-800/day depending on destination)
        if food_estimate == 0:
            food_estimate = duration * 600

        # Miscellaneous: 5% of budget or ₹500/day
        misc_estimate = max(budget * 0.05, duration * 500)

        total = transport_cost + stay_cost + activities_cost + food_estimate + misc_estimate

        within_budget = total <= budget
        savings = budget - total
        overshoot = total - budget if not within_budget else 0
        overshoot_pct = (overshoot / budget * 100) if budget > 0 and not within_budget else 0

        self.logger.decision(
            message.correlation_id,
            f"Budget {'✅ OK' if within_budget else '❌ EXCEEDED'}",
            f"total=₹{total:.0f} vs budget=₹{budget:.0f} (diff=₹{savings:.0f})",
        )

        breakdown = {
            "transport": transport_cost,
            "accommodation": stay_cost,
            "activities": activities_cost,
            "food": food_estimate,
            "miscellaneous": misc_estimate,
            "total": total,
            "budget": budget,
            "within_budget": within_budget,
            "savings": savings if within_budget else 0,
        }

        # Generate suggestions if over budget
        suggestions = []
        if not within_budget:
            self.logger.decision(
                message.correlation_id,
                f"Over budget by ₹{overshoot:.0f} ({overshoot_pct:.1f}%)",
                "Generating cost-cutting suggestions",
            )

            if transport_cost > budget * 0.3:
                suggestions.append({
                    "area": "transport",
                    "suggestion": "Consider train/bus instead of flight to save ₹2000-4000",
                    "potential_saving": transport_cost * 0.4,
                })

            if stay_cost > budget * 0.3:
                suggestions.append({
                    "area": "accommodation",
                    "suggestion": "Switch to a budget hotel or hostel to save significantly",
                    "potential_saving": stay_cost * 0.5,
                })

            if activities_cost > budget * 0.2:
                suggestions.append({
                    "area": "activities",
                    "suggestion": "Choose free/low-cost attractions over premium ones",
                    "potential_saving": activities_cost * 0.3,
                })

            suggestions.append({
                "area": "food",
                "suggestion": "Eat at local restaurants and street stalls instead of fine dining",
                "potential_saving": food_estimate * 0.3,
            })

        return {
            "breakdown": breakdown,
            "within_budget": within_budget,
            "overshoot": overshoot,
            "overshoot_percentage": overshoot_pct,
            "suggestions": suggestions,
            "needs_negotiation": not within_budget,
        }
