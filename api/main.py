"""FastAPI main application — bootstraps the server, agents, and message bus."""

import os
import sys
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from shared.message_bus.redis_bus import RedisBus
from agents.planner.planner_agent import PlannerAgent
from agents.transport.transport_agent import TransportAgent
from agents.stay.stay_agent import StayAgent
from agents.itinerary.itinerary_agent import ItineraryAgent
from agents.budget.budget_agent import BudgetAgent
from agents.context.context_agent import ContextAgent
from agents.negotiation.negotiation_agent import NegotiationAgent
from api.routes import trips as trip_routes
from api.routes import auth as auth_routes

# ── Logging setup ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("api.main")

# ── Globals ──
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PORT = int(os.getenv("PORT", "3000"))

bus: RedisBus = None
agents: list = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start agents on startup, clean up on shutdown."""
    global bus, agents

    logger.info("🚀 Starting Agentic Travel Planner...")
    logger.info(f"📡 Connecting to Redis at {REDIS_URL}")

    # Initialize message bus
    bus = RedisBus(REDIS_URL)
    await bus.connect()

    # Create database schema
    from shared.database.models import Base
    from shared.database.session import engine
    
    # Initialize PostgreSQL tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("🗄️ Verified PostgreSQL database tables")

    # Initialize all agents
    planner = PlannerAgent(bus)
    transport = TransportAgent(bus)
    stay = StayAgent(bus)
    itinerary = ItineraryAgent(bus)
    budget = BudgetAgent(bus)
    context = ContextAgent(bus)
    negotiation = NegotiationAgent(bus)

    agents = [planner, transport, stay, itinerary, budget, context, negotiation]

    # Start all agents (subscribe to their channels)
    for agent in agents:
        await agent.start()

    # Start the message bus listener
    await bus.start_listening()

    # Inject dependencies into routes
    trip_routes.set_dependencies(bus, planner)

    logger.info("=" * 60)
    logger.info("✅ ALL AGENTS ONLINE")
    logger.info("=" * 60)
    for agent in agents:
        logger.info(f"   🤖 {agent.agent_type.value}")
    logger.info("=" * 60)
    logger.info(f"🌐 API ready at http://localhost:{PORT}")
    logger.info(f"📖 Docs at http://localhost:{PORT}/docs")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("🛑 Shutting down agents...")
    await bus.close()
    logger.info("👋 Goodbye!")


# ── Create FastAPI app ──
app = FastAPI(
    title="🌍 Agentic Travel Planner",
    description=(
        "Multi-agent travel planning system with A2A communication. "
        "Agents collaborate via Redis Pub/Sub to plan trips with "
        "transport, accommodation, itinerary, budget optimization, "
        "and contextual intelligence."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──
app.include_router(trip_routes.router)
app.include_router(auth_routes.router)


@app.get("/", tags=["health"])
async def root():
    return {
        "service": "Agentic Travel Planner",
        "version": "1.0.0",
        "status": "running",
        "agents": [a.agent_type.value for a in agents] if agents else [],
        "docs": "/docs",
    }


@app.get("/health", tags=["health"])
async def health():
    return {"status": "healthy", "agents_count": len(agents)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=PORT, reload=True)
