"""The written texts of "What's new": their form, which of them an account reads, the guard and the frozen texts.

The texts lie in the app's folder, one file per language (``en.json``, ``de.json``), keyed by version (``"1.17.0"``),
as nexview, nexlore and nexmail kept them (W2). An entry:

    {"lead": "...", "sections": [{"title": "...", "where": "...", "body": "...", "link": {"label": "...",
     "href": "https://..."}, "operator": true}], "smallTitle": "Also", "small": ["..."]}

``link`` (only to https) and ``operator`` (the section only for operators, W8) may be left out. An entry of another
form is left out, never shown half; the guard (``problems``) makes sure none ships like that.

``released.json`` in the same folder freezes the texts of released versions (W12): per version and language the
checksum of the entry. Every version below the running one is released and must be in it; a frozen text never changes
and never goes. ``freeze`` writes it (``tools/sync.py freeze <app>``).

Only the standard library."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from .config import FALLBACK, AppConfig, current

log = logging.getLogger("nexwasneu")

RELEASED = "released.json"
#: A version as the apps write it ("1.17.0"); the whole text.
_VERSION = re.compile(r"(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})")
#: A language asked for ("de", "de-AT", "pt-BR", "zh-Hant"); anything else reads English.
_LANGUAGE = re.compile(r"[a-z]{2,3}(?:[-_](?:[A-Za-z]{2}|[A-Za-z]{4}))?")
#: The largest file the module reads (nexlore's two files are 56 KB and 49 KB after 32 versions).
MAX_FILE = 4 * 1024 * 1024

Version = tuple[int, int, int]


# --- Versions and languages -----------------------------------------------------------------------------------------


def parse(version: str) -> Version | None:
    """``"1.17.0"`` -> ``(1, 17, 0)``; None for anything else (``"v1.2.0"``, ``"1.2"``, ``"01.2.0"``)."""
    found = _VERSION.fullmatch(version) if isinstance(version, str) else None
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


def chain(language: str | None, languages: tuple[str, ...]) -> list[str]:
    """The built-in languages to read, in turn: the one asked for, its base language, English (W4). ``"de-AT"`` ->
    ``["de", "en"]``; ``"nl"`` (uploaded by the operator) -> ``["en"]``; garbage -> ``["en"]``."""
    found: list[str] = []
    if isinstance(language, str) and _LANGUAGE.fullmatch(language):
        asked = language.replace("_", "-")
        base = asked.split("-")[0].lower()
        for candidate in (asked, base):
            if candidate in languages and candidate not in found:
                found.append(candidate)
    if FALLBACK not in found:
        found.append(FALLBACK)
    return found


# --- The form of an entry -------------------------------------------------------------------------------------------


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_link(value: Any) -> bool:
    """A link leaves only to https, never to a script or a page of the app itself."""
    return (
        isinstance(value, dict)
        and set(value) <= {"label", "href"}
        and _text(value.get("label"))
        and _text(value.get("href"))
        and value["href"].startswith("https://")
        and not any(char.isspace() for char in value["href"])
    )


def is_section(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value) <= {"title", "where", "body", "link", "operator"}:
        return False
    return (
        _text(value.get("title"))
        and _text(value.get("where"))
        and _text(value.get("body"))
        and ("link" not in value or is_link(value["link"]))
        and ("operator" not in value or isinstance(value["operator"], bool))
    )


def is_entry(value: Any) -> bool:
    """The four fields, every text not empty; ``smallTitle`` may be empty only while ``small`` is."""
    if not isinstance(value, dict) or set(value) != {"lead", "sections", "smallTitle", "small"}:
        return False
    sections, small = value["sections"], value["small"]
    return (
        _text(value["lead"])
        and isinstance(sections, list)
        and len(sections) > 0
        and all(is_section(part) for part in sections)
        and isinstance(value["smallTitle"], str)
        and isinstance(small, list)
        and all(_text(line) for line in small)
        and (not small or _text(value["smallTitle"]))
    )


def visible(entry: dict[str, Any], operator: bool) -> dict[str, Any] | None:
    """The entry as one account sees it: a section marked ``operator`` only for operators (W8); without a section left,
    nothing. The flag itself stays in what goes out (the window marks those sections for the operator)."""
    sections = [part for part in entry["sections"] if operator or not part.get("operator", False)]
    if not sections:
        return None
    return {**entry, "sections": sections}


def digest(entry: Any) -> str:
    """The checksum of an entry, independent of the order of its keys and of the file's layout (``sha256-<base64>``,
    the form the apps' commit scanners pass)."""
    text = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


# --- Reading the files ----------------------------------------------------------------------------------------------


def read_file(path: Path) -> dict[str, Any] | None:
    """A file as it stands: None when it is missing; raises ``ValueError`` when it is no JSON object or too large."""
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if len(raw) > MAX_FILE:
        raise ValueError(f"{path.name} is larger than {MAX_FILE // (1024 * 1024)} MB")
    try:
        found = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path.name} is no JSON ({error.__class__.__name__})") from error
    if not isinstance(found, dict):
        raise ValueError(f"{path.name} holds no object")
    return found


