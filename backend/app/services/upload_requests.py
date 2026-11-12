"""Upload requests (U1): a person asks somebody without an account for documents, by an address ``/u/<token>``.

**What a request is.** A row of ``upload_requests``: whom the files are expected from (``name``, it stands at every
document that came through it), until when it works (at most as long as a link, ``sharing.rules``), how many files it
takes (``max_files``, 10 from the start, 50 at most). Each person makes requests for their own inbox only, at most
``MAX_OPEN`` open ones. The token (``upr_`` and 43 random characters) is found by its SHA-256 and kept sealed with the
server's secret, so that the person can copy the address again; the database alone tells nobody a token, and no log
line holds it (``services/logs.py`` masks ``upr_`` wherever it stands and the paths ``/u/<token>``).

**When it works.** The operator's switch is on (``upload_requests_allowed``, off from the start; off, every request
takes nothing at once), it was not revoked, its end has not passed (nor the longest a link may last now), not all its
files are there, the person is not blocked (blocking revokes them, deleting the account deletes them), and the public
address of the server is still the one it was made under (a request needs a public address; when the operator changes
it, the old addresses given out end). Everything else answers like an unknown token, and counts on a brake of its own
(``deps.request_failed``).

**What arrives.** Only ever the inbox of the person in their personal vault: the request names it, the caller names
nothing. Source ``request``, marked unknown like a mail nobody could be told from, "from <name>" with the document. A
rule may propose fields, never another vault (``sorting.propose``). The same file twice is taken twice (see
``take_file``): the answer never says whether the person has a file.

**Limits.** The files of a request (a slot is held atomically before the file is read: two uploads at once never pass
``max_files``), the size of a file as for every upload, files per request and per sender's address and hour (in
memory), files and bytes of the whole server per day (in the settings, like the mailbox's). What is refused costs
little: the token, the brakes and the slot come before a byte of the body is read, and a body larger than one file may
be is turned away by its declared length (``middleware.body_limit``).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from .. import clock
from ..errors import error
from ..models import Account, Document, IntakeItem, UploadRequest
from ..security import decrypt_secret, encrypt_secret
from . import changes, filetypes, receiving, settings_service, sharing

logger = logging.getLogger("nexpaper.requests")
#: The person of a request, inside the tests of a query that may itself be over `Account`.
_owner = aliased(Account)

TOKEN_PREFIX = "upr_"
NAME_MAX = 100
#: The files a request takes, from the start and at most.
DEFAULT_FILES = 10
MAX_FILES = 50
#: Open requests per person.
MAX_OPEN = 20
#: Files per request and hour, per sender's address and hour (every try counts, taken or not).
PER_REQUEST_HOUR = 20
PER_ADDRESS_HOUR = 30
#: Files and bytes of the whole server per day (UTC).
DAY_FILES = 500
DAY_BYTES = 2048 * 1024 * 1024
#: A request that ended stays in the person's list this long after its end (then it is only gone from sight).
LIST_DAYS = 30
#: At most one notice per request in this time.
TELL_EVERY = timedelta(hours=1)
#: Where a document from a request comes from (``documents.source``, ``intake_items.source``).
SOURCE = "request"
#: The path the person's notice opens.
INBOX_PATH = "/eingang?source=request"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sealed_with(token_hash: str) -> str:
    """What the sealed token is bound to: its own row (a sealed value moved to another row does not open)."""
    return "upload-request:" + token_hash


@dataclass(frozen=True)
class Rules:
    allowed: bool
    max_days: int
    #: The public address of the server, without which no request is made and none works.
    address: str


def rules(db: Session) -> Rules:
    return Rules(bool(settings_service.get(db, "upload_requests_allowed")), sharing.rules(db).max_days,
                 settings_service.public_url(db))


def live(now: datetime, current: Rules) -> ColumnElement[bool]:
    """A request that takes files right now (the switch aside, see ``Rules.allowed``): not revoked, before its end and
    the longest a link may last now, made under the public address the server has now, all its files not there yet, its
    person not blocked."""
    return and_(
        UploadRequest.revoked_at.is_(None), UploadRequest.until > now,
        UploadRequest.created_at > now - timedelta(days=current.max_days),
        UploadRequest.address == current.address, UploadRequest.address != "",
        UploadRequest.received < UploadRequest.max_files,
        exists().where(_owner.id == UploadRequest.user_id, _owner.blocked_at.is_(None)),
    )


def ends(row: UploadRequest, max_days: int) -> datetime:
    return min(row.until, row.created_at + timedelta(days=max_days))


def status_of(row: UploadRequest, current: Rules) -> str:
    """``active``; ``revoked``; ``off`` (the operator's switch); ``expired``; ``used`` (all files are there);
    ``ended`` (the public address changed since it was made)."""
    if row.revoked_at is not None:
        return "revoked"
    if not current.allowed:
        return "off"
    if ends(row, current.max_days) <= clock.now():
        return "expired"
    if row.received >= row.max_files:
        return "used"
    if not row.address or row.address != current.address:
        return "ended"
    return "active"


# --- The person's side ------------------------------------------------------------------------------------------------


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if (not cleaned or len(cleaned) > NAME_MAX or any(ord(c) < 32 or ord(c) == 127 for c in cleaned)
            or any(ord(c) in filetypes.BIDI_CONTROLS for c in cleaned)):
        raise error("invalid_name", f"Say whom the files are from (1 to {NAME_MAX} characters).", 422)
    return cleaned


def create(db: Session, uid: int, name: str, days: int, max_files: int) -> tuple[UploadRequest, str]:
    cleaned = _clean_name(name)
    changes.write_lock(db)
    current = rules(db)
    if not current.allowed:
        raise error("requests_off", "The operator has not switched upload requests on.", 409)
    if not current.address:
        raise error("public_url_missing", "Upload requests need the public address of the server. The operator sets "
                    "it under Settings.", 409)
    if not 1 <= days <= current.max_days:
        raise error("invalid_days", f"A request lasts 1 to {current.max_days} days.", 422, max_days=current.max_days)
    if not 1 <= max_files <= MAX_FILES:
        raise error("invalid_files", f"A request takes 1 to {MAX_FILES} files.", 422, max=MAX_FILES)
    now = clock.now()
    open_ones = db.scalar(select(func.count()).select_from(UploadRequest).where(
        UploadRequest.user_id == uid, live(now, current))) or 0
    if open_ones >= MAX_OPEN:
        raise error("too_many_requests", f"At most {MAX_OPEN} open upload requests.", 409, max=MAX_OPEN)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    hashed = digest(token)
    sealed = encrypt_secret(token, _sealed_with(hashed))
    row = UploadRequest(user_id=uid, name=cleaned, token_hash=hashed, token_enc=sealed,
                        address=current.address, until=now + timedelta(days=days), max_files=max_files, received=0,
                        created_at=now)
    db.add(row)
    db.commit()
    logger.info("Upload request made request_id=%s days=%s files=%s", row.id, days, max_files)
    return row, token


def mine(db: Session, uid: int) -> list[UploadRequest]:
    """The person's own requests that are not revoked, newest first; one that ended stays ``LIST_DAYS`` in sight."""
    current = rules(db)
    since = clock.now() - timedelta(days=LIST_DAYS)
    rows = db.scalars(select(UploadRequest).where(UploadRequest.user_id == uid, UploadRequest.revoked_at.is_(None))
                      .order_by(UploadRequest.id.desc())).all()
    return [row for row in rows if ends(row, current.max_days) > since]


def _own(db: Session, uid: int, request_id: int) -> UploadRequest:
    """The person's own request; anybody else's, the operator's look included, is 404 as for one that does not exist."""
    row = db.get(UploadRequest, request_id)
    if row is None or row.user_id != uid or row.revoked_at is not None:
        raise error("not_found", "Not found.", 404)
    return row


def token_of(db: Session, uid: int, request_id: int) -> str:
    """The token again, for the person who made it, while it works."""
    row = _own(db, uid, request_id)
    if status_of(row, rules(db)) != "active":
        raise error("request_ended", "This request takes nothing any more. Make a new one.", 409)
    token = decrypt_secret(row.token_enc, _sealed_with(row.token_hash))
    if not token or digest(token) != row.token_hash:
        raise error("request_unreadable", "This address cannot be shown again. Make a new request.", 409)
    return token


def revoke(db: Session, uid: int, request_id: int) -> None:
    changes.write_lock(db)
    row = _own(db, uid, request_id)
    row.revoked_at = clock.now()
    db.commit()
    logger.info("Upload request revoked request_id=%s", row.id)


def end_for(db: Session, uid: int) -> int:
    """The person was blocked: their requests end for good (in the caller's transaction). Returns how many."""
    result = db.execute(update(UploadRequest).where(UploadRequest.user_id == uid, UploadRequest.revoked_at.is_(None))
                        .values(revoked_at=clock.now()))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class Overview:
    open_requests: int
    people: int


def overview(db: Session) -> Overview:
    """For the operator: how many requests take files and of how many people; never an address or a name."""
    current = rules(db)
    if not current.allowed:
        return Overview(0, 0)
    rows = db.execute(select(UploadRequest.user_id).where(live(clock.now(), current))).all()
    return Overview(len(rows), len({r[0] for r in rows}))


# --- The page behind the address ----------------------------------------------------------------------------------


def check(db: Session, token: str) -> tuple[UploadRequest, Account] | None:
    """The request and its person for a token that takes files right now; None for anything else."""
    if not token.startswith(TOKEN_PREFIX) or len(token) > 100:
        return None
    current = rules(db)
    if not current.allowed:
        return None
    row = db.execute(select(UploadRequest, Account).join(Account, Account.id == UploadRequest.user_id)
                     .where(UploadRequest.token_hash == digest(token), live(clock.now(), current))).first()
    return None if row is None else (row[0], row[1])


def hold(db: Session, request_id: int) -> bool:
    """A slot for one file, in one statement: of many uploads at once, only as many as files are left pass. False when
    the request no longer takes files."""
    current = rules(db)
    if not current.allowed:
        return False
    now = clock.now()
    taken = db.execute(update(UploadRequest).where(UploadRequest.id == request_id, live(now, current))
                       .values(received=UploadRequest.received + 1, last_used_at=now)).rowcount
    db.commit()
    return taken == 1


def give_back(db: Session, request_id: int) -> None:
    """The slot of a file that was not taken."""
    db.execute(update(UploadRequest).where(UploadRequest.id == request_id, UploadRequest.received > 0)
               .values(received=UploadRequest.received - 1))
    db.commit()


def still_open(db: Session, request_id: int) -> UploadRequest | None:
    """After the file arrived: the request (holding the slot) still works (not revoked meanwhile, the switch still on).
    The slot itself counts, so the test is the one of ``live`` without the number of files."""
    current = rules(db)
    if not current.allowed:
        return None
    now = clock.now()
    return db.scalar(select(UploadRequest).where(
        UploadRequest.id == request_id, UploadRequest.revoked_at.is_(None), UploadRequest.until > now,
        UploadRequest.created_at > now - timedelta(days=current.max_days), UploadRequest.address == current.address,
        exists().where(_owner.id == UploadRequest.user_id, _owner.blocked_at.is_(None))))


def take_file(db: Session, row: UploadRequest, *, filename: str, path: Path, kind: str, sha256: str,
              size: int) -> Document:
    """A file that arrived becomes a document of the person, in the inbox of their personal vault, never anywhere else.

    The same file again is taken again, as a document of its own: the person sees in the inbox that it looks like one
    they have and deletes it. Passing over it would answer the same, but the request would then count differently or
    the answer would wait differently, and either tells the sender whether the person has the file. A duplicate costs a
    slot of the request like any file."""
    vault_id = receiving.personal_vault(db, row.user_id)
    cleaned = filetypes.file_name(filename) if filename else ""

    def note(session: Session, document: Document) -> None:
        session.add(IntakeItem(document_id=document.id, source=SOURCE, key=f"{row.id}:{secrets.token_hex(8)}",
                               state="done", sha256=sha256, size=size, unknown=True,
                               detail={"from": row.name}, at=clock.now()))

    document, _twin = receiving.accept(
        db, uid=row.user_id, vault_id=vault_id, filename=cleaned or "document", path=path, kind=kind, sha256=sha256,
        size=size, source=SOURCE, also=note, detail={"from": row.name})
    logger.info("Upload request took a file request_id=%s document_id=%s bytes=%s", row.id, document.id, size)
    return document


def tell_if_due(db: Session, request_id: int) -> None:
    """At most one notice per request and hour: the name of the request and how many files came through it so far, no
    file name, nothing of the contents. Claimed in one statement, so two files at once tell once."""
    from . import tell

    now = clock.now()
    claimed = db.execute(update(UploadRequest).where(
        UploadRequest.id == request_id,
        or_(UploadRequest.told_at.is_(None), UploadRequest.told_at <= now - TELL_EVERY)).values(told_at=now)).rowcount
    db.commit()
    if claimed != 1:
        return
    row = db.get(UploadRequest, request_id)
    if row is None:
        return
    count, name = row.received, row.name
    tell.person(row.user_id, tell.Notice(
        texts={
            "de": ("Neue Dateien im Eingang", f"Über die Bitte „{name}“ sind bis jetzt {count} Dateien angekommen."
                   if count != 1 else f"Über die Bitte „{name}“ ist eine Datei angekommen."),
            "en": ("New files in the inbox", f"{count} files have arrived so far through the request “{name}”."
                   if count != 1 else f"A file has arrived through the request “{name}”."),
        },
        url=INBOX_PATH, tag=f"upload-request-{request_id}",
        mail_subject="Files arrived through an upload request",
        mail_body=f"Files arrived through your upload request \"{name}\": {count} so far.\n\n"
                  "They wait in your inbox: {where}\n",
    ))


# --- Limits per hour (in memory) and per day (in the settings) --------------------------------------------------------

_lock = threading.Lock()
_seen: dict[tuple[str, str], deque[float]] = {}


def hour_room(request_id: int, address: str) -> bool:
    """One more try for this request and this sender in the hour, or False (then neither counts). Counted before the
    file is read, whatever comes of it: a flood of refused files is a flood all the same."""
    moment = clock.monotonic()
    wanted = ((("request", str(request_id)), PER_REQUEST_HOUR), (("address", address), PER_ADDRESS_HOUR))
    with _lock:
        for key, limit in wanted:
            seen = _seen.setdefault(key, deque())
            while seen and moment - seen[0] > 3600:
                seen.popleft()
            if len(seen) >= limit:
                return False
        for key, _limit in wanted:
            _seen[key].append(moment)
        return True


def _budget(db: Session) -> dict[str, Any]:
    stored = settings_service.get(db, "upload_request_budget")
    today = clock.now().date().isoformat()
    if not isinstance(stored, dict) or stored.get("day") != today:
        return {"day": today, "files": 0, "bytes": 0}
    return {"day": today, "files": int(stored.get("files") or 0), "bytes": int(stored.get("bytes") or 0)}


def day_reserve(db: Session, size: int) -> bool:
    """Room in the day of the whole server for one more file of at most ``size`` bytes (the declared length of the
    request): reserved now, settled with ``day_settle`` once the true size is known."""
    with _lock:
        budget = _budget(db)
        if budget["files"] + 1 > DAY_FILES or budget["bytes"] + size > DAY_BYTES:
            return False
        budget["files"] += 1
        budget["bytes"] += size
        settings_service.save(db, {"upload_request_budget": budget})
        return True


def day_settle(db: Session, reserved: int, used: int, *, taken: bool) -> None:
    """What was reserved and not used goes back; a file that was not taken gives its file back too."""
    with _lock:
        budget = _budget(db)
        budget["bytes"] = max(0, budget["bytes"] - max(0, reserved - used))
        if not taken:
            budget["files"] = max(0, budget["files"] - 1)
        settings_service.save(db, {"upload_request_budget": budget})


def forget() -> None:
    """For the tests."""
    with _lock:
        _seen.clear()
