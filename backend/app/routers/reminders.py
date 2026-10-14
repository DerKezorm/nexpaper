"""Reminders (``services/reminders.py``): how the own account is reminded of deadlines, and a test message.

Only for the own account, like everything under ``/me``: a signed-in browser or a device (a native app sets its owner's
reminders too); a program with an API key is turned away, it has no account of its own to set. Nothing here names a
vault the caller is not a member of: muting one they may not change things in answers like one that does not exist.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ..deps import Account as Caller
from ..deps import DbSession
from ..services import brakes, reminders

router = APIRouter(prefix="/api/v1", tags=["reminders"])

Rhythm = Literal["single", "weekly", "both"]


class Lead(BaseModel):
    #: Days ahead: a bill (1, 3, 7, 14), the last day to cancel (7, 14, 30, 60), the end of a warranty (7, 14, 30, 60).
    due: int
    cancel: int
    warranty: int


class LeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Whole numbers only: ``true`` is not a 1.
    due: StrictInt | None = None
    cancel: StrictInt | None = None
    warranty: StrictInt | None = None


class LeadOptions(BaseModel):
    due: list[int]
    cancel: list[int]
    warranty: list[int]


class ReminderVault(BaseModel):
    id: int
    #: A personal vault is named after its person.
    name: str
    icon: str
    #: The caller's own vault.
    personal: bool
    #: The own vault of somebody else.
    personal_of_other: bool


class ReminderVaultMine(ReminderVault):
    muted: bool
    #: How many others are reminded too (edit or manage in the vault).
    others: int


class RemindersOut(BaseModel):
    #: ``single`` (one message per deadline), ``weekly`` (a mail on Mondays) or ``both``.
    rhythm: Rhythm
    push: bool
    mail: bool
    lead: Lead
    #: Once more on the day itself.
    same_day: bool
    #: The muted vaults.
    muted: list[int]
    #: Nothing about documents reached through a share alone.
    muted_shared: bool
    options: LeadOptions
    #: The hour of the day the reminders go, in ``time_zone``.
    hour: int
    time_zone: str
    #: Own devices that take a push.
    push_devices: int
    #: The confirmed own address; empty without one.
    mail_address: str
    #: Why nothing goes by mail: ``no_server``, ``no_address``, ``unconfirmed``; null when it can.
    mail_problem: Literal["no_server", "no_address", "unconfirmed"] | None
    #: Vaults where the caller may change things: they are reminded, and can mute them.
    vaults: list[ReminderVaultMine]
    #: Vaults the caller may only read: never reminded.
    read_only: list[ReminderVault]
    #: Documents shared with the caller with ``edit``, in no vault of theirs to change things in.
    shared: int


class RemindersIn(BaseModel):
    """Only what is sent changes."""

    model_config = ConfigDict(extra="forbid")

    rhythm: Rhythm | None = None
    push: bool | None = None
    mail: bool | None = None
    lead: LeadIn | None = None
    same_day: bool | None = None
    muted: list[Annotated[StrictInt, Field(ge=1, le=2**31 - 1)]] | None = Field(default=None,
                                                                           max_length=reminders.MUTED_MAX)
    muted_shared: bool | None = None


class PushCount(BaseModel):
    sent: int
    gone: int
    failed: int


class ReminderTestOut(BaseModel):
    push: PushCount
    #: The mail was taken by the mail server.
    mail: bool
    #: Which ways were tried.
    by_push: bool
    by_mail: bool


@router.get("/me/reminders", response_model=RemindersOut, summary="How the own account is reminded of deadlines")
def get_reminders(account: Caller, db: DbSession) -> dict[str, object]:
    return reminders.view(db, account)


@router.put("/me/reminders", response_model=RemindersOut,
            summary="Change how the own account is reminded; only the values sent change")
def put_reminders(payload: RemindersIn, account: Caller, db: DbSession) -> dict[str, object]:
    change = payload.model_dump(exclude_unset=True)
    if "lead" in change:
        change["lead"] = {key: value for key, value in (change["lead"] or {}).items() if value is not None}
    for key in ("rhythm", "push", "mail", "same_day", "muted_shared", "muted"):
        if key in change and change[key] is None:
            del change[key]
    reminders.save(db, account, change)
    return reminders.view(db, account)


@router.post("/me/reminders/test", response_model=ReminderTestOut,
             summary="A test message on every way the own reminders go")
def test_reminder(account: Caller, db: DbSession) -> dict[str, object]:
    brakes.take("push_test", account.id)
    return reminders.send_test(db, account)
