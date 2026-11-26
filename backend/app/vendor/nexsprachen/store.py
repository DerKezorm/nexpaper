"""The operator's own languages: JSON files in the app's folder (nexnotes ``<data_dir>/locales``), one per language,
named after its code (``nl.json``, ``pt-BR.json``, ``zh-Hant.json``).

A file holds the same keys as the app's English texts; what it leaves out falls back to English in the browser. A file
for a built-in language (``de.json``) replaces only the texts it holds: the page lays it over the shipped ones, so a
wording changes without a release. An optional ``"_meta": {"name": "Nederlands"}`` gives the name in the menus.

The files come from outside, so nothing in them is trusted:

* The code must match ``CODE_PATTERN`` as a whole (``re.fullmatch``: ``nl`` followed by a line break is no code) before
  it becomes a file name. Nothing outside the folder is read or written: links and anything but a plain file are
  refused, reading opens without following a link where the system can.
* A file is at most ``MAX_BYTES``, valid UTF-8 and valid JSON, an object of texts and groups of texts at most
  ``MAX_DEPTH`` levels deep; no empty, overlong or reserved key (``__proto__``), no text a browser could not take
  (a lone surrogate). The page renders the texts as text, never as HTML.
* An upload is checked whole before anything is written, then written under a passing name and moved into place: a
  refused or failed upload leaves the folder as it was.
* What a stopped process left of an upload (a hidden ``.<code>.<random>.part``) is removed when the app starts
  (``tidy_at_start``), never a language file.
* A broken file laid into the folder by hand is skipped and named in the log (once per state of the file); it never
  stops the others or the start of the app.

The names are those of nexnotes' ``services/locales.py`` (``valid_code``, ``load``, ``available``, ``save``,
``remove``, ``forget``, ``locales_dir``, ``Locale``, ``LocaleError``, ``MAX_BYTES`` …), so that file may become
``from app.vendor.nexsprachen import *``.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import current
from .errors import LocaleError, SaveError

#: ``de``, ``es``, ``fil``, ``pt-BR``, ``zh-Hant``: a language, then optionally a region or a script. Used with
#: ``fullmatch`` only (``$`` would let a trailing line break through).
CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}))?$")
MAX_BYTES = 512 * 1024
MAX_DEPTH = 8
MAX_NAME = 60
MAX_KEY = 120
#: More would be a folder somebody filled by mistake; the menu has no room for it either.
MAX_FILES = 200
META_KEY = "_meta"
#: The passing name of an upload (``tempfile.mkstemp(prefix=".<code>.", suffix=".part")``, and the older apps'
#: ``.<code>.json.part``): the only names ``tidy_at_start`` removes.
PASSING_PATTERN = re.compile(r"\.[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}))?\.[A-Za-z0-9_]{1,64}\.part")
#: Held while an upload writes, so that tidying never takes a passing file of this process.
_writing = threading.Lock()
#: Keys a browser's merge of texts must never meet.
RESERVED_KEYS = frozenset({"__proto__"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Locale:
    """One of the operator's files: its code, the name it gives itself (else the code), how many texts it holds."""

    code: str
    name: str
    keys: int


@dataclass(frozen=True)
class Language:
    """One entry of the list the page shows: a built-in language (``built_in``), the operator's file (``own``), or
    both (a file over a built-in one). ``keys`` counts the texts of the operator's file, 0 without one."""

    code: str
    name: str
    keys: int
    built_in: bool
    own: bool


@dataclass(frozen=True)
class Parsed:
    texts: dict[str, Any]
    name: str
    keys: int


def locales_dir() -> Path:
    return current().directory()


def valid_code(code: object) -> bool:
    return isinstance(code, str) and CODE_PATTERN.fullmatch(code) is not None


def _count(value: Any, depth: int) -> int:
    if depth > MAX_DEPTH:
        raise LocaleError("too_deep")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:  # a lone surrogate from "\ud800": no browser text, no JSON answer
            raise LocaleError("not_utf8") from exc
        return 1
    if isinstance(value, dict):
        total = 0
        for key, child in value.items():
            if not key or len(key) > MAX_KEY or key in RESERVED_KEYS or not _encodable(key):
                raise LocaleError("key_invalid")
            total += _count(child, depth + 1)
        return total
    raise LocaleError("not_text")


