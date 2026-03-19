"""Planner Agent — the orchestrator that coordinates all other agents."""

import asyncio
import uuid
from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


class PlannerAgent(BaseAgent):
    agent_type = AgentType.PLANNER

    def __init__(self, bus: RedisBus):
        super().__init__(bus)
        self._pending_trips: dict[str, asyncio.Future] = {}

    async def handle(self, message: AgentMessage) -> Any:
        task = message.task

        if task == "plan_trip":
            return await self._plan_trip(message)
        elif task == "replan_trip":
            return await self._plan_trip(message, is_replan=True)

    async def _plan_trip(self, message: AgentMessage, is_replan: bool = False) -> dict:
        payload = message.payload
        destination = payload.get("destination", "Unknown")
        budget = payload.get("budget", 20000)
        duration = payload.get("duration", 3)
        preferences = payload.get("preferences", [])
        correlation_id = message.correlation_id

        action = "Re-planning" if is_replan else "Planning"
        self.logger.decision(
            correlation_id,
            f"{action} trip to {destination}",
            f"budget=₹{budget}, duration={duration} days, prefs={preferences}",
        )

        # ── Step 1: Fan out parallel requests to Transport, Stay, Context ──
        self.logger.info(correlation_id, "Step 1: Fetching transport, stays, and context in parallel")

        common_payload = {
            "destination": destination,
            "budget": budget,
            "duration": duration,
            "preferences": preferences,
        }

        transport_task = asyncio.create_task(
            self.request(AgentType.TRANSPORT, "find_transport", common_payload, correlation_id)
        )
        stay_task = asyncio.create_task(
            self.request(AgentType.STAY, "find_hotels", common_payload, correlation_id)
        )
        context_task = asyncio.create_task(
            self.request(AgentType.CONTEXT, "get_context", common_payload, correlation_id)
        )

        transport_response, stay_response, context_response = await asyncio.gather(
            transport_task, stay_task, context_task
        )

        # Extract results
        transport_data = transport_response.payload if transport_response else {}
        stay_data = stay_response.payload if stay_response else {}
        context_data = context_response.payload if context_response else {}

        transport_options = transport_data.get("options", [])
        stay_options = stay_data.get("options", [])
        recommended_transport = transport_data.get("recommended", transport_options[0] if transport_options else {})
        recommended_stay = stay_data.get("recommended", stay_options[0] if stay_options else {})

        self.logger.info(
            correlation_id,
            f"Got {len(transport_options)} transport options, {len(stay_options)} stay options",
        )

        # ── Step 2: Generate itinerary with context ──
        self.logger.info(correlation_id, "Step 2: Generating itinerary")

        itinerary_payload = {
            **common_payload,
            "context": context_data.get("weather", {}),
        }
        itinerary_response = await self.request(
            AgentType.ITINERARY, "generate_itinerary", itinerary_payload, correlation_id
        )
        itinerary_data = itinerary_response.payload if itinerary_response else {}
        itinerary = itinerary_data.get("itinerary", [])

        # ── Step 3: Budget validation ──
        self.logger.info(correlation_id, "Step 3: Validating budget")

        transport_cost = (recommended_transport.get("price", 0) * 2) if recommended_transport else 0
        stay_cost = recommended_stay.get("total_price", 0) if recommended_stay else 0
        activities_cost = itinerary_data.get("total_activities_cost", 0)

        budget_payload = {
            "budget": budget,
            "transport_cost": transport_cost,
            "stay_cost": stay_cost,
            "activities_cost": activities_cost,
            "duration": duration,
        }
        budget_response = await self.request(
            AgentType.BUDGET, "validate_budget", budget_payload, correlation_id
        )
        budget_data = budget_response.payload if budget_response else {}

        negotiation_applied = False
        changes = []

        # ── Step 4: Negotiation if budget exceeded ──
        if budget_data.get("needs_negotiation", False):
            self.logger.info(correlation_id, "Step 4: Budget exceeded — triggering negotiation")

            negotiation_payload = {
                "budget": budget,
                "overshoot": budget_data.get("overshoot", 0),
                "transport_options": transport_options,
                "stay_options": stay_options,
                "current_transport": recommended_transport,
                "current_stay": recommended_stay,
                "suggestions": budget_data.get("suggestions", []),
            }
            neg_response = await self.request(
                AgentType.NEGOTIATION, "negotiate", negotiation_payload, correlation_id
            )
            neg_data = neg_response.payload if neg_response else {}

            if neg_data.get("new_transport"):
                recommended_transport = neg_data["new_transport"]
                transport_cost = recommended_transport.get("price", 0) * 2

            if neg_data.get("new_stay"):
                recommended_stay = neg_data["new_stay"]
                stay_cost = recommended_stay.get("total_price", 0)

            changes = neg_data.get("changes", [])
            negotiation_applied = True

            # Re-validate budget after negotiation
            budget_payload["transport_cost"] = transport_cost
            budget_payload["stay_cost"] = stay_cost
            budget_response = await self.request(
                AgentType.BUDGET, "validate_budget", budget_payload, correlation_id
            )
            budget_data = budget_response.payload if budget_response else budget_data

        # ── Step 5: Assemble final response ──
        self.logger.info(correlation_id, "Step 5: Assembling final trip plan")

        # Use Cohere to generate a trip summary if available
        trip_summary = ""
        if cohere_service.is_available:
            prompt = (
                f"Write a 2-3 sentence exciting summary for a {duration}-day trip to {destination}. "
                f"Transport: {recommended_transport.get('mode', 'N/A')} by {recommended_transport.get('provider', 'N/A')}. "
                f"Stay: {recommended_stay.get('name', 'N/A')}. "
                f"Total budget: ₹{budget}. Preferences: {', '.join(preferences) if preferences else 'general'}."
            )
            trip_summary = await cohere_service.generate(prompt, max_tokens=150, temperature=0.8)

        final_result = {
            "trip_id": correlation_id,
            "destination": destination,
            "duration": duration,
            "summary": trip_summary,
            "transport": {
                "options": transport_options,
                "selected": recommended_transport,
            },
            "stay": {
                "options": stay_options,
                "selected": recommended_stay,
            },
            "itinerary": itinerary,
            "cost_breakdown": budget_data.get("breakdown", {}),
            "context": {
                "weather": context_data.get("weather", {}),
                "events": context_data.get("events", []),
                "crowd_level": context_data.get("crowd_level", "unknown"),
                "tips": context_data.get("tips", []),
            },
            "negotiation_applied": negotiation_applied,
            "negotiation_changes": changes,
            "llm_itinerary_suggestions": itinerary_data.get("llm_suggestions", ""),
            "status": "completed",
        }

        self.logger.decision(
            correlation_id,
            f"Trip plan completed — total ₹{budget_data.get('breakdown', {}).get('total', 0):.0f}",
            f"within_budget={budget_data.get('breakdown', {}).get('within_budget', '?')}",
        )

        return final_result
