"""Authentication routes."""

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests

from shared.database.session import get_session
from shared.database.models import User
from api.auth_utils import create_jwt, get_current_user_id
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

logger = logging.getLogger("api.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")


class GoogleLoginRequest(BaseModel):
    credential: str  # The ID token from Google


@router.post("/google")
async def google_login(request: GoogleLoginRequest, db: AsyncSession = Depends(get_session)):
    """Verify Google token, create/update user in DB, and return a JWT."""
    if not GOOGLE_CLIENT_ID:
        logger.error("GOOGLE_CLIENT_ID is not set in environment!")
        raise HTTPException(status_code=500, detail="OAuth not configured on server")

    try:
        # Verify the token with Google (allow 30 seconds of clock skew)
        id_info = id_token.verify_oauth2_token(
            request.credential, 
            requests.Request(), 
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=30
        )
        
        google_id = id_info['sub']
        email = id_info.get('email')
        name = id_info.get('name', 'User')
        picture = id_info.get('picture')

        # Check if user exists in our DB
        result = await db.execute(select(User).where(User.google_id == google_id))
        user = result.scalars().first()

        if user:
            # Update info if changed
            if user.name != name or user.avatar_url != picture:
                user.name = name
                user.avatar_url = picture
                await db.commit()
        else:
            # Check if user exists by email (if they previously logged in differently)
            if email:
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalars().first()

            if user:
                # Link google account
                user.google_id = google_id
                user.avatar_url = picture
                await db.commit()
            else:
                # Create brand new user
                user = User(
                    google_id=google_id,
                    name=name,
                    email=email,
                    avatar_url=picture
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)

        # Generate our own JWT
        token = create_jwt(user_id=user.id, email=user.email, name=user.name)

        logger.info(f"✅ User {user.name} logged in via Google")

        return {
            "token": token,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "avatar_url": user.avatar_url
            }
        }

    except ValueError as e:
        logger.error(f"Google token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google token")


@router.post("/guest")
async def guest_login():
    """Generate a temporary session for a guest user."""
    import uuid
    guest_id = f"guest:{uuid.uuid4()}"
    token = create_jwt(user_id=guest_id, name="Guest Explorer")
    
    logger.info("👋 New guest session created")
    
    return {
        "token": token,
        "user": {
            "id": guest_id,
            "name": "Guest Explorer",
            "email": None,
            "avatar_url": None,
            "is_guest": True
        }
    }


@router.get("/me")
async def get_me(user_id: Optional[str] = Depends(get_current_user_id), db: AsyncSession = Depends(get_session)):
    """Get current logged in user details."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Handle Guest users
    if user_id.startswith("guest:"):
        return {
            "id": user_id,
            "name": "Guest Explorer",
            "email": None,
            "avatar_url": None,
            "is_guest": True
        }

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "is_guest": False
    }
