"""The page of a document in the web app, for the answers that name it (the dashboard card, the deadlines). One rule,
kept here so both say the same: the public address when the operator set one, else the address the request came to;
``/dokument/<id>`` for a filed document, ``/eingang/<id>`` for one waiting in the inbox."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from sqlalchemy.orm import Session

from ..services import settings_service


def document_pages(db: Session, request: Request) -> Callable[[int, str], str]:
    """A function from a document's id and status to its page. The address is looked up once, then used for all."""
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")

    def page(document_id: int, status: str) -> str:
        return f"{base}/dokument/{document_id}" if status == "filed" else f"{base}/eingang/{document_id}"

    return page