def _encodable(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def parse(raw: bytes) -> Parsed:
    """A language file checked whole: its texts without ``_meta``, its name, how many texts. ``LocaleError``
    otherwise."""
    if len(raw) > MAX_BYTES:
        raise LocaleError("too_large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LocaleError("not_utf8") from exc
    try:
        data = json.loads(text)
    except RecursionError as exc:  # "[[[[…" a hundred thousand times: deeper than any limit
        raise LocaleError("too_deep") from exc
    except ValueError as exc:
        raise LocaleError("not_json") from exc
    if not isinstance(data, dict):
        raise LocaleError("not_object")
    meta = data.pop(META_KEY, None)
    name = ""
    if meta is not None:
        given = meta.get("name", "") if isinstance(meta, dict) else None
        if not isinstance(given, str) or not _encodable(given):
            raise LocaleError("meta_invalid")
        name = _CONTROL.sub("", given).strip()[:MAX_NAME].strip()
    keys = _count(data, 1)
    if keys == 0:
        raise LocaleError("no_texts")
    return Parsed(texts=data, name=name, keys=keys)


def _path_for(code: str) -> Path:
    """The file of a code: ``LocaleError`` for no code or anything but a plain file, ``FileNotFoundError`` for none.
    Never a path outside the folder."""
    if not valid_code(code):
        raise LocaleError("code")
    root = locales_dir().resolve()
    candidate = root / f"{code}.json"
    try:
        found = candidate.lstat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise FileNotFoundError(code) from exc
    if stat.S_ISLNK(found.st_mode) or not stat.S_ISREG(found.st_mode):
        raise LocaleError("not_a_file")
    if candidate.resolve().parent != root:
        raise LocaleError("not_a_file")
    return candidate


def _read(path: Path) -> bytes:
    """The bytes of a plain file, at most one more than allowed; opened without following a link where the system
    can, so a file swapped for a link after the check is not read either."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        handle = os.open(path, flags)
    except OSError as exc:
        if path.is_symlink():
            raise LocaleError("not_a_file") from exc
        raise
    with os.fdopen(handle, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise LocaleError("not_a_file")
        return file.read(MAX_BYTES + 1)


def load(code: str) -> dict[str, Any]:
    """The texts of one of the operator's files, without ``_meta``. ``FileNotFoundError`` or ``LocaleError`` when
    there is none or it is not usable."""
    return parse(_read(_path_for(code))).texts


#: What ``available`` found per file, keyed by name, valid while size, change time and inode stay the same. The list
#: is asked for on every page load; without this every file would be read in full each time, and a broken one would be
#: warned about each time.
_seen: dict[str, tuple[tuple[int, int, int], Locale | None]] = {}


def forget() -> None:
    """Drop what ``available`` remembered (after ``configure``; for tests that write the same names again)."""
    _seen.clear()


def available() -> list[Locale]:
    """Every usable file of the operator, sorted by code (nexnotes' list). Broken ones are skipped and logged once
    per state of the file."""
    directory = locales_dir()
    if not directory.is_dir():
        _seen.clear()
        return []
    files = sorted(path for path in directory.iterdir() if path.suffix == ".json")
    if len(files) > MAX_FILES:
        current().logger.warning("Language folder holds %d files, only the first %d are read", len(files), MAX_FILES)
        files = files[:MAX_FILES]
    for name in set(_seen) - {path.name for path in files}:
        del _seen[name]
    result: list[Locale] = []
    for path in files:
        try:
            found = path.lstat()
        except OSError:
            continue
        # The inode as well: a file written anew within the same clock tick at the same size is still new.
        state = (found.st_size, found.st_mtime_ns, found.st_ino)
        known = _seen.get(path.name)
        if known is None or known[0] != state:
            known = (state, _examine(path))
            _seen[path.name] = known
        if known[1] is not None:
            result.append(known[1])
    return result


def _examine(path: Path) -> Locale | None:
    code = path.stem
    try:
        parsed = parse(_read(_path_for(code)))
    except FileNotFoundError:
        return None
    except (LocaleError, OSError) as exc:
        current().logger.warning("Language file name=%s skipped: %s", path.name[:80], exc)
        return None
    return Locale(code=code, name=parsed.name or code, keys=parsed.keys)


def languages() -> list[Language]:
    """The list of the page and the menus: the built-in languages in the app's order, each with its own file if the
    operator laid one over it, then the operator's further languages by code."""
    config = current()
    own = {locale.code: locale for locale in available()}
    found = [
        Language(code=code, name=name, keys=own[code].keys if code in own else 0, built_in=True, own=code in own)
        for code, name in config.built_in.items()
    ]
    found += [
        Language(code=locale.code, name=locale.name, keys=locale.keys, built_in=False, own=True)
        for code, locale in own.items()
        if code not in config.built_in
    ]
    return found


def known(code: str) -> bool:
    """Whether the app speaks ``code``: built in or one of the operator's usable files (for a profile's language)."""
    return code in current().built_in or any(locale.code == code for locale in available())


def save(code: str, raw: bytes) -> Locale:
    """A file from the operator's upload: checked whole like one laid into the folder, then written under a passing
    name and moved into place. ``LocaleError`` for an unusable file, ``SaveError`` when it could not be written; in
    both cases nothing changes in the folder."""
    if not valid_code(code):
        raise LocaleError("code")
    parsed = parse(raw)
    config = current()
    directory = locales_dir()
    target = directory / f"{code}.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        found = target.lstat()
    except FileNotFoundError:
        found = None
    except OSError as exc:
        raise SaveError("the folder is not usable") from exc
    if found is not None and not stat.S_ISREG(found.st_mode):
        raise LocaleError("not_a_file")
    passing = ""
    try:
        with _writing:
            handle, passing = tempfile.mkstemp(dir=directory, prefix=f".{code}.", suffix=".part")
            with os.fdopen(handle, "wb") as file:
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            os.replace(passing, target)
    except OSError as exc:
        if passing:
            with contextlib.suppress(OSError):
                os.unlink(passing)
        config.logger.warning("Language file name=%s not saved: %s", target.name, exc.__class__.__name__)
        raise SaveError("not written") from exc
    config.logger.info("Language file name=%s saved keys=%s", target.name, parsed.keys)
    return Locale(code=code, name=parsed.name or code, keys=parsed.keys)


def tidy_at_start() -> int:
    """**The app calls it at its start**, right after ``configure``: removes what a stopped process left of an upload,
    the hidden plain files named like ``PASSING_PATTERN`` (``.nl.k3j9x_2a.part``), whatever their age. Never a
    language file, a link, a folder or any other name. Calling it again is harmless; while an upload of this process
    writes, it leaves everything as it is. Returns how many it removed."""
    directory = locales_dir()
    if not directory.is_dir() or not _writing.acquire(blocking=False):
        return 0
    removed = 0
    try:
        for path in directory.iterdir():
            if not PASSING_PATTERN.fullmatch(path.name):
                continue
            try:
                if not stat.S_ISREG(path.lstat().st_mode):
                    continue
                path.unlink()
            except OSError:
                continue
            removed += 1
    finally:
        _writing.release()
    if removed:
        current().logger.info("Removed %d unfinished language upload(s) left by a stopped process", removed)
    return removed


def remove(code: str) -> bool:
    """Remove one of the operator's files; False when there is none (or it is a link, which stays)."""
    try:
        path = _path_for(code)
    except (FileNotFoundError, LocaleError):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    current().logger.info("Language file name=%s removed", path.name)
    return True


def texts_only(tree: Mapping[str, Any], depth: int = 1) -> dict[str, Any]:
    """Since 1.0.2 (E59): what of ``tree`` a language file may carry, so that the template the app offers is taken by
    its own upload: texts and groups of texts, at most ``MAX_DEPTH`` levels, keys neither empty, nor longer than
    ``MAX_KEY``, nor reserved, nor ``_meta`` at the top; lists, numbers, null and empty groups are left out (they
    show in English, as every text a file leaves out). The same rules as ``textsOnly`` on the page."""
    kept: dict[str, Any] = {}
    for key, value in tree.items():
        if (not isinstance(key, str) or not key or len(key) > MAX_KEY or key in RESERVED_KEYS or not _encodable(key)
                or (depth == 1 and key == META_KEY)):
            continue
        if isinstance(value, str):
            if _encodable(value):
                kept[key] = value
        elif isinstance(value, Mapping) and depth < MAX_DEPTH:
            group = texts_only(value, depth + 1)
            if group:
                kept[key] = group
    return kept


def template() -> dict[str, Any] | None:
    """The template to translate: ``_meta`` with a hint for the name, then the app's texts in the fallback language,
    only what a language file may carry (``texts_only``, since 1.0.2). None when the app makes the template on its
    page."""
    given = current().template
    if given is None:
        return None
    texts: Mapping[str, Any] = given()
    return {META_KEY: {"name": "Name of the language in itself, for example Nederlands"}, **texts_only(texts)}
