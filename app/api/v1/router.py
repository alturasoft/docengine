"""DocEngine — FastAPI v1 Router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import extraction, health

router = APIRouter()
router.include_router(health.router)
router.include_router(extraction.router)
