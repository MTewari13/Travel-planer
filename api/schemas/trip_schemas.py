"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel, Field
from typing import Optional


class TripCreateRequest(BaseModel):
    """Request body for creating a new trip plan."""

    destination: str = Field(..., min_length=1, max_length=200, examples=["Goa"])
    budget: float = Field(..., gt=0, examples=[20000])
    duration: int = Field(..., ge=1, le=30, examples=[5])
    preferences: list[str] = Field(
        default_factory=list,
        examples=[["food", "nightlife", "beach"]],
    )
    origin: str = Field(default="Delhi", max_length=200)


class TripUpdateRequest(BaseModel):
    """Request body for updating/re-planning a trip."""

    destination: Optional[str] = None
    budget: Optional[float] = Field(default=None, gt=0)
    duration: Optional[int] = Field(default=None, ge=1, le=30)
    preferences: Optional[list[str]] = None


class TripStatusResponse(BaseModel):
    trip_id: str
    status: str
    message: str


class ErrorResponse(BaseModel):
    detail: str
