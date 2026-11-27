"""The routes of "What's new" (W10):

``GET  <prefix>?language=de``          the running version, what this account read, its unread entries and the entry
                                       for "About" (a signed-in account)
``GET  <prefix>/history?language=de``  every entry up to the running version, the newest first (W18)
``POST <prefix>/seen``                 the account read or put away the running version

The app mounts them with ``app.include_router(nexwasneu.api.router(viewer=…))``; ``viewer`` is the app's dependency
that gives a ``nexwasneu.Viewer`` for the signed-in account (401 without a session, as the app's other routes). The
page asks in its own language; without one the account's language counts, then English. Sections for operators reach
only operators (W8). An app's old route (``POST /api/me/whats-new/seen``) stays and calls ``nexwasneu.mark_seen``.

``operation_ids`` and ``summaries`` (by ``ROUTES``) keep an app's own names in its description. The only part of the
module that needs FastAPI. No postponed annotations here: FastAPI reads the types of the local route functions."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from . import texts
from .config import current
from .seen import Viewer, mark_seen

ROUTES = ("whats_new", "whats_new_history", "whats_new_seen_now")
SUMMARIES = {
    "whats_new": "What is new for this account since the version it read",
    "whats_new_history": "What every version up to the running one brought",
    "whats_new_seen_now": "What's new of the running version is read or put away",
}


class WhatsNewLink(BaseModel):
    label: str
    href: str


class WhatsNewSection(BaseModel):
    title: str
    where: str
    body: str
    link: WhatsNewLink | None = None
    operator: bool = False


class WhatsNewItem(BaseModel):
    version: str
    #: The language the text is in (the one asked for, its base language, or English, W4).
    language: str
    lead: str
    sections: list[WhatsNewSection]
    #: The name the files give it.
    smallTitle: str
    small: list[str]


class WhatsNewOut(BaseModel):
    version: str
    seen: str
    #: The entries after the version this account read, the newest first, at most five (W6).
    unread: list[WhatsNewItem]
    #: More unread entries than shown; the rest under "Earlier versions".
    more: bool
    #: The newest entry up to the running version, for "About" (W7).
    current: WhatsNewItem | None
    #: Whether there are entries before ``current`` (W18).
    earlier: bool


class WhatsNewHistoryOut(BaseModel):
    version: str
    entries: list[WhatsNewItem]


class WhatsNewSeenOut(BaseModel):
    seen: str


def _checked(given: dict[str, str] | None) -> dict[str, str]:
    given = dict(given or {})
    unknown = sorted(set(given) - set(ROUTES))
    if unknown:
        raise ValueError(f"unknown route: {', '.join(unknown)} (known: {', '.join(ROUTES)})")
    return given


def _language(asked: str | None, viewer: Viewer) -> str | None:
    return asked or viewer.language


def router(
    *,
    viewer: Callable[..., Viewer],
    prefix: str = "/api/whats-new",
    tags: list[str] | None = None,
    operation_ids: dict[str, str] | None = None,
    summaries: dict[str, str] | None = None,
) -> APIRouter:
    """The routes under ``prefix`` (nexpaper ``/api/v1/whats-new``). ``viewer``: the app's dependency for the signed-in
    account, as a ``Viewer``."""
    ids = _checked(operation_ids)
    said = SUMMARIES | _checked(summaries)
    Signed = Annotated[Viewer, Depends(viewer)]
    Language = Annotated[str | None, Query(max_length=35)]
    routes = APIRouter(prefix=prefix, tags=tags or ["whats-new"])

    @routes.get("", response_model=WhatsNewOut, summary=said["whats_new"], operation_id=ids.get("whats_new"))
    def whats_new(signed: Signed, language: Language = None) -> dict[str, Any]:
        found = texts.state(signed.seen, _language(language, signed), signed.operator, current())
        return {
            "version": found.version,
            "seen": found.seen,
            "unread": found.unread,
            "more": found.more,
            "current": found.current,
            "earlier": found.earlier,
        }

    @routes.get(
        "/history",
        response_model=WhatsNewHistoryOut,
        summary=said["whats_new_history"],
        operation_id=ids.get("whats_new_history"),
    )
    def whats_new_history(signed: Signed, language: Language = None) -> dict[str, Any]:
        config = current()
        return {
            "version": config.running(),
            "entries": texts.collected(_language(language, signed), signed.operator, config),
        }

    @routes.post(
        "/seen",
        response_model=WhatsNewSeenOut,
        summary=said["whats_new_seen_now"],
        operation_id=ids.get("whats_new_seen_now"),
    )
    def whats_new_seen_now(signed: Signed) -> dict[str, str]:
        return {"seen": mark_seen(signed)}

    return routes
