"""Display name, username and address: the rules, the suggestion, the numbering.

Three things, three words. The **display name** is how others see you: free, umlauts and emoji allowed, at most 80
characters, empty shows the username. The **username** is what you sign in with: 2 to 64 characters out of a to z,
digits, dot, hyphen, underscore, never an @ (that is how the sign-in field tells an address), compared without regard
to case, unique. The **email** is optional, at most one per account, unique over all accounts without regard to case.

A username of an older version keeps working even when it breaks these rules (capitals, one letter, other
characters): the rules are checked when a name is set, never when one is looked up. A name once used stays reserved
for ever, also the name of an account deleted for good (``Store.name_reserved``).

Display names are unique too (compared as ``display_key``: NFKC, without regard to case), and neither may look like
another account's username: a display name equal to a foreign username, or a new username equal to a foreign display
name, is taken. So nobody can pass for somebody else when sharing or in a comment.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .errors import AccountError
from .model import Account, AccountId, Store
from .visible import has_something_to_see, skeleton, visible

USERNAME_MIN = 2
USERNAME_MAX = 64
#: The first character a letter or digit: a name like ``..`` or ``-x`` would read as something else in a path or on a
#: command line.
USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
DISPLAY_NAME_MAX = 80
EMAIL_MAX = 254
#: Enough to catch a typo, not a validation of the address: the mail server has the last word. No control character
#: and no line break.
_PART = r"[^@\s<>,;\x00-\x1f\x7f-\x9f]+"
EMAIL_PATTERN = re.compile(rf"{_PART}@{_PART}\.{_PART}")
PASSWORD_MIN = 12
PASSWORD_MAX = 256
#: How far numbering goes (``max-2``, ``max-3`` …) before the module gives up.
NAME_TRIES = 1000
FALLBACK_USERNAME = "user"

_GERMAN = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_NOT_ALLOWED = re.compile(r"[^a-z0-9._-]+")
_PUNCTUATION_RUN = re.compile(r"([._-])[._-]+")
_NUMBERED = re.compile(r"(.*?)(-\d+)")


def normalize_username(raw: str) -> str:
    """What is compared and stored: without blanks at the edges, in lower case."""
    return (raw or "").strip().lower()


def valid_username(name: str) -> bool:
    return bool(USERNAME_PATTERN.fullmatch(name)) and "@" not in name


def check_username(raw: str) -> str:
    """The username as it is stored, or ``username_invalid``."""
    name = normalize_username(raw)
    if not valid_username(name):
        raise AccountError(
            "username_invalid", "Use 2 to 64 characters: a to z, digits, dot, hyphen, underscore.", 422
        )
    return name


def _fold(text: str) -> str:
    """Lower case, German umlauts written out, other accents dropped, everything else a hyphen; runs of punctuation
    made one, none at the edges. ``konten.ts`` does exactly the same (``suggestUsername``)."""
    text = unicodedata.normalize("NFC", text or "").lower().translate(_GERMAN)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.category(char).startswith("M"))
    text = _NOT_ALLOWED.sub("-", text)
    text = _PUNCTUATION_RUN.sub(r"\1", text)
    return text.strip("._-")


def _cut(name: str) -> str:
    """At most ``USERNAME_MAX``; a number at the end (``max-2``) survives the cut."""
    if len(name) <= USERNAME_MAX:
        return name
    numbered = _NUMBERED.fullmatch(name)
    suffix = numbered.group(2) if numbered else ""
    stem = numbered.group(1) if numbered else name
    return stem[: USERNAME_MAX - len(suffix)].rstrip("._-") + suffix


def suggest_username(display_name: str) -> str:
    """A username from a display name (``Max Müller`` becomes ``max-mueller``); "" when nothing usable is left."""
    name = _cut(_fold(display_name)).strip("._-")
    return name if valid_username(name) else ""


def clean_username(raw: str) -> str:
    """The naming rules applied to a name a provider suggests (``Store.clean_name`` of the OIDC module): the same as
    ``suggest_username``, and a valid name stays as it is."""
    return suggest_username(raw)


def username_taken(store: Store, name: str, except_id: AccountId | None = None) -> bool:
    """The name is not free for this account (``Store.name_taken`` of the OIDC module): another account has it now
    (in any case), had it once, or shows it as its display name."""
    wanted = normalize_username(name)
    if any(account.id != except_id for account in store.find_by_username(wanted)):
        return True
    return store.name_reserved(wanted, except_id) or store.display_name_taken(wanted, except_id)


def display_key(name: str) -> str:
    """What display names (and usernames against them) are compared by: invisible characters gone, blanks as one,
    NFKC, without regard to case, letters of Cyrillic and Greek that look like Latin ones as those
    (``visible.skeleton``). An app that keeps the key in a column computes it with this function."""
    return skeleton(name)


def display_name_taken(store: Store, name: str, except_id: AccountId | None = None) -> bool:
    """Another account shows this display name, or has it (or had it) as its username. An empty one is never
    taken."""
    key = display_key(name)
    if not key:
        return False
    if store.display_name_taken(name, except_id):
        return True
    if any(account.id != except_id for account in store.find_by_username(key)):
        return True
    return store.name_reserved(key, except_id)


def check_display_name(store: Store, raw: str, except_id: AccountId | None = None, *, required: bool) -> str:
    """The display name as it is stored: cleaned, required where ``required`` (``display_name_empty``), and nobody
    else's (``display_name_taken``)."""
    shown = clean_display_name(raw)
    if required and not has_something_to_see(shown):
        raise AccountError("display_name_empty", "Enter a display name.", 422)
    if display_name_taken(store, shown, except_id):
        raise AccountError("display_name_taken", "Another account shows this name already.", 409)
    return shown


