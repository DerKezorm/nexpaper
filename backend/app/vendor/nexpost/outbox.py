"""The outbox: a mail is queued in the request and sent by a worker, again after 1, 5, 15, 60 and 180 minutes when the
mail server could not take it; then it is given up. A refusal that another try would not change (recipient or sender
refused, wrong user or password, no address) is given up at once, unless the server said "later" (4xx). Whatever
else goes wrong with one mail counts as a failed try of that mail: the next ones still go. The operator's page
shows the last mail that went out and the last error (``MailStatus``).

The test mail goes out at once, outside the outbox, and tells its error.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .common import log, utcnow
from .errors import MailError, is_final
from .letters import compose, language_for
from .model import Letter, MailSettings, MailStatus, Store
from .send import deliver

#: Minutes after the first, second … failure.
RETRY_MINUTES = (1, 5, 15, 60, 180)
#: How long a worker holds a row it took.
LEASE_SECONDS = 120
BATCH = 20


def _deliver(settings: MailSettings, letter: Letter) -> None:
    """``deliver``, and whatever else breaks counts as ``mail_failed``: one broken mail never stops the outbox, and
    the page shows a reason instead of a 500."""
    try:
        deliver(settings, letter)
    except MailError:
        raise
    except Exception as error:  # one broken mail must not stop the outbox
        raise MailError("mail_failed", f"The mail did not go out ({error.__class__.__name__}).") from error


def queue(store: Store, letter: Letter) -> int | str:
    """Into the outbox, due at once; the app commits with its own writes or after."""
    return store.add_to_outbox(letter, utcnow())


def _note(store: Store, *, ok: bool, error: str = "") -> None:
    status = store.mail_status()
    now = utcnow()
    if ok:
        store.note_result(MailStatus(now, status.last_error, status.last_error_at))
    else:
        store.note_result(MailStatus(status.last_ok_at, error, now))


def run_once(store: Store, now: datetime | None = None) -> int:
    """Send what is due (at most ``BATCH``); the number sent. Called by the app's worker every minute or so."""
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
        store.commit()
        sent += 1
    return sent


def test_mail(store: Store, to: str, *, language: str = "en") -> None:
    """The operator's test mail, at once; ``MailError`` with the reason (409 ``mail_off``, 502 the server's)."""
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
