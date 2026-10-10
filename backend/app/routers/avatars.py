"""Profile pictures (``services/avatars``): each account sets and removes its own; a picture is served only to those who
may see it, and to anyone else exactly like a picture that is not there."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from ..deps import Account, DbSession
from ..errors import error
from ..models import Account as AccountRow
from ..models import utcnow
from ..services import avatars, pictures
from .auth import account_view

logger = logging.getLogger("nexpaper.accounts")
router = APIRouter(prefix="/api/v1", tags=["accounts"])


@router.put("/auth/avatar", summary="Set the own profile picture (the picture itself as the body)")
async def set_avatar(request: Request, account: Account, db: DbSession) -> dict[str, Any]:
    try:
        # A place first, then the body (``pictures.admitted``); unpacked away from the event loop.
        with pictures.admitted():
            data = await pictures.read_body(request)
            picture = await run_in_threadpool(avatars.make, data)
    except pictures.PictureError as exc:
        raise error("avatar_too_large", "avatar too large", 422, max_mb=avatars.MAX_BYTES // (1024 * 1024)) from exc
    except avatars.AvatarError as exc:
        raise error(exc.code, exc.code.replace("_", " "), 422, max_mb=avatars.MAX_BYTES // (1024 * 1024)) from exc
    row = db.get(AccountRow, account.id)
    assert row is not None
    row.avatar = picture
    row.avatar_at = utcnow()
    db.commit()
    logger.info("Profile picture set name=%s", row.name)
    return account_view(row)


@router.delete("/auth/avatar", summary="Remove the own profile picture")
def remove_avatar(account: Account, db: DbSession) -> dict[str, Any]:
    row = db.get(AccountRow, account.id)
    assert row is not None
    row.avatar = None
    row.avatar_at = None
    db.commit()
    return account_view(row)


@router.get("/avatars/{account_id}", summary="A profile picture, for those who may see it")
def get_avatar(account_id: int, account: Account, db: DbSession) -> Response:
    row = db.get(AccountRow, account_id) if avatars.may_see(db, account, account_id) else None
    picture = row.avatar if row is not None else None
    if not picture:
        raise error("not_found", "Not found.", 404)
    # The address carries the time it was set (?v=), so a new picture is a new address: kept long, but only here.
    return Response(picture, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})