def provider_display_name(store: Store, raw: str, except_id: AccountId | None = None) -> str:
    """The display name a provider sends (claim ``name``) for a new account: cleaned, and "" when another account
    shows it or has it as username (then the account shows its username, nothing stops the sign-in)."""
    shown = clean_display_name(raw)
    return "" if display_name_taken(store, shown, except_id) else shown


def numbered(base: str) -> Iterable[str]:
    yield base
    for number in range(2, NAME_TRIES):
        yield _cut(f"{base}-{number}")


def free_username(store: Store, base: str) -> str:
    """``base``, else ``base-2``, ``base-3`` …; a base that breaks the rules becomes ``user``."""
    start = clean_username(base) or FALLBACK_USERNAME
    for candidate in numbered(start):
        if not username_taken(store, candidate):
            return candidate
    raise RuntimeError(f"no free username from {start!r}")


def clean_display_name(raw: str) -> str:
    """A name as people typed it: umlauts and emoji stay; what nobody can see goes (control and format characters,
    joiners and selectors outside emoji, fillers), blanks become one, at most ``DISPLAY_NAME_MAX`` characters. A name
    of nothing visible is "" (``visible.visible``)."""
    text = visible(raw)
    if not has_something_to_see(text):
        return ""
    return text[:DISPLAY_NAME_MAX].strip()


def shown_name(account: Account) -> str:
    """What others see: the display name, or the username when there is none."""
    return account.display_name.strip() or account.username


def clean_email(raw: str) -> str:
    """An address in the right form, blanks at the edges gone, case kept; "" stays "" (no address). Otherwise
    ``email_invalid``."""
    address = (raw or "").strip()
    if not address:
        return ""
    if len(address) > EMAIL_MAX or not EMAIL_PATTERN.fullmatch(address):
        raise AccountError("email_invalid", "This is not an email address.", 422)
    return address


def same_address(first: str, second: str) -> bool:
    return bool(first) and first.strip().lower() == (second or "").strip().lower()


def email_taken(store: Store, address: str, except_id: AccountId | None = None) -> bool:
    """Another account has this address in effect (any case, confirmed or not)."""
    return any(
        account.id != except_id and same_address(account.email, address) for account in store.find_by_email(address)
    )


def check_password_rule(password: str) -> None:
    """For a password set from now on: at least ``PASSWORD_MIN`` characters, no rules about special characters.
    Passwords of an older version that are shorter keep working; this is never asked at sign-in."""
    if len(password or "") < PASSWORD_MIN:
        raise AccountError(
            "password_too_short", f"Use at least {PASSWORD_MIN} characters.", 422, minimum=PASSWORD_MIN
        )
    if len(password) > PASSWORD_MAX:
        raise AccountError(
            "password_too_long", f"Use at most {PASSWORD_MAX} characters.", 422, maximum=PASSWORD_MAX
        )
