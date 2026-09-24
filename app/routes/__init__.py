"""HTTP routes. Each module defines a `router`; versioned routers are included in `api_router`."""

from fastapi import APIRouter

# Domain routers (venues, halls, ...) are added here as they are built.
api_router = APIRouter(prefix="/api/v1")
