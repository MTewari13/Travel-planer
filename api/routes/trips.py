"""Trip API routes — handles trip creation, retrieval, and re-planning."""

import uuid
import time
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api.schemas.trip_schemas import TripCreateRequest, TripUpdateRequest, TripStatusResponse
from shared.types.message import AgentMessage, AgentType
from shared.database.session import get_session
from shared.database.models import Trip
from api.auth_utils import get_current_user_id

logger = logging.getLogger("api.trips")

router = APIRouter(prefix="/api/trips", tags=["trips"])

# In-memory store for tracking live trips currently in the "planning" phase
_live_trips: dict[str, dict[str, Any]] = {}


def set_dependencies(bus, planner):
    """Inject dependencies from main app."""
    global _bus, _planner
    _bus = bus
    _planner = planner


@router.post("", status_code=201)
async def create_trip(
    request: TripCreateRequest, 
    user_id: Optional[str] = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_session)
):
    """Create a new trip and trigger the planning pipeline."""
    trip_id = str(uuid.uuid4())

    logger.info(f"📋 New trip request: {request.destination}, ₹{request.budget}, {request.duration} days")

    # Store trip status in memory while generating
    _live_trips[trip_id] = {
        "id": trip_id,
        "request": request.model_dump(),
        "status": "planning",
        "result": None,
        "created_at": time.time(),
        "logs": [],
    }

    # Send to planner agent via A2A message bus
    message = AgentMessage(
        from_agent=AgentType.GATEWAY,
        to_agent=AgentType.PLANNER,
        task="plan_trip",
        payload={
            "destination": request.destination,
            "budget": request.budget,
            "duration": request.duration,
            "preferences": request.preferences,
            "origin": request.origin,
        },
        correlation_id=trip_id,
    )

    start_time = time.time()
    response = await _bus.request_response(
        AgentType.PLANNER.value, message, timeout=120.0
    )
    elapsed_ms = (time.time() - start_time) * 1000

    if response:
        # Collect logs
        logs = _planner.logger.get_logs()
        
        # Save to PostgreSQL
        db_trip = Trip(
            id=trip_id,
            user_id=user_id,
            destination=request.destination,
            origin=request.origin,
            budget=request.budget,
            duration=request.duration,
            preferences=request.preferences,
            status="completed",
            result=response.payload
        )
        db.add(db_trip)
        await db.commit()

        # Clean up live memory
        _live_trips.pop(trip_id, None)

        logger.info(f"✅ Trip {trip_id[:8]} completed & saved in {elapsed_ms:.0f}ms")

        return {
            "trip_id": trip_id,
            "status": "completed",
            "elapsed_ms": round(elapsed_ms),
            "result": response.payload,
            "logs": logs
        }
    else:
        _live_trips[trip_id]["status"] = "failed"
        logger.error(f"❌ Trip {trip_id[:8]} timed out after {elapsed_ms:.0f}ms")
        raise HTTPException(status_code=504, detail="Trip planning timed out")


@router.get("/{trip_id}")
async def get_trip(
    trip_id: str, 
    user_id: Optional[str] = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_session)
):
    """Get a trip. Checks live memory first, then database."""
    # Check if currently generating
    if trip_id in _live_trips:
        return _live_trips[trip_id]
        
    # Check Database
    result = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalars().first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
        
    # Optional checking: if a logged in user tries to read someone else's trip
    if trip.user_id and user_id and trip.user_id != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    return {
        "id": trip.id,
        "request": {
            "destination": trip.destination,
            "origin": trip.origin,
            "budget": trip.budget,
            "duration": trip.duration,
            "preferences": trip.preferences,
        },
        "status": trip.status,
        "result": trip.result,
        "created_at": trip.created_at.timestamp(),
        "logs": []  # DB doesn't store logs to save space
    }


@router.put("/{trip_id}")
async def update_trip(
    trip_id: str, 
    request: TripUpdateRequest,
    user_id: Optional[str] = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_session)
):
    """Update a trip and trigger re-planning."""
    result = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalars().first()
    
    if not trip:
        # Fallback to check live trips in memory
        if trip_id in _live_trips:
            live_trip = _live_trips[trip_id]
            original = live_trip["request"]
        else:
            raise HTTPException(status_code=404, detail="Trip not found")
    else:
        if trip.user_id and user_id and trip.user_id != user_id:
            raise HTTPException(status_code=403, detail="Unauthorized")
        
        original = {
            "destination": trip.destination,
            "origin": trip.origin,
            "budget": trip.budget,
            "duration": trip.duration,
            "preferences": trip.preferences,
        }

    updated = {
        "destination": request.destination or original["destination"],
        "budget": request.budget or original["budget"],
        "duration": request.duration or original["duration"],
        "preferences": request.preferences if request.preferences is not None else original["preferences"],
        "origin": original.get("origin", "Delhi"),
    }

    _live_trips[trip_id] = {
        "id": trip_id,
        "request": updated,
        "status": "re-planning",
        "result": None,
        "created_at": time.time(),
        "logs": [],
    }

    logger.info(f"🔄 Re-planning trip {trip_id[:8]} with updated params")

    message = AgentMessage(
        from_agent=AgentType.GATEWAY,
        to_agent=AgentType.PLANNER,
        task="replan_trip",
        payload=updated,
        correlation_id=trip_id,
    )

    start_time = time.time()
    response = await _bus.request_response(
        AgentType.PLANNER.value, message, timeout=120.0
    )
    elapsed_ms = (time.time() - start_time) * 1000

    if response:
        # Update original DB record
        if trip:
            trip.destination = updated["destination"]
            trip.budget = updated["budget"]
            trip.duration = updated["duration"]
            trip.preferences = updated["preferences"]
            trip.result = response.payload
            await db.commit()
            
        _live_trips.pop(trip_id, None)

        return {
            "trip_id": trip_id,
            "status": "re-planned",
            "elapsed_ms": round(elapsed_ms),
            "result": response.payload,
            "logs": _planner.logger.get_logs()
        }
    else:
        _live_trips[trip_id]["status"] = "failed"
        raise HTTPException(status_code=504, detail="Re-planning timed out")


@router.get("/{trip_id}/logs")
async def get_trip_logs(trip_id: str):
    """Get agent decision logs for an active trip."""
    if trip_id in _live_trips:
        return {"trip_id": trip_id, "logs": _live_trips[trip_id].get("logs", [])}
    return {"trip_id": trip_id, "logs": []}


@router.get("")
async def list_trips(
    user_id: Optional[str] = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_session)
):
    """List all trips for the authenticated user from Database."""
    if not user_id:
        # If no user_id (not logged in and no guest token), return empty
        return []

    # Get trips belonging to this user_id, ordered by newest first
    result = await db.execute(
        select(Trip)
        .where(Trip.user_id == user_id)
        .order_by(Trip.created_at.desc())
        .limit(20)
    )
    trips = result.scalars().all()

    return [
        {
            "id": t.id,
            "destination": t.destination,
            "budget": t.budget,
            "duration": t.duration,
            "status": t.status,
            "created_at": t.created_at.timestamp()
        }
        for t in trips
    ]
