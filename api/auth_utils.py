"""Authentication utilities: JWT encoding/decoding and FastAPI dependencies."""

import os
import time
import jwt
import logging
from typing import Optional
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("api.auth_utils")

# Secret key for JWT signing (use env var in production)
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-travel-planner-key-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 1 week

security = HTTPBearer(auto_error=False)


def create_jwt(user_id: str, email: Optional[str] = None, name: str = "User") -> str:
    """Create a new JWT for a user."""
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "exp": time.time() + (JWT_EXPIRATION_HOURS * 3600),
        "iat": time.time(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> Optional[dict]:
    """Verify and decode a JWT. Returns the payload or None if invalid."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT invalid: {e}")
        return None


async def get_current_user_id(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> Optional[str]:
    """FastAPI dependency to get the current user ID from the Authorization header.
    Returns None for guest users (no token)."""
    if not credentials:
        return None

    token = credentials.credentials
    payload = verify_jwt(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload.get("sub")
