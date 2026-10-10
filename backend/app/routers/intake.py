"""Inputs: the intake folder and the mailbox for documents (Settings, Inputs; operator only, from a browser), the
addresses a person forwards documents from (My account, Upload), and where a document came from.

The mailbox password is written sealed and never read back: the answer only says whether one is set.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt

from ..deps import Account as Caller
from ..deps import BrowserAccount, DbSession, OperatorAccount, Reader, address_failed, address_guard, too_many
from ..errors import error
from ..models import MANAGE, Account
from ..security import brake, encrypt_secret
from ..services import accounts, intake, intake_folder, intake_mail, mail_senders, mailer, rights, settings_service

logger = logging.getLogger("nexpaper.intake")

router = APIRouter(prefix="/api/v1", tags=["inputs"])

Token = Annotated[str, Path(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


# --- The operator's settings -----------------------------------------------------------------------------------------


class FolderPerson(BaseModel):
    name: str
    display_name: str
    path: str
    #: ``folder_readonly`` when nexpaper may not move or remove files in this person's subfolder; else empty.
    problem: str = ""


class FolderOut(BaseModel):
    on: bool
    #: As set; empty means the default.
    path: str
    #: The folder used.
    used: str
    #: Why the folder cannot be used (``folder_invalid``, ``folder_forbidden``, ``folder_missing``); empty when it can.
    problem: str
    people: list[FolderPerson]
    #: Who gets what lies in the folder itself and in subfolders nobody has (marked unknown).
    operator: str


class MailLast(BaseModel):
    at: datetime | None = None
    ok: bool = True
    code: str = ""
    mails: int = 0
    files: int = 0
    unknown: int = 0
    #: Mails skipped because taking them apart costs too much, flagged in the mailbox (not taken whole), waiting for
    #: the next day (the daily amount of their person).
    skipped: int = 0
    flagged: int = 0
    deferred: int = 0


class MailOut(BaseModel):
    on: bool
    host: str
    port: int
    security: Literal["tls", "starttls", "none"]
    user: str
    password_set: bool
    #: The address of the mailbox, for ``name+<account>@``.
    address: str
    folder: str
    after: Literal["read", "move", "delete"]
    #: The mail server may lie in the own network.
    private: bool
    #: Mails nobody can be told from stay in the mailbox (instead of coming into the operator's inbox).
    drop_unknown: bool
    #: The server whose ``Authentication-Results`` count; empty: the domain of the mailbox's address.
    auth_server: str
    last: MailLast


class IntakeOut(BaseModel):
    folder: FolderOut
    mail: MailOut


class IntakeIn(BaseModel):
    folder_on: StrictBool | None = None
    folder_path: str | None = Field(default=None, max_length=400)
    mail_on: StrictBool | None = None
    mail_host: str | None = Field(default=None, max_length=255)
    mail_port: StrictInt | None = Field(default=None, ge=1, le=65535)
    mail_security: Literal["tls", "starttls", "none"] | None = None
    mail_user: str | None = Field(default=None, max_length=255)
    #: Empty removes the password; left out keeps it (unless server or port change).
    mail_password: str | None = Field(default=None, max_length=500)
    mail_address: str | None = Field(default=None, max_length=255)
    mail_folder: str | None = Field(default=None, max_length=200)
    mail_after: Literal["read", "move", "delete"] | None = None
    mail_private: StrictBool | None = None
    mail_drop_unknown: StrictBool | None = None
    mail_auth_server: str | None = Field(default=None, max_length=255)


def _view(db: DbSession) -> IntakeOut:
    values = settings_service.get_all(db)
    used, problem = intake_folder.describe(str(values["folder_path"] or ""))
    people = [
        FolderPerson(name=row.name, display_name=row.display_name or row.name, path=f"{used.rstrip('/')}/{row.name}/",
                     problem=intake_folder.person_problem(used, row.name)
                     if values["folder_on"] and not problem else "")
        for row in db.query(Account).filter(Account.blocked_at.is_(None)).order_by(Account.name)
        if intake_folder.folder_name(row.name)
    ]
    operator_id = intake.operator_id(db)
    operator = db.get(Account, operator_id) if operator_id is not None else None
    last = values["mail_last"] if isinstance(values["mail_last"], dict) else {}
    return IntakeOut(
        folder=FolderOut(on=bool(values["folder_on"]), path=str(values["folder_path"] or ""), used=used,
                         problem=problem, people=people,
                         operator=(operator.display_name or operator.name) if operator else ""),
        mail=MailOut(
            on=bool(values["mail_on"]), host=str(values["mail_host"] or ""), port=int(values["mail_port"] or 993),
            security=values["mail_security"] if values["mail_security"] in intake_mail.SECURITIES else "tls",
            user=str(values["mail_user"] or ""), password_set=bool(values["mail_password_enc"]),
            address=str(values["mail_address"] or ""), folder=str(values["mail_folder"] or "INBOX"),
            after=values["mail_after"] if values["mail_after"] in intake_mail.AFTER else "read",
            private=bool(values["mail_private"]), drop_unknown=bool(values["mail_drop_unknown"]),
            auth_server=str(values["mail_auth_server"] or ""),
            last=MailLast(**{key: value for key, value in last.items() if key in MailLast.model_fields}),
        ),
    )


def _mail_problem(exc: intake_mail.MailFailure) -> Exception:
    return error(exc.code, str(exc), exc.status)


@router.get("/settings/intake", response_model=IntakeOut, summary="The intake folder and the mailbox for documents")
def read_intake(_operator: OperatorAccount, db: DbSession) -> IntakeOut:
    return _view(db)


@router.put("/settings/intake", response_model=IntakeOut, summary="Change the intake folder or the mailbox")
def save_intake(payload: IntakeIn, operator: OperatorAccount, db: DbSession) -> IntakeOut:
    sent = payload.model_dump(exclude_unset=True)
    current = settings_service.get_all(db)
    changes: dict[str, Any] = {}
    for key, value in sent.items():
        if value is None:
            continue
        if key == "folder_path":
            value = value.strip()
            try:
                path = intake_folder.check_root(value)
            except intake_folder.FolderProblem as exc:
                raise error(exc.code, "This cannot be the intake folder.", 422, fields=[key]) from exc
            if intake_folder.forbidden(path):
                raise error("folder_forbidden", "nexpaper must not take files from this folder.", 422, fields=[key])
        elif key == "mail_host":
            value = value.strip()
            if value:
                try:
                    value = intake_mail.check_host(value)
                except intake_mail.MailFailure as exc:
                    raise error(exc.code, str(exc), 422, fields=[key]) from exc
        elif key == "mail_auth_server":
            value = value.strip()
            if value:
                try:
                    value = intake_mail.check_host(value)
                except intake_mail.MailFailure as exc:
                    raise error("mail_host_invalid", str(exc), 422, fields=[key]) from exc
        elif key == "mail_folder":
            try:
                value = intake_mail.check_folder(value)
            except intake_mail.MailFailure as exc:
                raise error(exc.code, str(exc), 422, fields=[key]) from exc
        elif key == "mail_address":
            value = value.strip()
            if value and not accounts.EMAIL_PATTERN.match(value):
                raise error("invalid_email", "This is not a mail address.", 422, fields=[key])
        elif key == "mail_user":
            value = value.strip()
        elif key == "mail_password":
            changes["mail_password_enc"] = encrypt_secret(value, intake_mail.PASSWORD_CONTEXT) if value else ""
            continue
        changes[key] = value
    merged = {**current, **changes}
    if merged["mail_security"] == "none" and merged["mail_host"] and merged["mail_host"] not in intake_mail.LOCAL_HOSTS:
        raise error("mail_plain_not_local", intake_mail.MESSAGES["mail_plain_not_local"], 422, fields=["mail_security"])
    moved = merged["mail_host"] != current["mail_host"] or int(merged["mail_port"]) != int(current["mail_port"])
    if moved and "mail_password_enc" not in changes and current["mail_password_enc"]:
        # The stored password goes only to the server it was given for.
        changes["mail_password_enc"] = ""
    if merged["folder_on"]:
        try:
            intake_folder.usable_root(str(merged["folder_path"] or ""), make=True)
        except intake_folder.FolderProblem as exc:
            raise error(exc.code, "This cannot be the intake folder.", 422, fields=["folder_path"]) from exc
    settings_service.save(db, changes)
    if merged["folder_on"]:
        root = intake_folder.usable_root(str(merged["folder_path"] or ""), make=True)
        names = [row.name for row in db.query(Account).filter(Account.blocked_at.is_(None))]
        intake_folder.prepare(sorted(names), root)
        # Whether files may be moved and removed there is looked at now; the card says it when not.
        intake_folder.writable(root, fresh=True)
    logger.info("Inputs changed keys=%s by=%s", ",".join(sorted(changes)), operator.name)
    return _view(db)


class ProbeOut(BaseModel):
    #: Mails that would be fetched next.
    mails: int
    #: What "afterwards" really does on this server: deleting one mail needs UIDPLUS, moving MOVE or UIDPLUS; without
    #: them nexpaper moves or marks read instead.
    after: Literal["read", "move", "delete"]


@router.post("/settings/intake/mail/test", response_model=ProbeOut,
             summary="Connect to the mailbox, sign in and count the mails that are new (nothing is taken)")
def test_mail(_operator: OperatorAccount) -> ProbeOut:
    try:
        found = intake_mail.probe()
        return ProbeOut(mails=found.mails, after=found.after)
    except intake_mail.MailFailure as exc:
        raise _mail_problem(exc) from exc


class FetchOut(BaseModel):
    #: Mails taken, documents made, mails that went to the operator as unknown, parts or mails passed over, and whether
    #: more mails wait for the next run; mails skipped (too costly to take apart), flagged (not taken whole), left
    #: for the next day, left in the mailbox (unknown, when the operator chose so); what "afterwards" really did.
    mails: int
    files: int
    unknown: int
    passed: int
    more: bool
    skipped: int
    flagged: int
    deferred: int
    dropped: int
    after: str


@router.post("/settings/intake/mail/fetch", response_model=FetchOut, summary="Fetch the mailbox now")
def fetch_mail(_operator: OperatorAccount) -> FetchOut:
    try:
        done = intake_mail.fetch()
    except intake_mail.MailFailure as exc:
        raise _mail_problem(exc) from exc
    return FetchOut(mails=done.mails, files=done.files, unknown=done.unknown, passed=done.passed, more=done.more,
                    skipped=done.skipped, flagged=done.flagged, deferred=done.deferred, dropped=done.dropped,
                    after=done.after)


# --- My account: where to send documents, and the addresses forwarded from --------------------------------------------


class SenderOut(BaseModel):
    id: int
    address: str
    confirmed: bool
    #: While the link waits: when it runs out.
    until: datetime | None


class MyIntakeOut(BaseModel):
    #: The mailbox is switched on; its address, and the own form ``name+<account>@`` of it.
    mail_on: bool
    mail_address: str
    plus_address: str
    #: The confirmed address of the account counts as well.
    account_address: str
    senders: list[SenderOut]
    #: The intake folder is switched on; the own subfolder.
    folder_on: bool
    folder: str
    #: A link can be mailed (a mail server and the public address are set up).
    can_confirm: bool


def _sender_out(row: Any) -> SenderOut:
    return SenderOut(id=row.id, address=row.address, confirmed=row.confirmed_at is not None,
                     until=row.expires_at if row.confirmed_at is None else None)


def _plus(address: str, name: str) -> str:
    local, at, domain = address.rpartition("@")
    return f"{local}+{name}@{domain}" if at and local else ""


@router.get("/me/intake", response_model=MyIntakeOut,
            summary="Where the own documents can be sent: the mailbox, the addresses forwarded from, the own subfolder")
def my_intake(account: Caller, db: DbSession) -> MyIntakeOut:
    values = settings_service.get_all(db)
    mail_on = bool(values["mail_on"])
    address = str(values["mail_address"] or "") if mail_on else ""
    folder_on = bool(values["folder_on"])
    used, _problem = intake_folder.describe(str(values["folder_path"] or ""))
    row = db.get(Account, account.id)
    assert row is not None
    own = row.email if row.email and row.email_confirmed_at is not None else ""
    return MyIntakeOut(
        mail_on=mail_on, mail_address=address, plus_address=_plus(address, row.name) if address else "",
        account_address=own, senders=[_sender_out(s) for s in mail_senders.of_account(db, row.id)],
        folder_on=folder_on,
        folder=f"{used.rstrip('/')}/{row.name}/" if folder_on and intake_folder.folder_name(row.name) else "",
        can_confirm=mail_senders.available(db),
    )


class SenderIn(BaseModel):
    address: str = Field(max_length=255)


@router.post("/me/mail-senders", response_model=SenderOut, status_code=201,
             summary="Add an address the own documents are forwarded from; it counts once its link is opened")
def add_sender(payload: SenderIn, account: BrowserAccount, db: DbSession) -> SenderOut:
    address = payload.address.strip()
    if not accounts.EMAIL_PATTERN.match(address):
        raise error("invalid_email", "This is not a mail address.", 422, fields=["address"])
    row = db.get(Account, account.id)
    assert row is not None
    key = mail_senders.key_of(address)
    if row.email_confirmed_at is not None and mail_senders.key_of(row.email) == key:
        raise error("sender_is_account", "This is the address of your account; it counts already.", 409)
    mine = mail_senders.of_account(db, row.id)
    if any(s.address_key == key and s.confirmed_at is not None for s in mine):
        raise error("sender_exists", "This address counts already.", 409)
    if not any(s.address_key == key for s in mine) and len(mine) >= mail_senders.MAX_PER_ACCOUNT:
        raise error("too_many_senders", f"At most {mail_senders.MAX_PER_ACCOUNT} addresses.", 409)
    if not mail_senders.available(db):
        raise error("mail_off", "No mail server is set up, so the link cannot be sent.", 409)
    brake_key = f"sender-link:{row.id}"
    wait = brake.wait_seconds(brake_key, mail_senders.PER_ACCOUNT)
    if wait:
        raise too_many(wait)
    brake.failed(brake_key, mail_senders.PER_ACCOUNT)
    made, token = mail_senders.start(db, row, address)
    try:
        mailer.send_sender_confirm(
            db, address, mail_senders.link_to(db, token), name=row.name, hours=mail_senders.HOURS,
            mailbox=str(settings_service.get(db, "mail_address") or ""),
        )
    except mailer.MailError as exc:
        db.delete(made)
        db.commit()
        raise error(exc.code, str(exc), 502) from exc
    return _sender_out(made)


@router.delete("/me/mail-senders/{sender_id}", status_code=204, summary="Remove an address forwarded from")
def remove_sender(sender_id: int, account: BrowserAccount, db: DbSession) -> None:
    from ..models import MailSender

    row = db.get(MailSender, sender_id)
    if row is None or row.user_id != account.id:
        raise error("not_found", "Not found.", 404)
    db.delete(row)
    db.commit()
    logger.info("Sender address removed name=%s", account.name)


def _valid(db: DbSession, request: Request, token: str) -> tuple[Any, Account]:
    address_guard(request)
    found = mail_senders.find(db, token)
    if found is None:
        address_failed(request)
        raise error("sender_link_invalid", "This link is not valid any more.", 404)
    return found


@router.get("/mail-senders/confirm/{token}", summary="Whether a link that confirms a sender address holds (no sign-in)")
def sender_state(token: Token, request: Request, db: DbSession) -> dict[str, str]:
    row, account = _valid(db, request, token)
    return {"name": account.name, "address": row.address}


@router.post("/mail-senders/confirm/{token}", summary="Confirm a sender address (no sign-in needed)")
def sender_confirm(token: Token, request: Request, db: DbSession) -> dict[str, str]:
    _valid(db, request, token)
    done = mail_senders.confirm(db, token)
    if done is None:
        address_failed(request)
        raise error("sender_link_invalid", "This link is not valid any more.", 404)
    row, account = done
    return {"name": account.name, "address": row.address}


# --- Where a document came from ---------------------------------------------------------------------------------------


class OriginOut(BaseModel):
    #: ``upload``, ``camera``, ``mail``, ``folder``, ``share``, ``paperless`` or ``api``.
    source: str
    #: It went to the operator because nobody could be told from it.
    unknown: bool
    #: For the owner of the document and the managers of its vault: the sender's address and the subject of the mail,
    #: the subfolder and the name of the file.
    sender: str = ""
    subject: str = ""
    folder: str = ""
    file: str = ""
    at: datetime | None = None


@router.get("/documents/{document_id}/origin", response_model=OriginOut, summary="Where a document came from")
def origin(document_id: int, account: Reader, db: DbSession) -> OriginOut:
    access = rights.require_document(db, account.id, document_id)
    document = access.document
    item = intake.origin(db, document.id)
    if item is None:
        return OriginOut(source=document.source, unknown=False)
    out = OriginOut(source=document.source, unknown=bool(item.unknown), at=item.at)
    if document.owner_id == account.id or access.vault == MANAGE:
        detail = item.detail if isinstance(item.detail, dict) else {}
        out.sender = str(detail.get("from") or "")
        out.subject = str(detail.get("subject") or "")
        out.folder = str(detail.get("folder") or "")
        out.file = str(detail.get("file") or "")
    return out
