"""Main API v1 router aggregator."""

from backend.app.api.v1 import info
from fastapi import APIRouter

api_v1_router = APIRouter()
api_v1_router.include_router(info.router, prefix="", tags=["System Info"])
