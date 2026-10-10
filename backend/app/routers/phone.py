"""The phone: what the quick upload shows, the iPhone shortcut, and the place the share menu of Android sends files to.

**The quick upload** (``GET /api/v1/quick``) is the start of the phone, and of any app that wants the same: where a
file goes (the person's choice, or their own vault), the vaults they may add to, their latest documents that are still
being read or wait in the inbox (or came today), and how many wait in the inbox. Everything is counted over what the
person may see, as everywhere.

**The share menu** of Android sends the files of another app as a form (``POST /teilen``, the ``share_target`` of the
manifest). Such a form carries the cookie and no header of nexpaper's own, so the server never takes files from it:
a page on another site could send one just the same. The service worker (``frontend/public/sw.js``) catches the form
before it leaves the phone, keeps the files in the browser and opens ``/teilen``, which uploads them through
``/api/v1`` like every other upload (with the tab header). Without the worker (not yet installed) the form reaches
``POST /teilen`` (served with the built frontend, ``main._mount_frontend``), which reads nothing and sends the page
to ``/teilen?missed=1``: it says to choose the file once more.

**The shortcut** for the iPhone: Safari puts no web app into the share menu of other apps; a shortcut in the app
Shortcuts does. Its file cannot be made here (iOS takes only shortcuts signed by Apple, which needs a Mac or a device
with the operator's Apple account), so the operator may share one by an iCloud link, kept here; the account page
explains how to build it in a few steps either way.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from .. import clock
from ..deps import Account, DbSession, OperatorAccount, Reader
from ..errors import error
from ..models import FILED, INBOX, PROCESSING, Document
from ..services import documents, inbox, receiving, rights, settings_service, vaults
from .schemas import DocumentOut, document_out

logger = logging.getLogger("nexpaper.api")

router = APIRouter(tags=["phone"])

#: How many of the latest own documents the quick upload shows.
RECENT = 5
#: A document that was filed already still counts as "latest" this long after it came.
RECENT_FILED = timedelta(hours=24)


class QuickVault(BaseModel):
    id: int
    name: str
    icon: str
    #: The person's own vault.
    mine: bool


class QuickOut(BaseModel):
    #: Where a file goes when the caller names no vault: their choice if they may still add there, else their own.
    target_vault_id: int
    #: The vaults the caller may add to (``edit`` or ``manage``), their own first.
    vaults: list[QuickVault]
    #: The caller's latest documents: still being read, waiting in the inbox, or filed in the last 24 hours.
    recent: list[DocumentOut]
    #: Documents the caller may see that wait in the inbox, and those still being read.
    inbox: int
    processing: int


@router.get("/api/v1/quick", response_model=QuickOut, summary="What the quick upload of a phone shows")
def quick(account: Reader, db: DbSession) -> QuickOut:
    target = receiving.resolve_vault(db, account.id, None)
    writable = [view for view in vaults.listing(db, account.id) if rights.at_least(view.right, rights.EDIT)]
    since = clock.now() - RECENT_FILED
    mine = list(db.scalars(
        select(Document).where(
            rights.visible_clause(account.id), Document.owner_id == account.id,
            or_(Document.status.in_((PROCESSING, INBOX)), (Document.status == FILED) & (Document.added_at >= since)),
        ).order_by(Document.added_at.desc(), Document.id.desc()).limit(RECENT)))
    counts = dict(db.execute(
        select(Document.status, func.count()).where(inbox.waiting(account.id))
        .group_by(Document.status)).all())
    return QuickOut(
        target_vault_id=target,
        vaults=[QuickVault(id=view.vault.id, name=view.name, icon=view.vault.icon,
                           mine=view.vault.personal_of == account.id) for view in writable],
        recent=[document_out(row) for row in documents.rows(db, account.id, mine)],
        inbox=int(counts.get(INBOX, 0)),
        processing=int(counts.get(PROCESSING, 0)),
    )


# --- The iPhone shortcut ----------------------------------------------------------------------------------------------

#: An iCloud link to a shortcut, and nothing else: the account page shows it to everybody as "Load the shortcut".
SHORTCUT_LINK = re.compile(r"^https://www\.icloud\.com/shortcuts/[0-9a-f]{32}/?$")


class ShortcutOut(BaseModel):
    #: The iCloud link the operator shared; empty when there is none.
    link: str
    #: Where the shortcut sends files: the public address of nexpaper, and the route for uploads.
    address: str
    upload_url: str


def _base(request: Request, db: DbSession) -> str:
    return settings_service.public_url(db) or str(request.base_url).rstrip("/")


@router.get("/api/v1/shortcut", response_model=ShortcutOut, summary="The iPhone shortcut: its link and where it sends")
def shortcut(request: Request, _account: Account, db: DbSession) -> ShortcutOut:
    base = _base(request, db)
    return ShortcutOut(link=str(settings_service.get(db, "shortcut_url") or ""), address=base,
                       upload_url=base + "/api/v1/documents?source=share")


class ShortcutLinkIn(BaseModel):
    #: ``https://www.icloud.com/shortcuts/<32 hexadecimal digits>``, or empty to take it away.
    link: str = Field(max_length=120)


class ShortcutLinkOut(BaseModel):
    link: str


@router.get("/api/v1/settings/shortcut", response_model=ShortcutLinkOut,
            summary="The iCloud link of the iPhone shortcut (operator)")
def shortcut_link(_operator: OperatorAccount, db: DbSession) -> ShortcutLinkOut:
    return ShortcutLinkOut(link=str(settings_service.get(db, "shortcut_url") or ""))


@router.put("/api/v1/settings/shortcut", response_model=ShortcutLinkOut,
            summary="Set or take away the iCloud link of the iPhone shortcut (operator)")
def set_shortcut_link(payload: ShortcutLinkIn, _operator: OperatorAccount, db: DbSession) -> ShortcutLinkOut:
    link = payload.link.strip()
    if link and not SHORTCUT_LINK.match(link):
        raise error("shortcut_link_invalid", "Use the iCloud link of the shortcut (https://www.icloud.com/shortcuts/...).",
                    422)
    settings_service.save(db, {"shortcut_url": link})
    logger.info("Shortcut link %s", "set" if link else "removed")
    return ShortcutLinkOut(link=link)

