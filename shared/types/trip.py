"""Trip domain types — requests, responses, and sub-models."""

from pydantic import BaseModel, Field
from typing import Optional


class TripRequest(BaseModel):
    """User input for a trip planning request."""

    destination: str
    budget: float
    duration: int  # days
    preferences: list[str] = Field(default_factory=list)
    origin: str = "Delhi"


class TransportOption(BaseModel):
    mode: str  # flight, train, bus
    provider: str
    departure: str
    arrival: str
    duration_hours: float
    price: float
    rating: Optional[float] = None


class StayOption(BaseModel):
    name: str
    type: str  # hotel, hostel, resort
    price_per_night: float
    total_price: float
    rating: float
    distance_to_center_km: float
    amenities: list[str] = Field(default_factory=list)


class Activity(BaseModel):
    time: str  # e.g. "09:00 - 11:00"
    name: str
    description: str
    cost: float = 0.0
    category: str = "sightseeing"


class DayPlan(BaseModel):
    day: int
    date: Optional[str] = None
    activities: list[Activity] = Field(default_factory=list)
    meals: list[Activity] = Field(default_factory=list)
    day_cost: float = 0.0


class CostBreakdown(BaseModel):
    transport: float = 0.0
    accommodation: float = 0.0
    activities: float = 0.0
    food: float = 0.0
    miscellaneous: float = 0.0
    total: float = 0.0
    budget: float = 0.0
    within_budget: bool = True
    savings: float = 0.0


class ContextInfo(BaseModel):
    weather: dict = Field(default_factory=dict)
    events: list[dict] = Field(default_factory=list)
    crowd_level: str = "moderate"
    best_time_to_visit: str = ""
    tips: list[str] = Field(default_factory=list)


class NegotiationResult(BaseModel):
    original_cost: float
    optimized_cost: float
    changes: list[str] = Field(default_factory=list)
    new_transport: Optional[TransportOption] = None
    new_stay: Optional[StayOption] = None


class TripResponse(BaseModel):
    """Final aggregated trip plan returned to the user."""

    trip_id: str
    destination: str
    duration: int
    transport: list[TransportOption] = Field(default_factory=list)
    selected_transport: Optional[TransportOption] = None
    stays: list[StayOption] = Field(default_factory=list)
    selected_stay: Optional[StayOption] = None
    itinerary: list[DayPlan] = Field(default_factory=list)
    cost_breakdown: Optional[CostBreakdown] = None
    context: Optional[ContextInfo] = None
    agent_logs: list[str] = Field(default_factory=list)
    negotiation_applied: bool = False
    status: str = "completed"
