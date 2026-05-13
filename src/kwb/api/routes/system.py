"""
System-Check route: GET /api/system/check (issue #180).

Returns probe results for every optional capability so the dashboard
can show users which features are ready and what to install otherwise.
"""
from __future__ import annotations

try:
    from fastapi import APIRouter
except ImportError:
    raise ImportError("pip install fastapi uvicorn python-multipart")

from kwb.system_check import run_system_check

router = APIRouter()


@router.get("/api/system/check")
async def system_check():
    """Probe optional dependencies and return capability status."""
    return run_system_check()
