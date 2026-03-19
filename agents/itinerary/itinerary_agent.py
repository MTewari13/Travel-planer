"""Itinerary Agent — generates day-wise travel plans."""

import json
import os
import random
from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "activities.json")

TIME_SLOTS = [
    ("09:00", "11:00"),
    ("11:30", "13:00"),
    ("14:00", "16:00"),
    ("16:30", "18:00"),
    ("19:00", "21:00"),
]


class ItineraryAgent(BaseAgent):
    agent_type = AgentType.ITINERARY

    def __init__(self, bus: RedisBus):
        super().__init__(bus)
        with open(DATA_PATH, "r") as f:
            self._data = json.load(f)

    async def handle(self, message: AgentMessage) -> Any:
        payload = message.payload
        destination = payload.get("destination", "").strip()
        duration = payload.get("duration", 3)
        preferences = payload.get("preferences", [])
        budget = payload.get("budget", float("inf"))
        context = payload.get("context", {})

        self.logger.decision(
            message.correlation_id,
            f"Generating {duration}-day itinerary for {destination}",
            f"preferences={preferences}",
        )

        # Find destination data
        dest_key = None
        for key in self._data:
            if key.lower() == destination.lower():
                dest_key = key
                break

        if not dest_key:
            dest_key = list(self._data.keys())[0]

        dest_data = self._data[dest_key]

        # Build activity pool prioritized by preferences
        all_activities = []
        for category, activities in dest_data.items():
            for act in activities:
                priority = 2 if category.lower() in [p.lower() for p in preferences] else 1
                all_activities.append({**act, "_priority": priority, "_category": category})

        # Sort: preferred categories first, then by cost (lower first)
        all_activities.sort(key=lambda x: (-x["_priority"], x["cost"]))

        # Use Cohere to generate an enhanced itinerary description if available
        llm_suggestions = ""
        if cohere_service.is_available:
            activity_list = "\n".join(
                f"- {a['name']}: {a['description']} (₹{a['cost']})" for a in all_activities[:15]
            )
            weather_info = ""
            if context.get("weather"):
                w = context["weather"]
                weather_info = f"\nWeather: {w.get('condition', 'N/A')}, High: {w.get('temp_high', 'N/A')}°C"

            prompt = (
                f"Create an optimized {duration}-day itinerary for {destination}.{weather_info}\n"
                f"Traveler preferences: {', '.join(preferences) if preferences else 'general tourism'}\n"
                f"Available activities:\n{activity_list}\n\n"
                f"Suggest 3-4 activities per day, considering logical grouping by location and time of day. "
                f"Reply as a brief bullet list, day by day."
            )
            llm_suggestions = await cohere_service.generate(prompt, max_tokens=600)
            self.logger.decision(
                message.correlation_id,
                "Enhanced itinerary with Cohere LLM suggestions",
            )

        # Build day-wise plan
        activity_pool = list(all_activities)
        used_activities = set()
        itinerary = []
        activities_budget = budget * 0.15  # 15% of total budget for activities
        daily_activity_budget = activities_budget / max(duration, 1)

        for day_num in range(1, duration + 1):
            day_activities = []
            day_meals = []
            day_cost = 0.0

            for i, (start, end) in enumerate(TIME_SLOTS):
                if not activity_pool:
                    break

                # Midday slot → meal
                if i in [1, 4]:
                    food_activities = [
                        a for a in activity_pool
                        if a["_category"] == "food" and a["name"] not in used_activities
                    ]
                    if food_activities:
                        meal = food_activities[0]
                        activity_pool.remove(meal)
                        used_activities.add(meal["name"])
                        day_meals.append({
                            "time": f"{start} - {end}",
                            "name": meal["name"],
                            "description": meal["description"],
                            "cost": meal["cost"],
                            "category": "food",
                        })
                        day_cost += meal["cost"]
                        continue

                # Pick best available activity
                available = [
                    a for a in activity_pool
                    if a["name"] not in used_activities and a["_category"] != "food"
                ]
                if available:
                    # Prefer activities within daily budget
                    within_budget = [a for a in available if day_cost + a["cost"] <= daily_activity_budget]
                    pick = within_budget[0] if within_budget else available[0]

                    activity_pool.remove(pick)
                    used_activities.add(pick["name"])
                    day_activities.append({
                        "time": f"{start} - {end}",
                        "name": pick["name"],
                        "description": pick["description"],
                        "cost": pick["cost"],
                        "category": pick.get("category", pick["_category"]),
                    })
                    day_cost += pick["cost"]

            itinerary.append({
                "day": day_num,
                "activities": day_activities,
                "meals": day_meals,
                "day_cost": day_cost,
            })

            self.logger.info(
                message.correlation_id,
                f"Day {day_num}: {len(day_activities)} activities, {len(day_meals)} meals, cost=₹{day_cost}",
            )

        total_activities_cost = sum(d["day_cost"] for d in itinerary)

        return {
            "destination": destination,
            "duration": duration,
            "itinerary": itinerary,
            "total_activities_cost": total_activities_cost,
            "llm_suggestions": llm_suggestions,
        }
