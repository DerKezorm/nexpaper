from __future__ import annotations

from fastapi import APIRouter

from .. import __version__

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("", summary="Is nexpaper running?")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
