"""Version and license (open to anybody), and whether a newer nexpaper is out (block X2).

The update state is shown to every account; switching the daily check and asking now belong to the operator, because
the question goes out for the whole installation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .. import __version__
from ..db import SessionLocal
from ..deps import Account, OperatorAccount
from ..services import settings_service, updates

router = APIRouter(prefix="/api/v1/about", tags=["about"])

REPO_URL = updates.REPO_URL


class UpdatesOut(BaseModel):
    update_check: bool
    checked: bool = False
    latest: str | None = None
    newer: bool = False
    checked_at: datetime | None = None
    #: The release page of the newest version, when there is one.
    release_url: str | None = None


class UpdateSwitchIn(BaseModel):
    update_check: bool


def _on() -> bool:
    with SessionLocal() as db:
        return bool(settings_service.get(db, "update_check"))


def _out(on: bool, known: updates.State) -> UpdatesOut:
    return UpdatesOut(
        update_check=on,
        checked=known.checked_at is not None,
        latest=known.latest,
        newer=known.newer,
        checked_at=known.checked_at,
        release_url=f"{updates.RELEASES_URL}/tag/{known.latest}" if known.latest else None,
    )


@router.get("", summary="About nexpaper")
def about() -> dict[str, Any]:
    return {
        "version": __version__,
        "license": "AGPL-3.0",
        "repo_url": REPO_URL,
        "releases_url": updates.RELEASES_URL,
        "project_url": updates.PROJECT_URL,
    }


@router.get("/updates", response_model=UpdatesOut, summary="Whether a newer nexpaper is out (asked once a day)")
def update_state(_account: Account) -> UpdatesOut:
    on = _on()
    return _out(on, updates.state(on=on))


@router.post("/updates/check", response_model=UpdatesOut, summary="Ask now, also with the daily check off")
def check_now(_operator: OperatorAccount) -> UpdatesOut:
    """Off means "not by itself"; whoever clicks here has just decided."""
    return _out(_on(), updates.state(on=True, force=True))


@router.put("/updates", response_model=UpdatesOut, summary="Switch the daily check")
def switch(body: UpdateSwitchIn, _operator: OperatorAccount) -> UpdatesOut:
    with SessionLocal() as db:
        settings_service.save(db, {"update_check": body.update_check})
    if not body.update_check:
        updates.forget()
    return _out(body.update_check, updates.state(on=body.update_check))
