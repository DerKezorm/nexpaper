"""Operator settings in the database, with defaults."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Setting

DEFAULTS: dict[str, Any] = {
    "log_mode": "normal",
    "log_mode_until": None,
    #: off | daily | weekly. Daily in the night unless the operator decides otherwise.
    "backup_schedule": "daily",
    "backup_keep": 7,
    #: The address people use to reach nexpaper: invitation links, the OIDC redirect. Empty means
    #: ``NEXPAPER_PUBLIC_URL``, and without that the request's own.
    "public_url": "",
    #: Members may sign in with a password. The operator always may: the emergency exit when OIDC fails.
    "password_login": True,
    #: Every account needs a second factor (a code from an app or a passkey), on from the start: right after the
    #: password, an account without one sets it up before it gets anywhere. Turning it off asks for the password.
    "two_factor_required": True,
    #: The operator declares that the OIDC provider checks a second factor itself: then an account that comes through
    #: the provider is not asked for nexpaper's. Off from the start.
    "oidc_second_factor_by_provider": False,
    #: OIDC: issuer, client id and the encrypted client secret; empty means not set up.
    "oidc_issuer": "",
    "oidc_client_id": "",
    "oidc_client_secret_enc": "",
    "oidc_provider_name": "",
    #: Whether an unknown identity from the provider gets an account. Off: only invited or linked accounts.
    "oidc_auto_create": False,
    #: Keys for programs such as a dashboard card (``/api/v1``): closed until the operator opens it.
    "api_keys_allowed": False,
    #: Ask GitHub once a day whether a newer nexpaper is out (services/updates). Only the question goes out, so on.
    "update_check": True,
    #: Invitation mail: without a host nothing is sent, the link to copy is enough.
    "smtp_host": "",
    "smtp_port": 587,
    #: starttls | tls | none
    "smtp_security": "starttls",
    "smtp_user": "",
    "smtp_password_enc": "",
    "smtp_from": "",
    #: The AI that proposes title, sender, kind, date and amount for a document (``services/ai.py``), one for
    #: everybody, set up by the operator only: none | local | openai | messages. None from the start: text leaves the
    #: server only when the operator wants it.
    "ai_provider": "none",
    "ai_url": "",
    "ai_model": "",
    #: Sealed with the server's secret (context ``operator:ai-key``); never shown again.
    "ai_key_enc": "",
    #: Documents in a personal vault never go to the AI (B6): there they get rules and what nexpaper reads itself only.
    "ai_skip_personal": True,
    #: The most documents sent to the AI in one day (UTC), on the whole server; 0 is no limit. A large delivery (a
    #: folder, a mailbox) would otherwise send every document to a service that is paid for by the request. ``ai_day``
    #: counts the day's requests (``services/ai_proposals.py``).
    "ai_daily_limit": 200,
    "ai_day": {},
    #: Web Push (``services/webpush.py``, ``services/push.py``): nexpaper's own key pair, made at the first need and
    #: sealed with the server's secret; who the push services may contact (empty: the public https address, else a
    #: placeholder); and push services beyond the known ones, as host names.
    "push_key_enc": "",
    "push_contact": "",
    "push_hosts": [],
    #: Links to documents for people without an account (``services/sharing.py``). The operator's switch: off ends every
    #: link at once. ``link_max_days`` is the longest one may last.
    "links_allowed": True,
    "link_max_days": 30,
    #: The kinds that come with nexpaper are put in the list once (``services/catalog.py``).
    "kinds_seeded": False,
    #: Receiving files (``services/limits.py``): the size of one file, the pages of one document, the pixels of one
    #: picture (in millions), how many pieces-by-piece uploads and how many bytes an account may have open at once,
    #: how long the worker may take for one document and how much memory it may use (0: no limit; only where the
    #: system allows it).
    "upload_max_mb": 200,
    "upload_max_pages": 2000,
    "upload_max_megapixels": 100,
    "upload_open_count": 10,
    "upload_open_mb": 4096,
    "process_timeout_seconds": 300,
    "process_memory_mb": 2048,
    #: The pictures of pages are kept in a cache that is trimmed to this size (MB), the ones used longest ago first.
    "cache_max_mb": 1024,
    #: Pages of a long document drawn in the background after it was read, behind every document that waits to be read
    #: (``services/pages.py``, job ``pages``); the ones after it are drawn when somebody asks for them.
    "prerender_max_pages": 500,
    #: The iCloud link of the iPhone shortcut "Nach nexpaper" the operator shared (``routers/phone.py``); empty: the
    #: account page explains how to build it.
    "shortcut_url": "",
    #: The intake folder (``services/intake_folder.py``): watched while on; empty path means ``<data_dir>/eingang``.
    "folder_on": False,
    "folder_path": "",
    #: The mailbox for documents (``services/intake_mail.py``), one per server, fetched every 5 minutes while on. Off is
    #: the operator's lock: no connection at all. The password is sealed with the server's secret (context
    #: ``operator:mail-intake``) and never shown again; it is forgotten when server or port change without a new one.
    #: ``mail_private``: the server may lie in the own network (off: only addresses on the internet).
    "mail_on": False,
    "mail_host": "",
    "mail_port": 993,
    #: tls | starttls | none (none only for a server on the same machine, 127.0.0.1)
    "mail_security": "tls",
    "mail_user": "",
    "mail_password_enc": "",
    #: The address of the mailbox, for ``name+<account>@`` and to tell people where to forward to.
    "mail_address": "",
    "mail_folder": "INBOX",
    #: read | move | delete: what happens to a mail once it was taken.
    "mail_after": "read",
    "mail_private": False,
    #: Mails that nobody can be told from are left in the mailbox instead of coming into the operator's inbox.
    "mail_drop_unknown": False,
    #: The server whose ``Authentication-Results`` count (``dmarc=fail``: unknown); empty: the mailbox's domain.
    "mail_auth_server": "",
    #: The bytes taken from the mailbox today, on the whole server and per person (``intake_mail.Budget``).
    "mail_budget": {},
    #: Where fetching stands (UIDVALIDITY and the last UID taken, per mailbox) and how the last run went.
    "mail_state": {},
    "mail_last": {},
    #: The text recognition (``services/ocr.py``): the languages it reads (of those in the image), whether it
    #: straightens and turns pages, whether blank pages count as separators (acted on by the page tools), and how many
    #: pages it works on at once.
    "ocr_languages": ["deu", "eng"],
    "ocr_straighten": True,
    "ocr_blank_pages": True,
    "ocr_jobs": 1,
    #: The longest the recognition of one document may take, in seconds.
    "ocr_max_seconds": 3600,
    #: The Paperless-ngx server documents are taken from (``services/paperless.py``): its address, the token sealed with
    #: the server's secret (context ``operator:paperless-token``, never shown again, forgotten when the address changes
    #: without a new one), and whether it may lie in the own network (off: only addresses on the internet).
    "paperless_url": "",
    "paperless_token_enc": "",
    "paperless_private": False,
    #: What the operator chose when the import was started (who is who, where it goes), kept for going on after a stop;
    #: and where the run stands (counts, state, the reasons things were skipped).
    "paperless_plan": {},
    "paperless_run": {},
    #: Checking the files (``services/filecheck.py``): whether a check runs, where it stands, what the last one found.
    "files_check": {},
}


def get(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key)
    return row.value


def get_all(db: Session) -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in db.scalars(select(Setting)):
        values[row.key] = row.value
    return values


def save(db: Session, changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()


def normalize_public_url(value: str) -> str:
    """``scheme://host[:port]`` and nothing else, or empty. ``ValueError`` for anything people could not type into
    a browser: no other schemes, no credentials, no path, no query."""
    text = value.strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("scheme or host")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("path, query or credentials")
    try:
        parts.port  # noqa: B018 - raises ValueError when the port is not a number
    except ValueError as exc:
        raise ValueError("port") from exc
    return f"{parts.scheme.lower()}://{parts.netloc}"


def public_url(db: Session) -> str:
    """The public address without a trailing slash: the setting, otherwise the environment, otherwise empty."""
    stored = str(get(db, "public_url") or "").strip().rstrip("/")
    return stored or get_settings().public_url.strip().rstrip("/")
