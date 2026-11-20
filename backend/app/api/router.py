"""Main API v1 router aggregator."""

from fastapi import APIRouter
from backend.app.api.v1 import info

api_v1_router = APIRouter()
api_v1_router.include_router(info.router, prefix="", tags=["System Info"])
