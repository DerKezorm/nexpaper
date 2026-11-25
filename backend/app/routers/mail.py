"""The page Server › Mail: the routes of the shared post module (``nexpost.api``), operator only (from the browser,
from the operators' networks: ``require_operator``), under ``/api/v1/server/mail``: the mail server as the page shows
it (never the password; the last mail sent, the last error, the mails waiting), saving it, the test mail with
nexpaper's logo in the page's language.

The routes of before stay as they were: ``/api/v1/settings`` (``smtp_*``) and ``/api/v1/settings/mail-test``; both
read and write the same settings through the same store (``services/post_store.py``)."""

from __future__ import annotations

from ..deps import DbSession, require_operator
from ..errors import error
from ..services import post_store
from ..vendor.nexpost import api


def _store(db: DbSession) -> post_store.PostStore:
    return post_store.PostStore(db)


router = api.router(operator=require_operator, store=_store, prefix="/api/v1/server/mail", error=error, tags=["mail"])