@dataclass
class _Cached:
    stamp: tuple[int, int, int]
    entries: dict[Version, dict[str, Any]]


_cache: dict[Path, _Cached] = {}
_told: set[tuple[Path, tuple[int, int, int]]] = set()
_lock = Lock()


def _stamp(path: Path) -> tuple[int, int, int] | None:
    try:
        found = path.stat()
    except OSError:
        return None
    return (found.st_mtime_ns, found.st_size, found.st_ino)


def entries(folder: Path, language: str) -> dict[Version, dict[str, Any]]:
    """The valid entries of one language, read again only when the file changed. A broken file or entry is left out
    and named once per state of the file in the log (WARNING), never shown half."""
    path = folder / f"{language}.json"
    stamp = _stamp(path)
    if stamp is None:
        return {}
    with _lock:
        cached = _cache.get(path)
        if cached and cached.stamp == stamp:
            return cached.entries
        found: dict[Version, dict[str, Any]] = {}
        bad: list[str] = []
        try:
            raw = read_file(path) or {}
        except (OSError, ValueError) as error:
            raw, bad = {}, [str(error)]
        for key, value in raw.items():
            version = parse(key)
            if version is None or not is_entry(value):
                bad.append(str(key)[:40])
            else:
                found[version] = value
        if bad and (path, stamp) not in _told:
            _told.add((path, stamp))
            log.warning("What's new: left out of %s: %s", path.name, ", ".join(bad[:10]))
        _cache[path] = _Cached(stamp, found)
        return found


def forget() -> None:
    """Drop what was read (tests)."""
    with _lock:
        _cache.clear()
        _told.clear()


# --- What an account reads ------------------------------------------------------------------------------------------


def _shown(version: Version) -> str:
    return ".".join(str(part) for part in version)


def collected(language: str | None, operator: bool, config: AppConfig | None = None) -> list[dict[str, Any]]:
    """Every entry up to the running version as this account reads it, the newest first: per version the first
    language of the chain that has one (W4, W16), with ``version`` and ``language`` added."""
    config = config or current()
    running = parse(config.running())
    if running is None:
        return []
    found: dict[Version, dict[str, Any]] = {}
    for code in chain(language, config.languages):
        for version, entry in entries(config.folder, code).items():
            if version in found or version > running:
                continue
            seen = visible(entry, operator)
            if seen is not None:
                found[version] = {"version": _shown(version), "language": code, **seen}
    return [found[version] for version in sorted(found, reverse=True)]


@dataclass(frozen=True)
class State:
    """What ``GET <prefix>`` answers: the running version, what this account read, its unread entries (the newest
    first, at most ``unread_limit``; ``more`` when there were more), the entry for "About" and whether there are
    earlier ones."""

    version: str
    seen: str
    unread: list[dict[str, Any]]
    more: bool
    current: dict[str, Any] | None
    earlier: bool


def state(seen: str | None, language: str | None, operator: bool, config: AppConfig | None = None) -> State:
    """W5 to W7: unread are the entries after the version this account read up to the running one. A version it never
    read in a form we know (empty, garbage) shows only the newest entry; an account ahead of the running version (a step
    back) reads nothing. A fix without its own text shows no banner; "About" shows the newest entry up to it."""
    config = config or current()
    running_text = config.running()
    every = collected(language, operator, config)
    seen_text = seen if isinstance(seen, str) else ""
    read = parse(seen_text)
    # Every entry is at most the running version: who read it or a later one (a step back) has nothing after it.
    if read is None:
        unread = every[:1]
    else:
        unread = [entry for entry in every if parse(entry["version"]) > read]  # type: ignore[operator]
    limit = config.unread_limit
    return State(
        version=running_text,
        seen=seen_text,
        unread=unread[:limit],
        more=len(unread) > limit,
        current=every[0] if every else None,
        earlier=len(every) > 1,
    )


# --- The guard and the frozen texts (W11, W12) ----------------------------------------------------------------------


