"""Main API v1 router aggregator."""

from fastapi import APIRouter

from backend.app.api.v1 import auth, historian, info, overview, simulation_ctrl

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router, prefix="", tags=["Authentication"])
api_v1_router.include_router(info.router, prefix="", tags=["System Info"])
api_v1_router.include_router(overview.router, prefix="", tags=["Plant Overview"])
api_v1_router.include_router(simulation_ctrl.router, prefix="", tags=["Simulation Control"])
api_v1_router.include_router(historian.router, prefix="", tags=["Historian"])
