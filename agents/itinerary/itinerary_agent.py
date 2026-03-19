"""Itinerary Agent — uses Cohere LLM to generate day-wise travel plans for any destination."""

import random
from typing import Any

from shared.agent_sdk.base_agent import BaseAgent
from shared.types.message import AgentMessage, AgentType
from shared.message_bus.redis_bus import RedisBus
from shared.cohere_service import cohere_service


TIME_SLOTS = [
    ("09:00", "11:00"),
    ("11:30", "13:00"),
    ("14:00", "16:00"),
    ("16:30", "18:00"),
    ("19:00", "21:00"),
]

FALLBACK_ACTIVITIES = {
    "sightseeing": [
        {"name": "City Landmark Tour", "description": "Visit the most iconic landmarks", "cost": 500, "duration": "3h", "category": "sightseeing"},
        {"name": "Museum Visit", "description": "Explore local art and history", "cost": 300, "duration": "2h", "category": "sightseeing"},
    ],
    "food": [
        {"name": "Local Cuisine Experience", "description": "Try the best local dishes", "cost": 600, "duration": "1.5h", "category": "food"},
        {"name": "Street Food Walk", "description": "Guided street food tour", "cost": 300, "duration": "2h", "category": "food"},
    ],
    "adventure": [
        {"name": "Outdoor Adventure Activity", "description": "Exciting outdoor experience", "cost": 1500, "duration": "3h", "category": "adventure"},
    ],
}


class ItineraryAgent(BaseAgent):
    agent_type = AgentType.ITINERARY

    def __init__(self, bus: RedisBus):
        super().__init__(bus)

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

        # ── Generate activities via Cohere LLM ──
        pref_str = ", ".join(preferences) if preferences else "general tourism"
        prompt = (
            f"Generate a list of tourist activities in {destination}, grouped by category. "
            f"Categories to include: sightseeing, food, nightlife, adventure, beach, shopping, wellness. "
            f"Only include categories relevant to {destination}. "
            f"For each activity provide: name (specific real place/activity name), "
            f"description (1 line), cost (in Indian Rupees ₹), duration (e.g. '2h'), category.\n\n"
            f"Generate at least 15 activities total, with more from these preferred categories: {pref_str}.\n\n"
            f"Return as a JSON object where keys are category names and values are arrays of activity objects.\n"
            f'Example: {{"sightseeing": [{{"name": "Burj Khalifa", "description": "World\'s tallest building", '
            f'"cost": 1500, "duration": "2h", "category": "sightseeing"}}]}}'
        )

        dest_data = await cohere_service.generate_json(
            prompt=prompt,
            fallback=FALLBACK_ACTIVITIES,
            max_tokens=2048,
            temperature=0.7,
        )

        # Validate we got a dict of categories
        if not isinstance(dest_data, dict) or len(dest_data) == 0:
            self.logger.warning(
                message.correlation_id,
                "LLM returned invalid activities data, using fallback",
            )
            dest_data = FALLBACK_ACTIVITIES

        # Build activity pool prioritized by preferences
        all_activities = []
        for category, activities in dest_data.items():
            if not isinstance(activities, list):
                continue
            for act in activities:
                if not isinstance(act, dict) or "name" not in act:
                    continue
                act.setdefault("description", "")
                act.setdefault("cost", 0)
                act.setdefault("duration", "2h")
                act.setdefault("category", category)
                act["cost"] = float(act.get("cost", 0))
                priority = 2 if category.lower() in [p.lower() for p in preferences] else 1
                all_activities.append({**act, "_priority": priority, "_category": category})

        if not all_activities:
            for category, activities in FALLBACK_ACTIVITIES.items():
                for act in activities:
                    all_activities.append({**act, "_priority": 1, "_category": category})

        # Sort: preferred categories first, then by cost (lower first)
        all_activities.sort(key=lambda x: (-x["_priority"], x["cost"]))

        # Use Cohere to generate enhanced itinerary suggestions
        llm_suggestions = ""
        if cohere_service.is_available:
            activity_list = "\n".join(
                f"- {a['name']}: {a['description']} (₹{a['cost']})" for a in all_activities[:15]
            )
            weather_info = ""
            if context.get("condition"):
                weather_info = f"\nWeather: {context.get('condition', 'N/A')}, High: {context.get('temp_high', 'N/A')}°C"
            elif context.get("weather"):
                w = context["weather"] if isinstance(context["weather"], dict) else context
                weather_info = f"\nWeather: {w.get('condition', 'N/A')}, High: {w.get('temp_high', 'N/A')}°C"

            suggest_prompt = (
                f"Create an optimized {duration}-day itinerary for {destination}.{weather_info}\n"
                f"Traveler preferences: {pref_str}\n"
                f"Available activities:\n{activity_list}\n\n"
                f"Suggest 3-4 activities per day, considering logical grouping by location and time of day. "
                f"Reply as a brief bullet list, day by day."
            )
            llm_suggestions = await cohere_service.generate(suggest_prompt, max_tokens=600)
            self.logger.decision(
                message.correlation_id,
                "Enhanced itinerary with Cohere LLM suggestions",
            )

        # Build day-wise plan
        activity_pool = list(all_activities)
        used_activities = set()
        itinerary = []
        activities_budget = budget * 0.15
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
