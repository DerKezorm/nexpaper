"""Taking documents over from Paperless-ngx, through its REST API (Settings, Import; the operator, from a browser).

**What comes over.** Every document with its file as it came (the original) and the searchable copy Paperless made
(the archive version), the text Paperless recognised (no new recognition: the reading of a document takes it instead of
running Tesseract, ``given_text``), the title, the date, the correspondent (the sender), the document type (the kind;
a type nexpaper does not know becomes a new kind), the tags (an inbox tag puts the document in the inbox instead of
filing it), the notes, the custom fields (one note with all values) and the people it was shared with (the same people
here, as far as they can be told). Storage paths and workflows have no place here and are left out.

**Who and where.** The owner in Paperless becomes the person the operator chose for that owner (proposed: the person of
the same name, else the operator). Everything goes either into one vault, or each document into the own vault of its
person.

**A job in the background.** The run is a job (``services/jobs.py``) of its own loop: one document at a time, the
progress kept in the settings (``paperless_run``), stoppable by the operator (``stop``) and by the end of the server
(it goes on at the next start). Every document taken is written down with its Paperless number in the same transaction
as the document it becomes (``PaperlessItem``): a second run never takes it twice, it takes only what is new or was
skipped. What is skipped is said in the log with its reason, never with a word of its content.

**Paperless is a stranger.** The address goes through ``outbound.py`` (resolved once, checked, no redirect, a deadline
for every request, the answer read up to a size); an address in the own network only with the operator's switch
(``paperless_private``). The token is sealed with the server's secret and never shown again. Every answer is checked for
its types and cut to the lengths nexpaper keeps; the numbers of the next page are counted here, a ``next`` address in an
answer is never followed. Files go straight to the disk piece by piece, are limited by the operator's size limit and
must be one of the kinds an upload may be (``services/filetypes.py``)."""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..errors import error
from ..models import (
    FILED,
    INBOX,
    OPERATOR,
    READ,
    Account,
    Document,
    DocumentTag,
    Kind,
    Note,
    PaperlessItem,
    Share,
    Vault,
    VaultMember,
    Version,
    VersionText,
)
from ..names import name_key
from ..security import decrypt_secret, encrypt_secret
from . import (
    catalog,
    changes,
    documents,
    filetypes,
    jobs,
    limits,
    ocr,
    outbound,
    receiving,
    search_index,
    settings_service,
    similar,
    storage,
    tell,
)

logger = logging.getLogger("nexpaper.paperless")

#: For the tests: an ``httpx`` transport that stands in for Paperless, a resolver and a clock.
transport: httpx.BaseTransport | None = None
resolver: Callable[[str, int], list[str]] = outbound.resolve
ticks: Callable[[], float] = time.monotonic

TOKEN_CONTEXT = "operator:paperless-token"
#: The whole of one request for data, and the longest a connection may take to be made.
JSON_SECONDS = 30.0
CONNECT_SECONDS = 10.0
#: The whole of one file, however large.
FILE_SECONDS = 900.0
#: The largest answer with data that is read (a page of documents with their text).
JSON_MAX = 32 * 1024 * 1024
#: The most documents one Paperless may have for an import, and the most names of one kind (tags, users ...).
MAX_DOCUMENTS = 100_000
MAX_NAMES = 20_000
#: Documents per page when the numbers are fetched; names per page.
PAGE = 1000
#: How a run sorts: as Paperless did (its inbox into the inbox, the rest filed), or everything into the inbox.
SORTS = ("paperless", "inbox")
#: The lowest version of Paperless's API that has owners and notes (Paperless-ngx 1.14), and the highest asked for.
API_MIN = 3
API_MAX = 9
#: Failures in a row that reach no answer at all (the server gone): the run stops instead of skipping everything.
UNREACHABLE_IN_A_ROW = 3
#: What stays free on the disk besides a file.
DISK_MARGIN = 512 * 1024 * 1024
#: Searchable copies waiting for the reading of their document; gone after this long if nobody took them.
STAGED_DAYS = 30
#: A skip for this reason is not tried again (the person has the very file already).
FOR_GOOD = ("exists",)

IDLE, QUEUED, RUNNING, PAUSED, DONE, FAILED = "idle", "queued", "running", "paused", "done", "failed"
ACTIVE = (QUEUED, RUNNING)

MESSAGES = {
    "paperless_incomplete": "Give the address of Paperless and a token first.",
    "paperless_address_invalid": "This is not an address of a Paperless server.",
    "paperless_address_refused": "This address is never reached.",
    "paperless_address_private": "This address lies in the own network. Allow the own network for Paperless first.",
    "paperless_unreachable": "The server cannot reach Paperless.",
    "paperless_timeout": "Paperless took too long to answer.",
    "paperless_token_refused": "Paperless refused the token.",
    "paperless_not_paperless": "This does not answer like Paperless-ngx.",
    "paperless_too_old": "This Paperless is too old. Paperless-ngx 1.14 or newer is needed.",
    "paperless_unreadable": "The answer of Paperless could not be read.",
    "paperless_failed": "Paperless answered with an error.",
    "paperless_too_many": "Paperless holds more documents than one import takes.",
    "paperless_running": "The import is running already.",
    "paperless_mapping_invalid": "Choose a person for every owner.",
    "paperless_vault_invalid": "Choose a vault the documents can go to.",
    "paperless_address_changed": "The address of Paperless changed since the last start. Connect and look again.",
    "paperless_redirected": "Paperless sends to another address (http to https, say). Give the address it answers at.",
    "paperless_tls_failed": "The certificate of Paperless is not trusted (self-signed?). In the own network use http.",
    "disk_full": "The server has no room left for the files.",
}


class Failure(Exception):
    """Something about Paperless as a whole (the address, the token, the server): the check says it, a run stops."""

    def __init__(self, code: str, status: int = 502, **values: Any) -> None:
        super().__init__(MESSAGES.get(code, code))
        self.code, self.status, self.values = code, status, values

    def http(self) -> HTTPException:
        return error(self.code, str(self), self.status, **self.values)


