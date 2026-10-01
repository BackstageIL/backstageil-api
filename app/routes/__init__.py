"""HTTP routes. Each module defines a `router`; versioned routers are included in `api_router`."""

from fastapi import APIRouter

from app.routes.admin import router as admin_router
from app.routes.cities import router as cities_router
from app.routes.venues import router as venues_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(venues_router)
api_router.include_router(cities_router)
api_router.include_router(admin_router)