def _all(folder: Path, languages: tuple[str, ...], problems: list[str]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for code in languages:
        try:
            files[code] = read_file(folder / f"{code}.json") or {}
        except (OSError, ValueError) as error:
            problems.append(str(error))
            files[code] = {}
        if not (folder / f"{code}.json").is_file():
            problems.append(f"{code}.json is missing (an empty file is {{}})")
    return files


def read_released(folder: Path) -> dict[str, dict[str, str]]:
    """``released.json``: version -> language -> checksum; empty while there is none. Raises ``ValueError`` when it
    is not of that form."""
    raw = read_file(folder / RELEASED)
    if raw is None:
        return {}
    for version, languages in raw.items():
        if parse(version) is None or not isinstance(languages, dict):
            raise ValueError(f"{RELEASED}: {version!r} is no version with its languages")
        for code, value in languages.items():
            if not isinstance(code, str) or not isinstance(value, str) or not value.startswith("sha256-"):
                raise ValueError(f"{RELEASED}: {version} {code!r} holds no checksum")
    return raw


def problems(config: AppConfig | None = None) -> list[str]:
    """Everything that stops a release, in words (empty: all is well). Runs in every app with the contract tests.

    1. every file of a built-in language is there and is a JSON object; every key is a version, every value an entry;
    2. English names every version another language names (the fallback);
    3. the running version x.y.0 has its entry in every built-in language (not the app's first version);
    4. an entry not frozen yet stands in every built-in language, built alike (as many sections and small things, the
       same sections for operators);
    5. every version below the running one is frozen in every language that has it, and a frozen text is unchanged."""
    config = config or current()
    found: list[str] = []
    files = _all(config.folder, config.languages, found)
    for code, every in files.items():
        for key, value in every.items():
            if parse(key) is None:
                found.append(f"{code}.json: {str(key)[:40]!r} is no version like 1.2.0")
            elif not is_entry(value):
                found.append(f"{code}.json: the entry of {key} is not of the form (lead, sections, smallTitle, small)")
    english = set(files.get(FALLBACK, {}))
    for code, every in files.items():
        for key in sorted(set(every) - english):
            found.append(f"{code}.json has {key}, en.json not (English is every other language's fallback)")
    running_text = config.running()
    running = parse(running_text)
    if running is None:
        return [*found, f"the running version {running_text!r} is no version like 1.2.0"]
    if running[2] == 0 and running_text != config.first:
        for code, every in files.items():
            if running_text not in every:
                found.append(f"{code}.json has no entry for {running_text}: a version x.y.0 ships with its text")
    try:
        released = read_released(config.folder)
    except ValueError as error:
        return [*found, str(error)]
    versions = {key for every in files.values() for key in every if parse(key) is not None}
    for key in sorted(versions, key=parse):  # type: ignore[arg-type]
        version = parse(key)
        assert version is not None
        holding = {code: every[key] for code, every in files.items() if key in every}
        if version < running:
            for code, entry in holding.items():
                frozen = released.get(key, {}).get(code)
                if frozen is None:
                    found.append(f"{key} ({code}) is released but not frozen: run tools/sync.py freeze <app>")
                elif frozen != digest(entry):
                    found.append(f"{key} ({code}) was released and has changed; a released text stays as it was")
        elif key not in released:
            for code in config.languages:
                if code not in holding:
                    found.append(f"{key} is not released yet and has no entry in {code}.json")
            shapes = {
                code: (len(entry["sections"]), len(entry["small"]),
                       tuple(bool(part.get("operator")) for part in entry["sections"]))
                for code, entry in holding.items() if is_entry(entry)
            }
            if len(set(shapes.values())) > 1:
                found.append(f"{key} is built differently in its languages: {shapes}")
    for key, languages in released.items():
        for code in languages:
            if key not in files.get(code, {}):
                found.append(f"{key} ({code}) is frozen but gone from {code}.json; a released text stays")
    return found


class FreezeRefused(Exception):
    pass


def freeze(config: AppConfig | None = None, change: tuple[str, ...] = ()) -> dict[str, list[str]]:
    """Freeze every entry below the running version (W12): writes ``released.json`` and returns what it added and what
    it changed (``version (language)``). A frozen text that differs is refused, unless its version is named in
    ``change`` (a typo fixed on purpose). Entries of the running version and above stay free."""
    config = config or current()
    running = parse(config.running())
    if running is None:
        raise FreezeRefused(f"the running version {config.running()!r} is no version like 1.2.0")
    try:
        released = read_released(config.folder)
    except ValueError as error:
        raise FreezeRefused(str(error)) from error
    broken: list[str] = []
    files = _all(config.folder, config.languages, broken)
    added: list[str] = []
    changed: list[str] = []
    refused: list[str] = []
    for code, every in files.items():
        for key, entry in every.items():
            version = parse(key)
            if version is None or version >= running:
                continue
            if not is_entry(entry):
                refused.append(f"{key} ({code}) is not of the form; mend it before it is frozen")
                continue
            now = digest(entry)
            before = released.get(key, {}).get(code)
            if before is None:
                released.setdefault(key, {})[code] = now
                added.append(f"{key} ({code})")
            elif before != now:
                if key in change:
                    released[key][code] = now
                    changed.append(f"{key} ({code})")
                else:
                    refused.append(f"{key} ({code}) was released and has changed (name it with --change {key})")
    if refused:
        raise FreezeRefused("; ".join(refused))
    ordered = {
        key: dict(sorted(released[key].items()))
        for key in sorted(released, key=lambda text: parse(text) or (0, 0, 0))
    }
    (config.folder / RELEASED).write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"added": added, "changed": changed}
