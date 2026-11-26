"""The outbox: a mail is queued in the request and sent by a worker, again after 1, 5, 15, 60 and 180 minutes when the
mail server could not take it; then it is given up. A refusal that another try would not change (recipient or sender
refused, wrong user or password, no address) is given up at once, unless the server said "later" (4xx). Whatever
else goes wrong with one mail counts as a failed try of that mail: the next ones still go. The operator's page
shows the last mail that went out and the last error (``MailStatus``).

The test mail goes out at once, outside the outbox, and tells its error.

Since 1.1.0:

- **at once after queuing** (``nudge``): ``queue`` asks the store to call ``nudge`` after its commit
  (``Store.on_commit``); ``nudge`` runs the app's own round of the outbox (``AppConfig.outbox_runner``) in a thread,
  so a link to confirm an address does not wait for the next minute (nexlore ``d08590b``). Nudges while a round runs
  make one more round, never a second thread. The app's worker stays as the second chance.
- **one mail at once with the result on the operator's page** (``deliver_now``), for what must fail in the request
  (an invitation, "Forgot your password?"): before, the apps called the private ``_note`` or left the page as it was.
- **what is waiting** (``waiting``) for the operator's page.
- **the app hears of every try** where its store has ``after_attempt`` (nextasks' state of each way of notifying).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from . import config, send
from .common import log, utcnow
from .errors import MailError, is_final
from .letters import compose, language_for
from .model import Letter, MailSettings, MailStatus, OutboxItem, Store

#: Minutes after the first, second … failure.
RETRY_MINUTES = (1, 5, 15, 60, 180)
#: How long a worker holds a row it took.
LEASE_SECONDS = 120
BATCH = 20


def _deliver(settings: MailSettings, letter: Letter) -> None:
    """``deliver``, and whatever else breaks counts as ``mail_failed``: one broken mail never stops the outbox, and
    the page shows a reason instead of a 500."""
    try:
        # Through the module (never a name imported once): testing.catch_mail replaces send.deliver (since E44).
        send.deliver(settings, letter)
    except MailError:
        raise
    except Exception as error:  # one broken mail must not stop the outbox
        raise MailError("mail_failed", f"The mail did not go out ({error.__class__.__name__}).") from error


def queue(store: Store, letter: Letter) -> int | str:
    """Into the outbox, due at once; the app commits with its own writes or after. Since 1.1.0 the outbox is nudged
    right after that commit (``Store.on_commit``), so the mail goes out at once; a letter with a ``key`` the outbox
    holds already adds nothing (the id of the row that has it)."""
    item_id = store.add_to_outbox(letter, utcnow())
    hook = getattr(store, "on_commit", None)
    if callable(hook):
        hook(nudge)
    return item_id


# The nudge: at most one thread per process; a nudge while it runs asks for one more round.
_lock = threading.Lock()
_running = False
_again = False
_thread: threading.Thread | None = None


def _round(runner: object) -> None:
    global _running, _again
    while True:
        try:
            runner()  # type: ignore[operator]
        except Exception:  # noqa: BLE001 (a failed round must not end the thread silently; the worker retries)
            log().exception("Outbox round failed")
        with _lock:
            if not _again:
                _running = False
                return
            _again = False


def nudge() -> bool:
    """Since 1.1.0: run the app's round of the outbox now, in a thread (SMTP blocks); True when a round runs or will
    run once more. False without ``AppConfig.outbox_runner`` (then the app's worker sends at its next round)."""
    global _running, _again, _thread
    try:
        runner = config.current().outbox_runner
    except RuntimeError:
        return False
    if runner is None:
        return False
    with _lock:
        if _running:
            _again = True
            return True
        _running = True
    thread = threading.Thread(target=_round, args=(runner,), name=f"{config.current().app_name}-outbox", daemon=True)
    try:
        thread.start()
    except RuntimeError:  # no thread to be had (interpreter shutting down): the worker sends later
        with _lock:
            _running = False
        return False
    _thread = thread
    return True


def settle(timeout: float = 10.0) -> bool:
    """Since 1.1.0, for tests: wait until the nudged rounds are done; False when they still run after ``timeout``."""
    thread = _thread
    if thread is not None:
        thread.join(timeout)
    with _lock:
        return not _running


def _note(store: Store, *, ok: bool, error: str = "") -> None:
    status = store.mail_status()
    now = utcnow()
    if ok:
        store.note_result(MailStatus(now, status.last_error, status.last_error_at))
    else:
        store.note_result(MailStatus(status.last_ok_at, error, now))


def _after(store: Store, item: OutboxItem, error: str, given_up: bool) -> None:
    hook = getattr(store, "after_attempt", None)
    if callable(hook):
        hook(item, error, given_up)


def run_once(store: Store, now: datetime | None = None) -> int:
    """Send what is due (at most ``BATCH``); the number sent. Called by the app's worker every minute or so, and
    since 1.1.0 by the app's ``outbox_runner`` when nudged."""
    moment = now or utcnow()
    settings = store.mail_settings()
    if not settings.configured:
        return 0
    sent = 0
    for item in store.due(moment, BATCH):
        if not store.claim(item.id, moment, moment + timedelta(seconds=LEASE_SECONDS)):
            continue
        store.commit()
        try:
            _deliver(settings, item.letter)
        except MailError as error:
            attempts = item.attempts + 1
            final = is_final(error) or attempts > len(RETRY_MINUTES)
            next_at = None if final else moment + timedelta(minutes=RETRY_MINUTES[attempts - 1])
            store.mark_failed(item.id, attempts, next_at, error.code + (f": {error.detail}" if error.detail else ""))
            _note(store, ok=False, error=error.code)
            _after(store, item, error.code, final)
            store.commit()
            log().warning(
                "Mail not sent kind=%s attempt=%s code=%s%s",
                item.letter.kind or "-",
                attempts,
                error.code,
                " (given up)" if final else "",
            )
            continue
        store.mark_sent(item.id)
        _note(store, ok=True)
        _after(store, item, "", False)
        store.commit()
        sent += 1
    return sent


def deliver_now(store: Store, letter: Letter) -> None:
    """Since 1.1.0: one letter at once, outside the outbox, for what must fail in the request (an invitation,
    "Forgot your password?"); ``MailError`` with the reason. The result goes to the operator's page like an outbox
    mail's (committed here, also when the mail failed). Goes through ``send.deliver``, so ``testing.catch_mail``
    catches it."""
    settings = store.mail_settings()
    try:
        send.deliver(settings, letter)
    except MailError as error:
        if error.code != "mail_off":
            _note(store, ok=False, error=error.code)
            store.commit()
        raise
    except Exception as error:  # the page shows a reason instead of a 500
        _note(store, ok=False, error="mail_failed")
        store.commit()
        raise MailError("mail_failed", f"The mail did not go out ({error.__class__.__name__}).") from error
    _note(store, ok=True)
    store.commit()


def waiting(store: Store) -> int | None:
    """Since 1.1.0: how many mails wait (``Store.waiting``); None where the store cannot tell (a store of 1.0.0)."""
    count = getattr(store, "waiting", None)
    return int(count()) if callable(count) else None


def test_mail(store: Store, to: str, *, language: str = "en") -> None:
    """The operator's test mail, at once; ``MailError`` with the reason (409 ``mail_off``, 502 the server's). The
    letter of the module, with the app's logo and name, the same in every app."""
    settings = store.mail_settings()
    letter = compose("test", to, language=language_for(language), values={})
    try:
        _deliver(settings, letter)
    except MailError as error:
        if error.code != "mail_off":
            _note(store, ok=False, error=error.code)
            store.commit()
        raise
    _note(store, ok=True)
    store.commit()