class Skip(Exception):
    """One document that is not taken, with the reason; the run goes on."""

    def __init__(self, reason: str, document_id: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.document_id = document_id


# --- The address and the token --------------------------------------------------------------------------------------


def check_address(url: str) -> str:
    """The base address of Paperless, cleaned and with its slash at the end (``/api/`` at its end is dropped, the routes
    add it). Only http and https, no credentials, no query."""
    url = (url or "").strip()
    if not url or len(url) > 255:
        raise Failure("paperless_address_invalid", 422)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise Failure("paperless_address_invalid", 422)
    if parts.query or parts.fragment or any(ord(char) < 33 or ord(char) == 127 for char in url):
        raise Failure("paperless_address_invalid", 422)
    try:
        parts.port  # noqa: B018 - raises ValueError when the port is not a number
    except ValueError as exc:
        raise Failure("paperless_address_invalid", 422) from exc
    path = parts.path.rstrip("/")
    path = path.removesuffix("/api")
    return parts._replace(path=path + "/").geturl()


def origin_of(base: str) -> str:
    """The name of a Paperless server in ``PaperlessItem``: its address, without the scheme and in lower case."""
    parts = urlsplit(base)
    shown = f"{(parts.hostname or '').lower()}:{outbound.port_of(base)}{parts.path.rstrip('/').lower()}"
    return hashlib.sha256(shown.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Connection:
    base: str
    token: str
    private: bool

    @property
    def origin(self) -> str:
        return origin_of(self.base)


def connection(db: Session) -> Connection:
    values = settings_service.get_all(db)
    base = str(values["paperless_url"] or "")
    token = decrypt_secret(str(values["paperless_token_enc"] or ""), TOKEN_CONTEXT)
    if not base or not token:
        raise Failure("paperless_incomplete", 409)
    return Connection(base, token, bool(values["paperless_private"]))


def view(db: Session) -> dict[str, Any]:
    """What the card shows: the address, whether a token is kept (never the token), the switch, the plan and the run."""
    values = settings_service.get_all(db)
    plan = values["paperless_plan"] if isinstance(values["paperless_plan"], dict) else {}
    return {
        "url": str(values["paperless_url"] or ""),
        "token_set": bool(values["paperless_token_enc"]),
        "private": bool(values["paperless_private"]),
        "run": run_state(db),
        "where": plan.get("where") if plan.get("where") in ("owner", "vault") else "owner",
        "vault_id": plan.get("vault_id") if isinstance(plan.get("vault_id"), int) else None,
        "sort": plan.get("sort") if plan.get("sort") in SORTS else "paperless",
    }


def save(db: Session, *, url: str | None, token: str | None, private: bool | None) -> dict[str, Any]:
    """Changes what was sent; left out stays. ⚠️ The token belongs to the address it was given for: a new address
    without a new token forgets the old one, or a changed address would carry it to whatever host it names."""
    changes_: dict[str, Any] = {}
    current = settings_service.get_all(db)
    if run_state(db)["state"] in ACTIVE:
        raise Failure("paperless_running", 409)
    if url is not None:
        base = check_address(url) if url.strip() else ""
        changes_["paperless_url"] = base
        if base != current["paperless_url"] and token is None and current["paperless_token_enc"]:
            changes_["paperless_token_enc"] = ""
    if token is not None:
        cleaned = token.strip()
        if any(ord(char) < 33 or ord(char) == 127 for char in cleaned) or len(cleaned) > 200:
            raise Failure("paperless_token_refused", 422)
        changes_["paperless_token_enc"] = encrypt_secret(cleaned, TOKEN_CONTEXT) if cleaned else ""
    if private is not None:
        changes_["paperless_private"] = private
    settings_service.save(db, changes_)
    logger.info("The operator changed the Paperless connection fields=%s", ",".join(sorted(changes_)) or "nothing")
    return view(db)


def forget(db: Session) -> dict[str, Any]:
    """The connection goes (address and token); what was taken stays, and so does the memory of what was taken."""
    if run_state(db)["state"] in ACTIVE:
        raise Failure("paperless_running", 409)
    settings_service.save(db, {"paperless_url": "", "paperless_token_enc": "", "paperless_private": False})
    logger.info("The operator removed the Paperless connection")
    return view(db)


def _unreachable(exc: Exception) -> Failure:
    """No answer: a certificate that is not trusted says so (a self-signed one in the own network), the rest is
    ``paperless_unreachable``."""
    text = str(exc)
    if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text.lower():
        return Failure("paperless_tls_failed")
    return Failure("paperless_unreachable")


def whole_pdf(path: Path) -> bool:
    """The searchable copy is taken only when it is a PDF from its start to its end: ``%PDF-`` at the start (checked
    by ``filetypes.sniff``) and ``%%EOF`` in its last bytes. Nothing more is read here; the copy is opened only in the
    worker process (pages, pictures), with its limits."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 2048))
            return b"%%EOF" in handle.read()
    except OSError:
        return False


def _owner_in(db: Session, vault_id: int, owner: int, operator: int) -> int:
    """Everything into one vault: the owner must see what they own there. A person who is not in that vault is not
    its owner; the operator who started the run is (when in the vault), else the first who manages it."""
    if db.get(VaultMember, (vault_id, owner)) is not None:
        return owner
    if db.get(VaultMember, (vault_id, operator)) is not None:
        return operator
    manager = db.scalar(select(VaultMember.user_id).where(VaultMember.vault_id == vault_id,
                                                          VaultMember.right == "manage").order_by(VaultMember.user_id))
    return int(manager) if manager is not None else owner


# --- Talking to Paperless -------------------------------------------------------------------------------------------


class Client:
    """Requests to one Paperless server: every one to the checked addresses only, with its deadline and limit."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.session = outbound.client(transport)
        self.api_version = 0
        self.version = ""

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = urljoin(self.conn.base, path)
        return url + ("?" + urlencode(params) if params else "")

    def _place(self, url: str) -> outbound.Target:
        def rule(ip: Any) -> None:
            if not self.conn.private and not outbound.public(str(ip)):
                raise Failure("paperless_address_private", 422)

        try:
            return outbound.pin(url, resolver, rule)
        except outbound.Refused as exc:
            raise Failure("paperless_address_refused", 422) from exc
        except outbound.Unreachable as exc:
            raise Failure("paperless_unreachable") from exc

    def _headers(self) -> dict[str, str]:
        accept = f"application/json; version={self.api_version}" if self.api_version else "application/json"
        return {"Authorization": f"Token {self.conn.token}", "Accept": accept}

    def get(self, path: str, params: dict[str, Any] | None = None, *, allow: tuple[int, ...] = ()) -> tuple[Any, int]:
        """The JSON of an answer and its status. A status in ``allow`` is handed back (with no data) instead of
        failing."""
        place = self._place(self._url(path, params))
        started = ticks()
        try:
            answer = outbound.send(self.session, "GET", place, self._headers(), deadline=started + JSON_SECONDS,
                                   ticks=ticks, limit=JSON_MAX, connect_seconds=CONNECT_SECONDS)
        except outbound.Late as exc:
            raise Failure("paperless_timeout", 504) from exc
        except (outbound.TooLarge, outbound.Refused) as exc:
            raise Failure("paperless_unreadable") from exc
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc
        if not self.api_version:
            self._learn(answer)
        if answer.status_code in allow:
            return None, answer.status_code
        self._judge(answer.status_code)
        try:
            return answer.json(), answer.status_code
        except ValueError as exc:
            raise Failure("paperless_unreadable") from exc

    def _learn(self, answer: httpx.Response) -> None:
        raw = answer.headers.get("x-api-version", "")
        self.version = "".join(c for c in answer.headers.get("x-version", "")[:20] if c.isprintable())
        if raw.strip().isdigit():
            self.api_version = min(int(raw.strip()), API_MAX)

    @staticmethod
    def _judge(status: int) -> None:
        if status == 200:
            return
        if status in (401, 403):
            raise Failure("paperless_token_refused")
        if status in (404, 405, 406):
            raise Failure("paperless_not_paperless")
        if status in (301, 302, 303, 307, 308):
            # Not followed (it could lead anywhere): the operator types the address Paperless answers at.
            raise Failure("paperless_redirected", answered=status)
        raise Failure("paperless_failed", answered=status)

    def handshake(self) -> None:
        """The first request: whether this is Paperless-ngx, which version, and whether the token holds."""
        _data, _status = self.get("api/documents/", {"page_size": 1})
        if not self.api_version:
            raise Failure("paperless_not_paperless")
        if self.api_version < API_MIN:
            raise Failure("paperless_too_old")

    def download(self, path: str, params: dict[str, Any], target: Path, limit: int) -> outbound.Saved:
        place = self._place(self._url(path, params))
        started = ticks()
        try:
            return outbound.download(self.session, place, self._headers(), target, deadline=started + FILE_SECONDS,
                                     ticks=ticks, limit=limit, connect_seconds=CONNECT_SECONDS)
        except outbound.Late as exc:
            raise Skip("download_timeout") from exc
        except outbound.TooLarge as exc:
            raise Skip("too_large") from exc
        except outbound.Refused as exc:
            raise Skip("download_failed") from exc
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc

    def pages(self, path: str, params: dict[str, Any], most: int) -> list[dict[str, Any]]:
        """Every result of a list, page by page (the page numbers counted here: a ``next`` address in an answer is never
        followed). At most ``most`` results; more is ``paperless_too_many``."""
        found: list[dict[str, Any]] = []
        page = 1
        while True:
            data, _status = self.get(path, {**params, "page": page})
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise Failure("paperless_unreadable")
            results = [item for item in data["results"] if isinstance(item, dict)]
            found.extend(results)
            if len(found) > most:
                raise Failure("paperless_too_many", 422, max=most)
            count = data.get("count")
            if not results or not data.get("next") or (isinstance(count, int) and len(found) >= count):
                return found
            page += 1
            if page > most // max(1, len(results)) + 2:
                raise Failure("paperless_unreadable")

    def count(self, path: str, params: dict[str, Any] | None = None) -> int:
        data, _status = self.get(path, {**(params or {}), "page_size": 1})
        if not isinstance(data, dict) or not number(data.get("count"), allow_zero=True):
            raise Failure("paperless_unreadable")
        return int(data["count"])


# --- Reading what Paperless says ------------------------------------------------------------------------------------


def number(value: Any, *, allow_zero: bool = False) -> bool:
    """An id or a count as Paperless gives them: a whole number (never a boolean), in range."""
    return type(value) is int and (0 if allow_zero else 1) <= value < 2**31


def text_of(value: Any, limit: int) -> str:
    """A text of Paperless, without control characters (lines and tabs kept), cut to ``limit``."""
    if not isinstance(value, str):
        return ""
    cleaned = "".join(char if char.isprintable() or char in "\n\t" else " " for char in value[: limit * 2])
    return cleaned.strip()[:limit]


def name_of(value: Any, limit: int) -> str:
    return " ".join(text_of(value, limit * 2).split())[:limit].strip()


def date_of(value: Any) -> Date | None:
    """``2026-03-14`` or ``2026-03-14T10:00:00+01:00`` (the day as written; no time zone moves it)."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        day = Date.fromisoformat(value[:10])
    except ValueError:
        return None
    return day if documents.DATE_MIN <= day <= documents.DATE_MAX else None


def moment_of(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment if moment.year >= 1900 and moment <= clock.now() + timedelta(days=1) else None


@dataclass
class Names:
    """The lists of Paperless: tags (name, inbox tag), correspondents, document types, users (name, groups), custom
    fields (name, type, the options of a choice)."""

    tags: dict[int, tuple[str, bool]] = field(default_factory=dict)
    correspondents: dict[int, str] = field(default_factory=dict)
    types: dict[int, str] = field(default_factory=dict)
    users: dict[int, tuple[str, list[int]]] = field(default_factory=dict)
    fields: dict[int, tuple[str, str, dict[str, str]]] = field(default_factory=dict)
    #: The token may not list the users (no right to): owners are known by their number only.
    users_hidden: bool = False


def _named(rows: list[dict[str, Any]], limit: int) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in rows:
        name = name_of(row.get("name"), limit)
        if number(row.get("id")) and name:
            out[int(row["id"])] = name
    return out


def names(client: Client) -> Names:
    found = Names()
    for row in client.pages("api/tags/", {"page_size": PAGE}, MAX_NAMES):
        name = name_of(row.get("name"), catalog.TAG_MAX * 4)
        if number(row.get("id")) and name:
            found.tags[int(row["id"])] = (name, row.get("is_inbox_tag") is True)
    found.correspondents = _named(client.pages("api/correspondents/", {"page_size": PAGE}, MAX_NAMES),
                                  catalog.SENDER_MAX)
    found.types = _named(client.pages("api/document_types/", {"page_size": PAGE}, MAX_NAMES), catalog.KIND_MAX)
    _data, status = client.get("api/users/", {"page_size": PAGE}, allow=(401, 403, 404))
    if status != 200:
        found.users_hidden = True
    else:
        for row in client.pages("api/users/", {"page_size": PAGE}, MAX_NAMES):
            username = name_of(row.get("username"), 64)
            groups = [g for g in row.get("groups") or [] if number(g)] if isinstance(row.get("groups"), list) else []
            if number(row.get("id")) and username:
                found.users[int(row["id"])] = (username, groups[:200])
    _data, status = client.get("api/custom_fields/", {"page_size": PAGE}, allow=(401, 403, 404))
    if status == 200:
        for row in client.pages("api/custom_fields/", {"page_size": PAGE}, MAX_NAMES):
            name = name_of(row.get("name"), 80)
            if not number(row.get("id")) or not name:
                continue
            options: dict[str, str] = {}
            extra = row.get("extra_data")
            raw = extra.get("select_options") if isinstance(extra, dict) else None
            if isinstance(raw, list):
                for index, option in enumerate(raw[:500]):
                    if isinstance(option, dict):
                        options[str(option.get("id"))] = name_of(option.get("label"), 120)
                    else:
                        options[str(index)] = name_of(option, 120)
            found.fields[int(row["id"])] = (name, name_of(row.get("data_type"), 20), options)
    return found


def document_ids(client: Client, inbox_tags: frozenset[int] = frozenset()
                 ) -> list[tuple[int, int | None, int | None, bool]]:
    """``(id, owner, document type, in Paperless's inbox)`` of every document, in the order of their numbers; in the
    inbox means carrying one of ``inbox_tags``. A Paperless that ignores ``fields`` sends whole documents: then the
    pages are made smaller until they fit."""
    for size in (PAGE, 100, 10):
        try:
            rows = client.pages("api/documents/", {"page_size": size, "ordering": "id",
                                                   "fields": "id,owner,document_type,tags", "truncate_content": "true"},
                                MAX_DOCUMENTS)
            break
        except Failure as exc:
            if exc.code != "paperless_unreadable" or size == 10:
                raise
    out: dict[int, tuple[int | None, int | None, bool]] = {}
    for row in rows:
        if number(row.get("id")):
            owner, kind = row.get("owner"), row.get("document_type")
            tags = row.get("tags") if isinstance(row.get("tags"), list) else []
            in_inbox = any(number(tag) and int(tag) in inbox_tags for tag in tags[:1000])
            out[int(row["id"])] = (int(owner) if number(owner) else None, int(kind) if number(kind) else None,
                                   in_inbox)
    return [(pid, owner, kind, in_inbox) for pid, (owner, kind, in_inbox) in sorted(out.items())]


# --- Looking before taking ------------------------------------------------------------------------------------------


def _person_named(db: Session, name: str) -> Account | None:
    if not name:
        return None
    key = name.strip().casefold()
    for row in db.scalars(select(Account).where(Account.blocked_at.is_(None))):
        if row.name == key or (row.display_name and row.display_name.casefold() == key):
            return row
    return None


def operator_of(db: Session) -> Account | None:
    return db.scalar(select(Account).where(Account.role == OPERATOR, Account.blocked_at.is_(None))
                     .order_by(Account.id).limit(1))


def check(db: Session, operator_id: int) -> dict[str, Any]:
    """"Connect and look": what Paperless holds and how it would come over, without writing anything."""
    conn = connection(db)
    db.rollback()
    with Client(conn) as client:
        client.handshake()
        total = client.count("api/documents/")
        if total > MAX_DOCUMENTS:
            raise Failure("paperless_too_many", 422, max=MAX_DOCUMENTS)
        found = names(client)
        scanned = document_ids(client, frozenset(tag for tag, (_name, inbox) in found.tags.items() if inbox))
    owned = Counter(owner for _id, owner, _kind, _inbox in scanned)
    used = {kind for _id, _owner, kind, _inbox in scanned if kind is not None}
    # The kinds that come with nexpaper count as known even before they are in the list (looking writes nothing). The
    # others are made in the vault a document goes to, when it comes.
    known = {key for (key,) in db.execute(select(Kind.name_key).where(Kind.vault_id.is_(None)))}
    if not settings_service.get(db, "kinds_seeded"):
        known |= {name_key(name) for _key, name, _hue in catalog.DEFAULT_KINDS}
    new_kinds = sorted({name for type_id, name in found.types.items() if name_key(name) not in known
                        and type_id in used}, key=str.casefold)
    owners = []
    for owner, count in sorted(owned.items(), key=lambda pair: (pair[0] is None, pair[0] or 0)):
        username = found.users.get(owner, ("", []))[0] if owner is not None else ""
        person = _person_named(db, username)
        owners.append({"paperless_id": owner, "name": username, "documents": count, "matched": person is not None,
                       "user_id": person.id if person is not None else operator_id})
    already = len(db.scalars(select(PaperlessItem.paperless_id).where(
        PaperlessItem.origin == conn.origin, PaperlessItem.state == "done")).all())
    return {
        "version": client.version, "api_version": client.api_version, "documents": total,
        "tags": len(found.tags), "correspondents": len(found.correspondents), "document_types": len(found.types),
        "custom_fields": len(found.fields), "new_kinds": new_kinds[:50], "owners": owners,
        "users_hidden": found.users_hidden, "already": already,
        # For the question how to sort: how many Paperless still had in its inbox.
        "inbox_documents": sum(1 for _id, _owner, _kind, inbox in scanned if inbox),
    }


# --- Starting, stopping, where it stands ----------------------------------------------------------------------------


def run_state(db: Session) -> dict[str, Any]:
    raw = settings_service.get(db, "paperless_run")
    run = raw if isinstance(raw, dict) else {}
    reasons = run.get("reasons") if isinstance(run.get("reasons"), dict) else {}
    return {
        "state": run.get("state") if run.get("state") in (IDLE, QUEUED, RUNNING, PAUSED, DONE, FAILED) else IDLE,
        "total": int(run.get("total") or 0), "done": int(run.get("done") or 0),
        "skipped": int(run.get("skipped") or 0), "taken": int(run.get("taken") or 0),
        "reasons": {str(k): int(v) for k, v in reasons.items() if isinstance(v, int)},
        "error": str(run.get("error") or ""), "stop": bool(run.get("stop")),
        "started_at": run.get("started_at"), "finished_at": run.get("finished_at"),
    }


def _save_run(db: Session, **values: Any) -> None:
    """Changes some values of the run, read and written under the write lock: the operator's ``stop`` written at the
    same moment is never lost."""
    changes.write_lock(db)
    run = run_state(db)
    run.update(values)
    settings_service.save(db, {"paperless_run": run})


def start(db: Session, operator: Account, *, where: str, vault_id: int | None,
          people: list[tuple[int | None, int]], sort: str = "paperless") -> dict[str, Any]:
    """The run, queued: who is who, where it goes, and how it is sorted (``paperless``: what Paperless had in its inbox
    waits in the inbox, the rest is filed; ``inbox``: everything waits in the inbox). One at a time (checked and written
    under the write lock); a second start while one runs is ``paperless_running``."""
    conn = connection(db)
    if where not in ("owner", "vault"):
        raise Failure("paperless_vault_invalid", 422)
    if sort not in SORTS:
        raise Failure("paperless_sort_invalid", 422)
    chosen: dict[str, int] = {}
    for paperless_id, user_id in people[:5000]:
        row = db.get(Account, user_id)
        if row is None or row.blocked_at is not None:
            raise Failure("paperless_mapping_invalid", 422)
        chosen["none" if paperless_id is None else str(paperless_id)] = user_id
    if where == "vault":
        vault = db.get(Vault, vault_id) if vault_id is not None else None
        if vault is None or (vault.personal_of is not None and vault.personal_of != operator.id):
            raise Failure("paperless_vault_invalid", 422)
    changes.write_lock(db)
    if run_state(db)["state"] in ACTIVE:
        db.rollback()
        raise Failure("paperless_running", 409)
    plan = {"origin": conn.origin, "where": where, "vault_id": vault_id if where == "vault" else None,
            "people": chosen, "by": operator.id, "sort": sort}
    run = {"state": QUEUED, "total": 0, "done": 0, "skipped": 0, "taken": 0, "reasons": {}, "error": "",
           "stop": False, "started_at": clock.now().isoformat(), "finished_at": None}
    jobs.enqueue(db, jobs.IMPORT, 0)
    settings_service.save(db, {"paperless_plan": plan, "paperless_run": run})
    logger.info("Paperless import queued where=%s sort=%s people=%s by=%s", where, sort, len(chosen), operator.name)
    return view(db)


def resume(db: Session, operator: Account) -> dict[str, Any]:
    """Starts again with what was chosen at the last start, for the same Paperless."""
    plan = _plan(db)
    if not plan.origin:
        raise Failure("paperless_mapping_invalid", 422)
    if plan.origin != connection(db).origin:
        # The address changed since the last start: look again, who is who may be different there.
        raise Failure("paperless_address_changed", 409)
    people: list[tuple[int | None, int]] = [(None if key == "none" else int(key), user_id)
                                            for key, user_id in plan.people.items() if key == "none" or key.isdigit()]
    return start(db, operator, where=plan.where, vault_id=plan.vault_id, people=people, sort=plan.sort)


#: The most skipped documents the card lists; the rest is only counted.
SKIPPED_LISTED = 50


def skipped(db: Session) -> dict[str, Any]:
    """The documents of this Paperless that were skipped and wait for another try, for the operator's card: the number
    in Paperless and the reason (a code), never a title or any other word of Paperless. At most ``SKIPPED_LISTED``,
    the lowest numbers first; ``more`` counts the rest."""
    origin = _plan(db).origin
    if not origin:
        return {"items": [], "total": 0, "more": 0}
    where = (PaperlessItem.origin == origin, PaperlessItem.state == "skipped")
    total = int(db.scalar(select(func.count()).select_from(PaperlessItem).where(*where)) or 0)
    rows = db.execute(select(PaperlessItem.paperless_id, PaperlessItem.reason).where(*where)
                      .order_by(PaperlessItem.paperless_id).limit(SKIPPED_LISTED)).all()
    return {"items": [{"paperless_id": int(pid), "reason": str(reason or "")} for pid, reason in rows],
            "total": total, "more": max(0, total - len(rows))}


def stop(db: Session) -> dict[str, Any]:
    """The run stops after the document it is at; it can be started again and goes on where it stopped."""
    changes.write_lock(db)
    state = run_state(db)
    if state["state"] in ACTIVE:
        _save_run(db, stop=True)
    else:
        db.rollback()
    return view(db)


# --- The run --------------------------------------------------------------------------------------------------------


@dataclass
class Plan:
    origin: str
    where: str
    vault_id: int | None
    people: dict[str, int]
    by: int
    sort: str = "paperless"


def _plan(db: Session) -> Plan:
    raw = settings_service.get(db, "paperless_plan")
    plan = raw if isinstance(raw, dict) else {}
    people = {str(k): int(v) for k, v in (plan.get("people") or {}).items() if isinstance(v, int)}
    return Plan(origin=str(plan.get("origin") or ""), where=str(plan.get("where") or "owner"),
                vault_id=plan.get("vault_id") if isinstance(plan.get("vault_id"), int) else None, people=people,
                by=int(plan.get("by") or 0), sort=plan.get("sort") if plan.get("sort") in SORTS else "paperless")


def staging() -> Path:
    """Where the searchable copy of a document waits until the document is read (``given_text``)."""
    folder = get_settings().data_dir / "paperless"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def staged_archive(document_id: int) -> Path:
    return staging() / f"{int(document_id)}.pdf"


def run_job(db: Session, attempt: int) -> None:
    """The job ``import``: every document of Paperless not taken yet, one at a time."""
    state = run_state(db)
    if state["state"] not in ACTIVE:
        db.rollback()
        return
    if state["stop"]:
        _save_run(db, state=PAUSED, stop=False, finished_at=clock.now().isoformat())
        return
    _save_run(db, state=RUNNING, error="")
    try:
        _run(db)
    except jobs.Interrupted:
        raise
    except Failure as exc:
        db.rollback()
        _save_run(db, state=FAILED, error=exc.code, finished_at=clock.now().isoformat(), stop=False)
        logger.warning("Paperless import stopped error=%s", exc.code)
        raise jobs.GiveUp(exc.code) from None
    except Exception as exc:
        db.rollback()
        _save_run(db, state=FAILED, error="failed", finished_at=clock.now().isoformat(), stop=False)
        logger.exception("Paperless import failed")
        raise jobs.GiveUp("failed") from exc


def _run(db: Session) -> None:
    plan = _plan(db)
    conn = connection(db)
    if conn.origin != plan.origin:
        # The address changed since the start: the plan was made for another server.
        raise Failure("paperless_incomplete", 409)
    db.rollback()
    with Client(conn) as client:
        client.handshake()
        found = names(client)
        everything = document_ids(client)
        taken = set(db.scalars(select(PaperlessItem.paperless_id).where(
            PaperlessItem.origin == plan.origin,
            (PaperlessItem.state == "done") | PaperlessItem.reason.in_(FOR_GOOD))))
        db.rollback()
        pending = [(pid, owner) for pid, owner, _kind, _inbox in everything if pid not in taken]
        done_before = len(everything) - len(pending)
        _save_run(db, total=len(everything), done=done_before, skipped=0, taken=0, reasons={})
        reasons: Counter[str] = Counter()
        imported = 0
        in_a_row = 0
        made_ids: list[int] = []
        for pid, _owner in pending:
            if jobs.stopping.is_set():
                raise jobs.Interrupted
            if run_state(db)["stop"]:
                _save_run(db, state=PAUSED, stop=False, finished_at=clock.now().isoformat())
                logger.info("Paperless import paused taken=%s skipped=%s", imported, sum(reasons.values()))
                return
            db.rollback()
            try:
                made_ids.append(take_one(db, client, found, plan, pid))
                imported += 1
                in_a_row = 0
            except Skip as exc:
                db.rollback()
                reasons[exc.reason] += 1
                _skipped(db, plan.origin, pid, exc.reason, exc.document_id)
                logger.info("Paperless document skipped paperless_id=%s reason=%s", pid, exc.reason)
                in_a_row = 0
            except Failure as exc:
                db.rollback()
                if exc.code not in ("paperless_unreachable", "paperless_timeout") or in_a_row + 1 >= \
                        UNREACHABLE_IN_A_ROW:
                    raise
                in_a_row += 1
                reasons["unreachable"] += 1
                _skipped(db, plan.origin, pid, "unreachable", None)
                logger.info("Paperless document skipped paperless_id=%s reason=unreachable", pid)
            _save_run(db, done=done_before + imported, taken=imported, skipped=sum(reasons.values()),
                      reasons=dict(reasons))
    _save_run(db, state=DONE, finished_at=clock.now().isoformat(), stop=False)
    logger.info("Paperless import done taken=%s skipped=%s", imported, sum(reasons.values()))
    tell_people(db, made_ids)


CLOSING = chr(10) * 2 + "Open nexpaper: {where}" + chr(10)
TEXTS = {
    "de": ("Paperless-Import fertig", "{count} Dokumente aus Paperless liegen jetzt bei dir.",
           " {inbox} davon warten im Eingang."),
    "en": ("Paperless import done", "{count} documents from Paperless are now yours.",
           " {inbox} are waiting in your inbox."),
}


def tell_people(db: Session, document_ids: list[int]) -> None:
    """After a run: each person who now has documents from it (they own them, or got them shared when everything went
    into one vault) is told how many and how many wait in the inbox, in the background. People who got nothing hear
    nothing; nothing names a document."""
    if not document_ids:
        return
    owned: Counter[int] = Counter()
    waiting: Counter[int] = Counter()
    for start in range(0, len(document_ids), 500):
        chunk = document_ids[start : start + 500]
        # A document is read after the import, so its status says "processing" yet: the flag of the item says whether
        # Paperless had it in its inbox, and so whether it lands in this one.
        rows = db.execute(select(Document.owner_id, PaperlessItem.inbox)
                          .outerjoin(PaperlessItem, PaperlessItem.document_id == Document.id)
                          .where(Document.id.in_(chunk)))
        for owner, in_inbox in rows:
            if owner is not None:
                owned[owner] += 1
                waiting[owner] += int(bool(in_inbox))
        for (user,) in db.execute(select(Share.user_id).where(Share.document_id.in_(chunk))):
            owned[user] += 1
    db.rollback()
    for person, count in owned.items():
        inbox = waiting[person]
        texts = {lang: (title, (body + (tail if inbox else "")).format(count=count, inbox=inbox))
                 for lang, (title, body, tail) in TEXTS.items()}
        tell.person(person, tell.Notice(
            texts=texts, url="/eingang" if inbox else "/", tag="paperless-import",
            mail_subject="nexpaper: the import from Paperless is done",
            mail_body=f"{count} documents from Paperless are now in nexpaper for you"
                      + (f", {inbox} of them waiting in your inbox" if inbox else "") + "." + CLOSING))


def _skipped(db: Session, origin: str, pid: int, reason: str, document_id: int | None) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    values = {"origin": origin, "paperless_id": pid, "document_id": document_id, "state": "skipped",
              "reason": reason[:32], "inbox": False, "at": clock.now()}
    db.execute(sqlite_insert(PaperlessItem).values(**values).on_conflict_do_update(
        index_elements=["origin", "paperless_id"], set_={"state": "skipped", "reason": reason[:32],
                                                          "document_id": document_id, "at": clock.now()}))
    db.commit()


# --- One document ---------------------------------------------------------------------------------------------------


@dataclass
class Incoming:
    """One document of Paperless, its answer read and checked."""

    pid: int
    title: str
    file_name: str
    day: Date | None
    sender: str
    kind: str
    tags: list[str]
    inbox: bool
    owner: int | None
    content: str
    has_archive: bool
    notes: list[tuple[str, int | None, datetime | None]]
    fields: str
    readers: list[int]
    writers: list[int]
    #: Everything into one vault the owner is not in: the person it belonged to, who gets it as a share.
    keeper: int | None = None


def _ids(value: Any, most: int = 500) -> list[int]:
    return [int(item) for item in value[:most] if number(item)] if isinstance(value, list) else []


def _field_value(value: Any, kind: str, options: dict[str, str]) -> str:
    if value is None or value == "":
        return ""
    if kind == "select":
        return options.get(str(value), name_of(value, 200) if isinstance(value, str) else "")
    if kind == "documentlink":
        return ", ".join(f"#{item}" for item in _ids(value, 50))
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if isinstance(value, int | float):
        return str(value)
    return text_of(value, 500).replace("\n", " ")


def read(data: Any, found: Names, pid: int) -> Incoming:
    if not isinstance(data, dict) or data.get("id") != pid:
        raise Skip("invalid_answer")
    tags, inbox = [], False
    for tag_id in _ids(data.get("tags")):
        name, is_inbox = found.tags.get(tag_id, ("", False))
        if is_inbox:
            inbox = True
        elif name:
            tags.append(name[: catalog.TAG_MAX].strip())
    notes: list[tuple[str, int | None, datetime | None]] = []
    for row in (data.get("notes") or [])[:200] if isinstance(data.get("notes"), list) else []:
        if not isinstance(row, dict):
            continue
        body = text_of(row.get("note"), documents.NOTE_MAX)
        user = row.get("user")
        user_id = user.get("id") if isinstance(user, dict) else user
        if body:
            notes.append((body, int(user_id) if number(user_id) else None, moment_of(row.get("created"))))
    lines = []
    asn = data.get("archive_serial_number")
    if number(asn, allow_zero=True):
        lines.append(f"ASN: {asn}")
    for row in (data.get("custom_fields") or [])[:200] if isinstance(data.get("custom_fields"), list) else []:
        if not isinstance(row, dict) or not number(row.get("field")):
            continue
        name, kind, options = found.fields.get(int(row["field"]), (f"#{row['field']}", "", {}))
        value = _field_value(row.get("value"), kind, options)
        if value:
            lines.append(f"{name}: {value}")
    readers: list[int] = []
    writers: list[int] = []
    permissions = data.get("permissions")
    if isinstance(permissions, dict):
        for right, into in (("view", readers), ("change", writers)):
            part = permissions.get(right)
            if not isinstance(part, dict):
                continue
            into.extend(_ids(part.get("users")))
            groups = set(_ids(part.get("groups")))
            if groups:
                into.extend(uid for uid, (_n, member_of) in found.users.items() if groups & set(member_of))
    correspondent = data.get("correspondent")
    kind_id = data.get("document_type")
    owner = data.get("owner")
    file_name = name_of(data.get("original_file_name"), 200)
    return Incoming(
        pid=pid, title=name_of(data.get("title"), documents.TITLE_MAX), file_name=file_name,
        day=date_of(data.get("created_date")) or date_of(data.get("created")),
        sender=found.correspondents.get(int(correspondent), "") if number(correspondent) else "",
        kind=found.types.get(int(kind_id), "") if number(kind_id) else "",
        tags=list(dict.fromkeys(t for t in tags if t))[: catalog.MAX_TAGS_PER_DOCUMENT], inbox=inbox,
        owner=int(owner) if number(owner) else None, content=text_of(data.get("content"), ocr.MAX_CHARS),
        has_archive=bool(data.get("archived_file_name")), notes=notes,
        fields=("Paperless\n" + "\n".join(lines))[: documents.NOTE_MAX] if lines else "",
        readers=readers, writers=writers,
    )


def _person(db: Session, plan: Plan, found: Names, paperless_user: int | None, *, owner: bool) -> int | None:
    """The person here for a user of Paperless: the operator's choice for owners, else the one of the same name."""
    chosen = plan.people.get("none" if paperless_user is None else str(paperless_user))
    if chosen is not None:
        row = db.get(Account, chosen)
        if row is not None and row.blocked_at is None:
            return row.id
    if paperless_user is not None and paperless_user in found.users:
        row = _person_named(db, found.users[paperless_user][0])
        if row is not None:
            return row.id
    if not owner:
        return None
    fallback = db.get(Account, plan.by)
    if fallback is not None and fallback.blocked_at is None:
        return fallback.id
    other = operator_of(db)
    return other.id if other is not None else None


def _kind_id(db: Session, vault_id: int, owner: int, name: str) -> int | None:
    """The kind of this name for documents of the vault: one of the server's, else the vault's own, made when there is
    none (in a write of its own, before the document's). The kinds of Paperless land in the vault they come to, never in
    the list of the whole server."""
    if not name:
        return None
    try:
        name = catalog.clean_word(name, catalog.KIND_MAX, "invalid_name")
    except HTTPException:
        return None
    found = catalog.kind_called(db, vault_id, name_key(name))
    if found is not None:
        return int(found.id)
    hue = int(hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest(), 16) % 360
    try:
        changes.write_lock(db)
        made = catalog.kind_in_vault(db, vault_id, owner, name, hue)
        db.commit()
        return int(made.id)
    except HTTPException:
        db.rollback()
        found = catalog.kind_called(db, vault_id, name_key(name))
        return int(found.id) if found is not None else None


def _room_for(size: int) -> None:
    try:
        free = shutil.disk_usage(get_settings().data_dir).free
    except OSError:
        return
    if free < size + DISK_MARGIN:
        raise Failure("disk_full", 507)


def _fetch(client: Client, pid: int, original: bool, limit: int) -> tuple[Path, outbound.Saved, str]:
    """A file of the document to a temporary place, with its kind (``Skip`` when it is none that is taken)."""
    target = storage.incoming_path("paperless-")
    saved = client.download(f"api/documents/{pid}/download/", {"original": "true"} if original else {}, target, limit)
    if saved.status == 404:
        target.unlink(missing_ok=True)
        raise Skip("file_missing")
    if saved.status in (401, 403):
        target.unlink(missing_ok=True)
        raise Failure("paperless_token_refused")
    if saved.status != 200:
        target.unlink(missing_ok=True)
        raise Skip("download_failed")
    if saved.size == 0:
        target.unlink(missing_ok=True)
        raise Skip("empty_file")
    try:
        kind = filetypes.sniff(saved.head).kind
    except filetypes.NotAccepted as exc:
        target.unlink(missing_ok=True)
        raise Skip(exc.reason) from None
    return target, saved, kind


def _ending(file_name: str) -> str:
    """The ending of a file name as a short word ("docx"), or "other" when it has none of plain letters and digits."""
    ending = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return ending if ending and len(ending) <= 8 and ending.isascii() and ending.isalnum() else "other"


def take_one(db: Session, client: Client, found: Names, plan: Plan, pid: int) -> int:
    """One document of Paperless becomes one here. Returns its id; ``Skip`` when it is not taken."""
    data, status = client.get(f"api/documents/{pid}/", {"full_perms": "true"}, allow=(404,))
    if status == 404:
        raise Skip("gone")
    incoming = read(data, found, pid)
    owner = _person(db, plan, found, incoming.owner, owner=True)
    if owner is None:
        raise Skip("no_person")
    if plan.where == "vault":
        vault_id = plan.vault_id
        if vault_id is None or db.get(Vault, vault_id) is None:
            raise Failure("paperless_vault_invalid", 409)
        chosen = owner
        owner = _owner_in(db, vault_id, owner, plan.by)
        if owner != chosen:
            # The person it belonged to keeps it: shared with them, with the right to change it.
            incoming.keeper = chosen
    else:
        vault_id = receiving.personal_vault(db, owner)
    kind_id = _kind_id(db, vault_id, owner, incoming.kind)
    limit = limits.current(db).max_file
    db.rollback()
    _room_for(limit)
    archive: Path | None = None
    #: The ending of the original when the document is taken as its PDF from Paperless ("docx"), else empty.
    from_archive = ""
    #: The original is gone in Paperless (404) and the searchable copy is taken in its place.
    original_missing = False
    try:
        path, saved, kind = _fetch(client, pid, True, limit)
    except Skip as exc:
        # An original nexpaper does not take (a Word file Paperless turned into a PDF), or one Paperless no longer has
        # (404 on the original): the PDF Paperless made of it is the document here, as its original, and the history
        # says so. Office files themselves are not taken. The copy must be a whole PDF, else the skip stands.
        missing = exc.reason == "file_missing"
        if not missing and exc.reason not in ("unsupported_type", "xml_not_invoice", "xml_doctype"):
            raise
        if not incoming.has_archive:
            raise
        failed = "file_missing" if missing else "unsupported_type"
        try:
            path, saved, kind = _fetch(client, pid, False, limit)
        except Skip:
            raise Skip(failed) from None
        if kind != filetypes.PDF or not whole_pdf(path):
            path.unlink(missing_ok=True)
            raise Skip(failed) from None
        if missing:
            original_missing = True
        else:
            from_archive = _ending(incoming.file_name)
        logger.info("Paperless document taken as its PDF from Paperless paperless_id=%s original_missing=%s", pid,
                    original_missing)
        incoming.has_archive = False
    try:
        if incoming.has_archive and kind != filetypes.XML:
            try:
                archive, _saved, archive_kind = _fetch(client, pid, False, limit)
                if archive_kind != filetypes.PDF or not whole_pdf(archive):
                    archive.unlink(missing_ok=True)
                    archive = None
            except Skip:
                archive = None
        twin = similar.same_file(db, owner, saved.sha256)
        if twin is not None:
            raise Skip("exists", twin.id)
        db.rollback()
        made = _create(db, plan, found, incoming, owner=owner, vault_id=vault_id, kind_id=kind_id, path=path,
                       kind=kind, saved=saved, archive=archive, from_archive=from_archive,
                       original_missing=original_missing)
    finally:
        path.unlink(missing_ok=True)
        if archive is not None:
            archive.unlink(missing_ok=True)
    return made


def _create(db: Session, plan: Plan, found: Names, incoming: Incoming, *, owner: int, vault_id: int,
            kind_id: int | None, path: Path, kind: str, saved: outbound.Saved, archive: Path | None,
            from_archive: str = "", original_missing: bool = False) -> int:
    staged: list[Path] = []

    def fill(session: Session, document: Document) -> None:
        session.flush()
        if incoming.sender:
            try:
                document.sender_id = catalog.sender_named(session, vault_id, owner, incoming.sender).id
            except HTTPException:
                pass
        document.kind_id = kind_id
        document.date = incoming.day
        tags = []
        for name in incoming.tags:
            try:
                tags.extend(catalog.tags_named(session, vault_id, owner, [name]))
            except HTTPException:
                continue
        for tag in {t.id: t for t in tags}.values():
            session.add(DocumentTag(document_id=document.id, tag_id=tag.id))
        for body, user, moment in incoming.notes:
            writer = _person(session, plan, found, user, owner=False) or owner
            session.add(Note(document_id=document.id, user_id=writer, text=body, created_at=moment or clock.now()))
        if incoming.fields:
            session.add(Note(document_id=document.id, user_id=owner, text=incoming.fields, created_at=clock.now()))
        _shares(session, plan, found, incoming, document, owner)
        version = session.scalar(select(Version).where(Version.document_id == document.id, Version.n == 1))
        if version is not None and kind != filetypes.XML:
            pages = incoming.content.split("\f") if incoming.content else [""]
            body = "\f".join(pages)
            session.add(VersionText(version_id=version.id, document_id=document.id, text=body, pages=len(pages),
                                    ocr_pages=0, languages="", digest=search_index.text_digest(body),
                                    created_at=clock.now()))
        session.add(PaperlessItem(origin=plan.origin, paperless_id=incoming.pid, document_id=document.id,
                                  state="done", reason="", inbox=incoming.inbox or plan.sort == "inbox",
                                  at=clock.now()))
        session.execute(
            PaperlessItem.__table__.delete().where(PaperlessItem.origin == plan.origin,
                                                   PaperlessItem.paperless_id == incoming.pid,
                                                   PaperlessItem.state == "skipped"))
        if archive is not None:
            target = staged_archive(document.id)
            target.unlink(missing_ok=True)
            shutil.move(str(archive), target)
            staged.append(target)

    title = incoming.title or filetypes.title_from(incoming.file_name or f"Paperless {incoming.pid}")
    try:
        documents.clean_title(title)
    except HTTPException:
        title = f"Paperless {incoming.pid}"
    try:
        document, _twin = receiving.accept(
            db, uid=owner, vault_id=vault_id, filename=incoming.file_name or title, path=path, kind=kind,
            sha256=saved.sha256, size=saved.size, source="paperless", title=title, also=fill,
            detail=({"from_archive": from_archive} if from_archive
                    else {"original_missing": True} if original_missing else None),
        )
    except Exception:
        for leftover in staged:
            leftover.unlink(missing_ok=True)
        raise
    return document.id


def _shares(session: Session, plan: Plan, found: Names, incoming: Incoming, document: Document, owner: int) -> None:
    """The people the document was shared with in Paperless, the same here, where they can be told; somebody in the
    vault already needs no share."""
    rights_of: dict[int, str] = {}
    if incoming.keeper is not None:
        rights_of[incoming.keeper] = "edit"
    for paperless_user in incoming.readers:
        person = _person(session, plan, found, paperless_user, owner=False)
        if person is not None:
            rights_of.setdefault(person, READ)
    for paperless_user in incoming.writers:
        person = _person(session, plan, found, paperless_user, owner=False)
        if person is not None:
            rights_of[person] = "edit"
    for person, right in rights_of.items():
        if person == owner or session.get(VaultMember, (document.vault_id, person)) is not None:
            continue
        session.add(Share(document_id=document.id, user_id=person, right=right, created_by=owner,
                          created_at=clock.now()))


# --- Reading a document that came from Paperless ----------------------------------------------------------------------


def given_text(db: Session, document: Document, version: Version, run: Any) -> Any:
    """For the reading of a document (``processing.recognize_text``): the text Paperless recognised instead of a new
    recognition, its searchable copy (moved to ``run.searchable``), and whether the document is filed or waits in the
    inbox. None when the document did not come from Paperless with its text (then it is read as any other)."""
    from .processing import Outcome

    given = db.get(VersionText, version.id)
    item = db.scalar(select(PaperlessItem).where(PaperlessItem.document_id == document.id).limit(1))
    if given is None or item is None:
        return None
    staged = staged_archive(document.id)
    searchable = False
    if staged.is_file():
        try:
            shutil.move(str(staged), run.searchable)
            searchable = True
        except OSError:
            searchable = False
    pages = given.text.split("\f") if given.text else [""]
    return Outcome(True, data={"texts": pages, "ocr_pages": 0, "languages": "", "searchable": searchable,
                               "file_as": INBOX if item.inbox else FILED})


def sweep_staged(db: Session) -> int:
    """Searchable copies nobody will take: their document is gone or was read, or they waited too long."""
    folder = get_settings().data_dir / "paperless"
    if not folder.is_dir():
        return 0
    removed = 0
    cutoff = time.time() - STAGED_DAYS * 86400
    # A copy is put there inside the transaction that makes its document: one without a document is left an hour.
    fresh = time.time() - 3600
    for path in folder.glob("*.pdf"):
        stem = path.stem
        document = db.get(Document, int(stem)) if stem.isdigit() else None
        try:
            changed = path.stat().st_mtime
        except OSError:
            continue
        gone = document is None and changed < fresh
        read = document is not None and document.status not in ("processing", "trash")
        if gone or read or changed < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    db.rollback()
    return removed


__all__ = ["Failure", "Skip", "check", "check_address", "given_text", "run_job", "save", "start", "stop", "view"]
