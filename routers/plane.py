"""
Plane webhook router handling webhooks from plane.so.

This router processes webhooks from plane.so.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
import os
import asyncio
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from dependencies.ch_db import get_ch_session
from models.commits import SyncStatus
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/plane")


@router.post("/webhook")
async def webhook_plane(request: Request, session: Session = Depends(get_ch_session)):
    """
    Handle Plane webhook events.
    """
    request_data = await request.json()
    print(f"[REQUEST DATA] : {request_data}")
    event_type = "Event type"
    return {
        "message": f"Event type '{event_type}' not processed",
        "event_type": event_type,
    }


async def handle_event_1(request_data: dict, session: Session):
    ...


async def handle_event_2(request_data: dict, session: Session):
    ...
