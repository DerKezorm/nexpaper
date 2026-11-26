"""Blacking out: what never reaches the log, at any level and in every app.

A record is one line (``one_line``): a line break inside a message would let whoever controls a value (a request
path, a file name) write a second, genuine-looking record. Then ``redact`` takes out, in this order:

1. the app's keys and tokens by their prefix (``ntk_…``, ``nxa_…``): the prefix stays, the rest becomes ``…``;
2. tokens in an address after a path segment that carries one (``/invite/<token>``; common segments and the app's);
3. tokens in a query (``?token=…``, ``&code=…``; common keys and the app's);
4. a password, secret or key written as ``name=value`` or ``name: value``, and the value of ``Bearer``;
5. the app's own rules (nexmail keeps its patterns of LOGIN, AUTH and words like Passwort exactly so).

Contents (notes, mails, entries) are never handed to the logger in the first place: that is the app's rule, kept by its
own tests (``test_log_secrets.py``). The module cannot know what a content looks like."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppConfig

#: Path segments followed by a token in every app.
COMMON_TOKEN_PATHS = ("invite", "reset", "public", "s", "oauth/authorize", "confirm-email")
#: Query parameters that carry a token in every app.
COMMON_QUERY_KEYS = ("access_token", "token", "key", "code", "state", "code_challenge", "code_verifier")
#: ``password=…``, ``secret: …``, ``api_key=…``: the value goes, the name stays.
_CREDENTIAL = re.compile(
    r"(?i)(\b(?:password|passwort|kennwort|passphrase|secret|client_secret|token|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token)\b\s*[=:]\s*)(?!…)[^\s,;)\"'&]+"
)
#: A token after "Bearer" goes, unless a rule before already blacked it out: then the key's prefix stays visible
#: (``Bearer nxa_…``, as without "Bearer"; since E44 it became ``Bearer ……``).
_BEARER = re.compile(r"(?i)(\bbearer\s+)(?![A-Za-z0-9._~+/=-]*…)[A-Za-z0-9._~+/=-]+")

_rules: list[tuple[re.Pattern[str], str]] = []


def one_line(text: str) -> str:
    """``\\r`` and ``\\n`` written as the two characters, so a record stays one line."""
    return text.replace("\r", "\\r").replace("\n", "\\n")


def _alternatives(words: tuple[str, ...]) -> str:
    unique = list(dict.fromkeys(word for word in words if word))
    return "|".join(re.escape(word) for word in sorted(unique, key=len, reverse=True))


def rebuild(config: AppConfig) -> None:
    """The rules for this app (``configure`` calls it)."""
    rules: list[tuple[re.Pattern[str], str]] = []
    if config.key_prefixes:
        rules.append((re.compile(rf"({_alternatives(config.key_prefixes)})[A-Za-z0-9_-]+"), r"\1…"))
    paths = _alternatives((*COMMON_TOKEN_PATHS, *config.token_paths))
    rules.append((re.compile(rf"(/(?:api/(?:v\d+/)?)?(?:{paths})/)[A-Za-z0-9_-]{{12,}}"), r"\1…"))
    keys = _alternatives((*COMMON_QUERY_KEYS, *config.query_keys))
    rules.append((re.compile(rf"([?&](?:{keys})=)[^&\s\"']+"), r"\1…"))
    rules.append((_CREDENTIAL, r"\1…"))
    rules.append((_BEARER, r"\1…"))
    rules.extend((re.compile(pattern), replacement) for pattern, replacement in config.redactions)
    _rules[:] = rules


def redact(text: str) -> str:
    """The text with everything blacked out that the rules name. Before ``configure``: the common rules."""
    if not _rules:
        from .config import AppConfig

        rebuild(AppConfig(app_name="nexapp", log_dir="."))
    for pattern, replacement in _rules:
        text = pattern.sub(replacement, text)
    return text


def shorten_address(address: str) -> str:
    """``kim@example.com`` -> ``k***@example.com``: a mail address in a line names its domain, not the person
    (nexmail's ``adresse_kuerzen``)."""
    local, at, domain = (address or "").partition("@")
    if not at:
        return "***"
    return f"{local[:1]}***@{domain}"
