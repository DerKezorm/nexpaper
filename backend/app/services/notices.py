"""A notice when an account signs in from a new device: a push to the person's devices and a mail, when a mail server
is set up and the account has an address.

New is a browser without the device cookie of this account (``security.devices_of``). Nothing is said for the very
first sign-in of an account (there is no other device to warn), nor when the person switched it off
(``profile.notify_login``, on from the start).

The notice names the device and the browser as its user agent says, the network it came from (the address cut to its
network, no lookup of places anywhere), and the time in the person's zone. Its link leads to the own account,
Security. Sent in the background: a slow push service or mail server never holds the sign-in up.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from .. import clock
from ..models import Account
from . import mailer, push, settings_service, timezones

logger = logging.getLogger("nexpaper.notices")

#: Notices per account and hour, at most: a flood of sign-ins does not become a flood of mails.
PER_HOUR = 10
#: Where the link leads: the own account, Security.
SECURITY_PATH = "/konto?tab=security"
TAG = "sign-in"

#: The networks of a home or an office: there, a new sign-in came from within.
OWN_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "fc00::/7", "fe80::/10", "::1/128",
))
MONTHS = {
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
           "Dezember"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
}
TEXTS = {
    "de": {
        "title": "Neue Anmeldung bei nexpaper",
        "body": "{device}, {when}, {where}. Warst du das nicht? Tippe hier.",
        "on": "{browser} unter {system}",
        "network": "Netz {network}",
        "own": "eigenes Netz {network}",
        "unknown": "unbekanntes Netz",
        "browser": "Ein Browser",
        "system": "einem unbekannten System",
    },
    "en": {
        "title": "New sign-in to nexpaper",
        "body": "{device}, {when}, {where}. Not you? Tap here.",
        "on": "{browser} on {system}",
        "network": "network {network}",
        "own": "own network {network}",
        "unknown": "unknown network",
        "browser": "A browser",
        "system": "an unknown system",
    },
}


def language_of(code: str) -> str:
    return "de" if (code or "").split("-")[0].lower() == "de" else "en"


# --- What the notice says -------------------------------------------------------------------------------------------


def browser_of(agent: str) -> str | None:
    """The browser a user agent names, the usual ones only; None for anything else."""
    for mark, name in (("Edg/", "Edge"), ("EdgA/", "Edge"), ("EdgiOS/", "Edge"), ("OPR/", "Opera"),
                       ("SamsungBrowser/", "Samsung Internet"), ("Firefox/", "Firefox"), ("FxiOS/", "Firefox"),
                       ("CriOS/", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari")):
        if mark in agent:
            return name
    return None


def system_of(agent: str) -> str | None:
    for mark, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("CrOS", "ChromeOS"),
                       ("Windows", "Windows"), ("Macintosh", "macOS"), ("Mac OS X", "macOS"), ("Linux", "Linux")):
        if mark in agent:
            return name
    return None


def device_name(agent: str, lang: str, installed: bool = False) -> str:
    """"Firefox unter Windows", "Safari on iPhone"; the app from the home screen says so."""
    words = TEXTS[language_of(lang)]
    agent = (agent or "")[:500]
    browser = browser_of(agent)
    system = system_of(agent)
    if installed:
        browser = "nexpaper"
    return words["on"].format(browser=browser or words["browser"], system=system or words["system"])


def network_of(address: str, lang: str) -> str:
    """The network an address lies in, never the address itself: an IPv4 address cut to its /24, IPv6 to its /48;
    an own network says so."""
    words = TEXTS[language_of(lang)]
    try:
        ip = ipaddress.ip_address(address.strip().split("%", 1)[0])
    except ValueError:
        return words["unknown"]
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    prefix = 24 if ip.version == 4 else 48
    network = str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
    own = any(ip in net for net in OWN_NETWORKS if net.version == ip.version)
    return words["own" if own else "network"].format(network=network)


def when_of(moment: datetime, account: Account, lang: str) -> str:
    local = moment.astimezone(timezones.zone_of(account))
    month = MONTHS[language_of(lang)][local.month - 1]
    if language_of(lang) == "de":
        return f"{local.day}. {month}, {local:%H:%M}"
    return f"{local.day} {month}, {local:%H:%M}"


# --- Sending --------------------------------------------------------------------------------------------------------


_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nexpaper-notice")
_pending: set[Future[Any]] = set()
_lock = threading.Lock()
_recent: dict[int, deque[float]] = {}


def _room(account_id: int) -> bool:
    moment = time.monotonic()
    with _lock:
        seen = _recent.setdefault(account_id, deque())
        while seen and moment - seen[0] > 3600:
            seen.popleft()
        if len(seen) >= PER_HOUR:
            return False
        seen.append(moment)
        return True


def new_sign_in(account: Account, address: str, agent: str, *, first: bool, known: bool) -> bool:
    """Called at every sign-in, before the session is made. Sends the notice in the background when it is due;
    gives whether it is."""
    profile = account.profile if isinstance(account.profile, dict) else {}
    if first or known or profile.get("notify_login") is False:
        return False
    if not _room(account.id):
        logger.warning("Sign-in notice left out, too many this hour name=%s", account.name)
        return False
    future = _pool.submit(_send, account.id, address[:64], agent[:500], clock.now())
    with _lock:
        _pending.add(future)
    future.add_done_callback(_done)
    return True


def later(job: Callable[..., None], *args: Any) -> None:
    """Runs ``job`` in the background beside the notices (a mail that must not hold a request up, nor tell by its
    duration what it did). A failure is logged and touches nothing."""

    def run() -> None:
        try:
            job(*args)
        except Exception:
            logger.exception("A job in the background failed")

    future = _pool.submit(run)
    with _lock:
        _pending.add(future)
    future.add_done_callback(_done)


def _done(future: Future[Any]) -> None:
    with _lock:
        _pending.discard(future)


def settle(seconds: float = 30) -> None:
    """Waits for the notices on their way (tests; the end of the server)."""
    with _lock:
        pending = list(_pending)
    wait(pending, timeout=seconds)


def _send(account_id: int, address: str, agent: str, moment: datetime) -> None:
    from ..db import SessionLocal

    try:
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account is None:
                return
            db.expunge(account)
            mail_to = account.email if mailer.configured(db) else ""
            base = settings_service.public_url(db)

        def for_lang(lang: str) -> push.Message:
            chosen = language_of(lang or account.language)
            words = TEXTS[chosen]
            body = words["body"].format(device=device_name(agent, chosen), when=when_of(moment, account, chosen),
                                        where=network_of(address, chosen))
            return push.Message(title=words["title"], body=body, url=SECURITY_PATH, desk=SECURITY_PATH, tag=TAG,
                                urgency="high")

        result = push.send_to_person(account_id, for_lang)
        logger.info("Sign-in notice pushed name=%s devices=%s", account.name, result.sent)
        if mail_to:
            _mail(account, mail_to, base, agent, address, moment)
    except Exception:
        # A notice that fails never touches the sign-in.
        logger.exception("A sign-in notice failed")


def _mail(account: Account, to: str, base: str, agent: str, address: str, moment: datetime) -> None:
    """The mail, English like everything nexpaper mails. The link only with the public address the operator set: an
    address taken from the request could be one a stranger chose."""
    from ..db import SessionLocal

    message = EmailMessage()
    message["To"] = to
    message["Subject"] = "New sign-in to nexpaper"
    where = f"Open {base}{SECURITY_PATH}" if base else "Open nexpaper, then Account, Security,"
    message.set_content(
        f"Someone signed in to your nexpaper account {account.name}.\n\n"
        f"Device: {device_name(agent, 'en')}\n"
        f"When: {when_of(moment, account, 'en')} ({timezones.zone_of(account)})\n"
        f"From: {network_of(address, 'en')}\n\n"
        "If this was you, there is nothing to do.\n"
        f"If it was not you: {where} and change your password.\n"
    )
    with SessionLocal() as db:
        try:
            mailer.send_message(db, message)
        except mailer.MailError:
            logger.warning("Sign-in notice not mailed name=%s", account.name)
            return
    logger.info("Sign-in notice mailed name=%s", account.name)


# --- The operator took the second factor --------------------------------------------------------------------------

RESET_TEXTS = {
    "de": ("Zweiter Faktor zurückgesetzt", (
        "Der Betreiber hat deinen zweiten Faktor zurückgesetzt. Richte ihn bei der nächsten Anmeldung neu ein. "
        "Warst du das nicht? Sag dem Betreiber Bescheid.")),
    "en": ("Second factor reset", (
        "The operator reset your second factor. Set it up again at your next sign-in. "
        "Not asked for by you? Tell the operator.")),
}


def factor_reset(account: Account, by: str) -> None:
    """Tells the person that the operator took their second factor: by push to their devices and by mail. In the
    background, like the notice of a sign-in; a failure touches nothing."""
    future = _pool.submit(_send_reset, account.id, by)
    with _lock:
        _pending.add(future)
    future.add_done_callback(_done)


def _send_reset(account_id: int, by: str) -> None:
    from ..db import SessionLocal

    try:
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account is None:
                return
            db.expunge(account)
            mail_to = account.email if mailer.configured(db) else ""

        def for_lang(lang: str) -> push.Message:
            title, body = RESET_TEXTS[language_of(lang or account.language)]
            return push.Message(title=title, body=body, url=SECURITY_PATH, desk=SECURITY_PATH, tag="factor-reset",
                                urgency="high")

        result = push.send_to_person(account_id, for_lang)
        logger.info("Second factor reset notice pushed name=%s devices=%s", account.name, result.sent)
        if mail_to:
            message = EmailMessage()
            message["To"] = mail_to
            message["Subject"] = "Your second factor in nexpaper was reset"
            message.set_content(
                f"The operator ({by}) reset the second factor of your nexpaper account {account.name}.\n\n"
                "At your next sign-in you set it up again.\n"
                "If you did not ask for this, tell the operator and change your password.\n"
            )
            with SessionLocal() as db:
                try:
                    mailer.send_message(db, message)
                except mailer.MailError:
                    logger.warning("Second factor reset notice not mailed name=%s", account.name)
                    return
            logger.info("Second factor reset notice mailed name=%s", account.name)
    except Exception:
        logger.exception("A notice of a second factor reset failed")


def forget() -> None:
    """For the tests."""
    settle()
    with _lock:
        _recent.clear()


# --- A probe of Web Push ---------------------------------------------------------------------------------------------

PROBE_TEXTS = {
    "de": ("nexpaper", "Das ist eine Probe. Wenn du sie siehst, kommen Benachrichtigungen an."),
    "en": ("nexpaper", "This is a test. If you see it, notices reach this device."),
}


def probe(account: Account) -> push.Result:
    """A test message to every device of the person, each in the language it signed up in."""

    def for_lang(lang: str) -> push.Message:
        title, body = PROBE_TEXTS[language_of(lang or account.language)]
        return push.Message(title=title, body=body, url="/", desk="/", tag="probe")

    return push.send_to_person(account.id, for_lang)
