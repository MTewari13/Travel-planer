"""Async SQLAlchemy session factory."""

import os
import ssl as ssl_module
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/travel_planner"
)

# asyncpg doesn't understand ?ssl=require in the URL — strip it and pass as connect_args
connect_args = {}
if "ssl=require" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("?ssl=require", "").replace("&ssl=require", "")
    ssl_ctx = ssl_module.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl_module.CERT_NONE
    connect_args["ssl"] = ssl_ctx

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10, connect_args=connect_args)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncSession:
    """Yield an async database session."""
    async with async_session_factory() as session:
        yield session
