"""SQLAlchemy models for the travel planner database."""

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON, Boolean
)
from sqlalchemy.orm import declarative_base, relationship, foreign
import uuid

Base = declarative_base()


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    google_id = Column(String(255), unique=True, nullable=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=True)
    avatar_url = Column(String(500), nullable=True)
    preferences = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    trips = relationship("Trip", primaryjoin="User.id == foreign(Trip.user_id)", back_populates="user")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, index=True, nullable=True)  # No FK constraint to allow "guest:" IDs
    destination = Column(String(200), nullable=False)
    origin = Column(String(200), default="Delhi")
    budget = Column(Float, nullable=False)
    duration = Column(Integer, nullable=False)
    preferences = Column(JSON, default=list)
    status = Column(String(50), default="planning")  # planning, completed, failed
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", primaryjoin="User.id == foreign(Trip.user_id)", back_populates="trips")
    itinerary = relationship("ItineraryRecord", back_populates="trip")
    agent_logs = relationship("AgentLog", back_populates="trip")


class ItineraryRecord(Base):
    __tablename__ = "itineraries"

    id = Column(String, primary_key=True, default=gen_uuid)
    trip_id = Column(String, ForeignKey("trips.id"), nullable=False)
    day = Column(Integer, nullable=False)
    activities = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    trip = relationship("Trip", back_populates="itinerary")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    trip_id = Column(String, ForeignKey("trips.id"), nullable=False)
    agent_name = Column(String(100), nullable=False)
    action = Column(String(200), nullable=False)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    duration_ms = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    trip = relationship("Trip", back_populates="agent_logs")
