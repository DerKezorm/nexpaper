"""The shapes the routes for vaults and documents answer with, shared by them."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, model_serializer

from ..models import Account, Kind
from ..services import documents as documents_service
from ..services.documents import Row


class PersonRef(BaseModel):
    id: int
    name: str
    display_name: str


class NameRef(BaseModel):
    id: int
    name: str


class KindOut(BaseModel):
    id: int
    key: str
    name: str
    hue: int
    position: int
    #: The vault this kind belongs to; empty for the kinds of the whole server.
    vault_id: int | None = None
    #: How many years its documents are kept (`keep_until` is worked out from it); empty: no keeping time.
    keep_years: int | None = None
    #: Its documents whose keeping time is over go to the trash by themselves, once a day (off from the start).
    auto_trash: bool = False


class NoticeOut(BaseModel):
    n: int
    unit: Literal["weeks", "months"]


class DoneOut(BaseModel):
    at: datetime
    #: Who marked it done; empty when that account is gone.
    by: PersonRef | None


class DateOut(BaseModel):
    kind: str
    date: Date
    #: A contract's notice period, and how many months it renews by when nobody cancels (empty: it just ends).
    notice: NoticeOut | None = None
    renew_months: int | None = None
    #: The last day to cancel, worked out from ``date`` and ``notice`` (to the day of the calendar).
    last_to_cancel: Date | None = None
    #: Paid, cancelled or claimed: for everybody, with who and when.
    done: DoneOut | None = None
    #: The end the contract last renewed from by itself (the history has when).
    renewed_from: Date | None = None
    #: "Later" of the caller on this deadline, while it lasts.
    snoozed_until: Date | None = None
    #: Only on `keep_until` (left out for the other kinds): `true` set by a person; `false` worked out from the kind's
    #: keeping time, and worked out again when the kind, the date or the vault changes.
    manual: bool | None = None

    # No return annotation: pydantic would take it for the schema of the answer.
    @model_serializer(mode="wrap")
    def _manual_only_where_it_means_something(self, handler: Any):
        data = handler(self)
        if self.manual is None:
            data.pop("manual", None)
        return data


class DuplicateOut(BaseModel):
    """A document the caller may see that this one repeats (``same``: the very same file) or looks like (``similar``).
    """

    document_id: int
    title: str
    kind: Literal["same", "similar"]


class DocumentOut(BaseModel):
    id: int
    vault_id: int
    owner: PersonRef | None
    title: str
    sender: NameRef | None
    kind: KindOut | None
    date: Date | None
    #: In cents.
    amount: int | None
    currency: str
    tags: list[str]
    dates: list[DateOut]
    pages: int
    source: str
    status: Literal["processing", "inbox", "filed", "trash"]
    added_at: datetime
    trashed_at: datetime | None
    #: When the trash empties this document for good.
    trash_ends_at: datetime | None
    change_seq: int
    current_version: int
    #: What the caller may do with it: ``read``, ``edit`` or ``manage``.
    my_right: Literal["read", "edit", "manage"]
    #: The caller sees it only because it was shared with them.
    via_share: bool
    can_share: bool
    notes: int
    #: Why reading the file failed (``encrypted``, ``broken``, ``too_many_pages``, ``too_large``, ``timeout``,
    #: ``failed``); empty when all is well. The document waits in the inbox then, and ``POST .../retry`` tries again.
    process_error: str
    duplicate: DuplicateOut | None
    #: A split at blank separator pages is proposed (``GET .../separators`` says where).
    split_suggested: bool = False
    #: Where the proposals in the inbox came from, per field (``title``, ``sender``, ``kind``, ``date``, ``amount``,
    #: ``vault``, ``tags``, ``dates``): ``rule``, ``ai``, ``einvoice``, ``text``, ``default`` or ``last_time``, and
    #: ``person`` for a field a person changed since. Empty when nothing was proposed.
    suggest: dict[str, str] = {}
    #: For a caller who may share it (``can_share``): how many people it is shared with and how many of its links to the
    #: outside work now; empty for everybody else.
    share_count: int | None = None
    link_count: int | None = None
    #: The format of the e-invoice it carries (``ZUGFeRD (EN 16931)``, ``XRechnung (UBL)`` ...); empty when none.
    #: ``GET /documents/{id}/einvoice`` has its data.
    einvoice: str = ""
    #: The check of the files found a problem: ``missing`` (a file is gone from the disk) or ``changed`` (a file does
    #: not have its checksum any more); empty when all is well (``services/filecheck.py``).
    files_state: Literal["", "missing", "changed"] = ""
    #: The nightly task will put it in the trash by itself (or will, once it is filed from the inbox): its kind has the
    #: switch on, its `keep_until` is over for the caller, and it was not put there before (one a person restored is
    #: left alone). The same condition as the task's, in one place.
    auto_trash_due: bool = False
    #: It is in the trash because the task put it there, not a person.
    auto_trashed: bool = False


def _suggest(value: object) -> dict[str, str]:
    """Only names and short words: what the database holds is shown, never trusted to be of the right shape."""
    if not isinstance(value, dict):
        return {}
    return {str(k)[:20]: str(v)[:20] for k, v in list(value.items())[:20] if isinstance(k, str) and isinstance(v, str)}


def person(account: Account | None) -> PersonRef | None:
    return None if account is None else PersonRef(id=account.id, name=account.name, display_name=account.display_name)


def kind_out(kind: Kind | None) -> KindOut | None:
    if kind is None:
        return None
    return KindOut(id=kind.id, key=kind.key, name=kind.name, hue=kind.hue, position=kind.position,
                   vault_id=kind.vault_id, keep_years=kind.keep_years,
                   auto_trash=bool(kind.auto_trash))


def dates_out(row: Row) -> list[DateOut]:
    if not row.date_rows:
        return [DateOut(kind=kind, date=day) for kind, day in row.dates]
    return [DateOut(
        kind=r.kind, date=r.date, manual=r.manual if r.kind == "keep_until" else None,
        notice=NoticeOut(n=r.notice_n, unit=r.notice_unit) if r.notice_n and r.notice_unit else None,  # type: ignore[arg-type]
        renew_months=r.renew_months, last_to_cancel=r.notice_date,
        done=DoneOut(at=r.done_at, by=person(row.done_by.get(r.done_by)) if r.done_by else None) if r.done_at else None,
        renewed_from=r.renewed_from, snoozed_until=row.snoozes.get(r.id),
    ) for r in row.date_rows]


def document_out(row: Row) -> DocumentOut:
    document = row.document
    ends = document.trashed_at + timedelta(days=documents_service.TRASH_DAYS) if document.trashed_at else None
    return DocumentOut(
        id=document.id, vault_id=document.vault_id, owner=person(row.owner), title=document.title,
        sender=NameRef(id=row.sender.id, name=row.sender.name) if row.sender else None, kind=kind_out(row.kind),
        date=document.date, amount=document.amount, currency=document.currency, tags=row.tags,
        dates=dates_out(row), pages=document.pages, source=document.source,
        status=document.status,  # type: ignore[arg-type]
        added_at=document.added_at, trashed_at=document.trashed_at, trash_ends_at=ends, change_seq=document.change_seq,
        current_version=document.current_version, my_right=row.right,  # type: ignore[arg-type]
        via_share=row.via_share, can_share=row.can_share, notes=row.notes, process_error=document.process_error,
        duplicate=DuplicateOut(document_id=row.duplicate.id, title=row.duplicate.title,
                               kind=document.duplicate_kind) if row.duplicate and document.duplicate_kind else None,  # type: ignore[arg-type]
        split_suggested=row.split,
        suggest=_suggest(document.suggest), share_count=row.share_count, link_count=row.link_count,
        einvoice=row.einvoice, files_state=document.files_state,  # type: ignore[arg-type]
        auto_trash_due=row.auto_trash_due, auto_trashed=row.auto_trashed,
    )
