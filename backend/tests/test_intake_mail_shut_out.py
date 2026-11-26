# ruff: noqa: F811 - the fixtures of the mailbox come from test_intake_mail
"""The mailbox and an account that is out (Bauplan E38, E57): a mail to the plus address of a blocked or deleted
account, or from a confirmed address of such an account only, never goes to the operator, not even as unknown. It
waits unread in the mailbox and comes in as any other once the account is back; once the account is removed for good,
it is passed over and given to nobody."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account
from app.services import intake_mail, settings_service
from app.services.konten_store import KontenStore
from app.vendor.nexkonten import manage

from . import imap_server
from .conftest import PASSWORD, make_account, remove_for_good
from .test_intake_mail import (  # noqa: F401 - fixtures
    PDF,
    certificate,
    confirmed_sender,
    deliver,
    docs,
    items,
    mail,
    mailbox,
    server,
    set_up,
    store,
    trusted,
)

SEEN = "\\Seen"


def act(name: str, account: Account, operator: Account) -> None:
    """What the operator does on Server › Accounts: ``block``, ``unblock``, ``remove`` (delete), ``restore``."""
    with SessionLocal() as db:
        getattr(manage, name)(KontenStore(db), account.id, actor_id=operator.id, password=PASSWORD)


def unread(box: imap_server.Store) -> list[bool]:
    return [SEEN not in kept.flags for kept in box.inbox().mails]


def held() -> dict[str, Any]:
    with SessionLocal() as db:
        return dict(settings_service.get(db, "mail_state")["held"])


def owners() -> list[int | None]:
    return [document.owner_id for document in docs()]


def test_a_blocked_accounts_mail_waits_unread_and_the_operator_sees_nothing(mailbox: imap_server.Store,
                                                                              operator: Account) -> None:
    tom = make_account("tom")
    confirmed_sender(tom, "tom.privat@example.com")
    act("block", tom, operator)
    deliver(mailbox, mail(sender="someone@example.org", to="paper+tom@example.com", files=[PDF]))
    deliver(mailbox, mail(sender="tom.privat@example.com", files=[PDF]))
    first = intake_mail.fetch()
    assert (first.held, first.files, first.unknown, first.mails) == (2, 0, 0, 0)
    assert docs() == [] and items() == [], "nothing for the operator, not even as unknown"
    assert unread(mailbox) == [True, True]
    assert sorted(held().values()) == [[tom.id], [tom.id]]
    # Still blocked: the mails are not fetched again.
    again = intake_mail.fetch()
    assert (again.held, again.files) == (0, 0) and docs() == []
    act("unblock", tom, operator)
    done = intake_mail.fetch()
    assert (done.files, done.mails, done.unknown) == (2, 2, 0)
    assert owners() == [tom.id, tom.id] and [i.unknown for i in items()] == [False, False]
    assert unread(mailbox) == [False, False], "marked read afterwards, as any other"
    assert held() == {}


def test_a_mail_of_somebody_who_may_receive_is_not_held(mailbox: imap_server.Store, operator: Account) -> None:
    """Only post meant for the account that is out waits: the plus address of somebody else, the address of another
    person and an unknown sender go their ways as before."""
    tom, jule = make_account("tom"), make_account("jule")
    confirmed_sender(tom, "shared@example.com")
    confirmed_sender(jule, "shared@example.com")
    act("block", tom, operator)
    deliver(mailbox, mail(sender="shared@example.com", files=[PDF]))
    deliver(mailbox, mail(sender="tom.privat@example.com", to="paper+jule@example.com", files=[PDF]))
    deliver(mailbox, mail(sender="nobody@example.org", to="paper+niemand@example.com", files=[PDF]))
    done = intake_mail.fetch()
    assert (done.held, done.files) == (0, 3)
    assert owners() == [jule.id, jule.id, operator.id]
    assert [i.unknown for i in items()] == [False, False, True]


def test_a_deleted_accounts_mail_waits_and_comes_in_when_it_is_brought_back(mailbox: imap_server.Store,
                                                                             operator: Account) -> None:
    tom = make_account("tom")
    act("remove", tom, operator)
    deliver(mailbox, mail(sender="someone@example.org", to="paper+tom@example.com", files=[PDF]))
    assert intake_mail.fetch().held == 1
    assert docs() == [] and items() == [] and unread(mailbox) == [True]
    act("restore", tom, operator)
    done = intake_mail.fetch()
    assert (done.files, done.unknown) == (1, 0) and owners() == [tom.id]
    assert unread(mailbox) == [False] and held() == {}


def test_a_mail_that_waited_for_an_account_removed_for_good_goes_to_nobody(mailbox: imap_server.Store,
                                                                         operator: Account) -> None:
    tom = make_account("tom")
    confirmed_sender(tom, "tom.privat@example.com")
    act("remove", tom, operator)
    deliver(mailbox, mail(sender="someone@example.org", to="paper+tom@example.com", files=[PDF]))
    deliver(mailbox, mail(sender="tom.privat@example.com", files=[PDF]))
    assert intake_mail.fetch().held == 2
    remove_for_good(tom)
    done = intake_mail.fetch()
    assert (done.dropped, done.files, done.unknown, done.held) == (2, 0, 0, 0)
    assert docs() == [] and items() == [], "the operator gets none of it"
    assert unread(mailbox) == [True, True], "passed over, left as it is"
    assert held() == {}
    # Never fetched again.
    later = intake_mail.fetch()
    assert (later.dropped, later.files) == (0, 0) and docs() == []
    with SessionLocal() as db:
        assert db.scalar(select(Account.id).where(Account.id == tom.id)) is None
