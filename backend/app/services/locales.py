"""The operator's own languages: JSON files in ``<data_dir>/locales``.

English and German ship inside the frontend. Every further language is one file named after its code
(``es.json``, ``pt-BR.json``) that holds the same keys as the frontend's ``en.json``; what it leaves out falls
back to English in the browser. A file for ``en`` or ``de`` is laid over the shipped texts, so a wording can be
changed without a new release.

The files come from outside, so nothing in them is trusted:

* The code is checked against a strict pattern before it becomes a path. Nothing outside the directory is read,
  links included.
* A file is at most ``MAX_BYTES`` and at most ``MAX_DEPTH`` levels deep; every leaf is a string. The frontend
  renders the texts as text, never as HTML.
* A broken file is skipped and named in the log; it never stops the others or the start of the app.

An optional ``"_meta": {"name": "Español"}`` gives the name shown in the language menu.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger("nexpaper.locales")

#: ``de``, ``es``, ``fil``, ``pt-BR``, ``zh-Hant``: a language, then optionally a region or a script.
CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}))?$")
MAX_BYTES = 512 * 1024
MAX_DEPTH = 8
MAX_NAME = 60
#: More would be a directory somebody filled by mistake; the menu has no room for it either.
MAX_FILES = 200
META_KEY = "_meta"


class LocaleError(ValueError):
    """Why a file is not usable. The message is English and names no content."""


@dataclass(frozen=True)
class Locale:
    code: str
    name: str
    keys: int


def locales_dir() -> Path:
    directory = get_settings().locales_dir
    if directory is None:  # the settings validator fills it; this only satisfies the type
        raise RuntimeError("locales_dir is not set")
    return directory


def valid_code(code: str) -> bool:
    return bool(CODE_PATTERN.match(code))


def _count_leaves(value: Any, depth: int = 1) -> int:
    if depth > MAX_DEPTH:
        raise LocaleError(f"nested deeper than {MAX_DEPTH} levels")
    if isinstance(value, str):
        return 1
    if isinstance(value, dict):
        total = 0
        for key, child in value.items():
            if not key or len(key) > 120:
                raise LocaleError("a key is empty or longer than 120 characters")
            total += _count_leaves(child, depth + 1)
        return total
    raise LocaleError(f"a value is {type(value).__name__}, only text and groups of text are allowed")


def _path_for(code: str) -> Path:
    """The file for a code, or LocaleError. Never a path outside the directory."""
    if not valid_code(code):
        raise LocaleError("not a language code")
    root = locales_dir().resolve()
    candidate = root / f"{code}.json"
    if candidate.is_symlink():
        raise LocaleError("a link, not a file")
    resolved = candidate.resolve()
    if resolved.parent != root:
        raise LocaleError("outside the language directory")
    if not resolved.is_file():
        raise FileNotFoundError(code)
    return resolved


def _parse(path: Path) -> tuple[dict[str, Any], str, int]:
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise LocaleError(f"{size} bytes, the limit is {MAX_BYTES}")
    return _parse_bytes(path.read_bytes())


def _parse_bytes(raw: bytes) -> tuple[dict[str, Any], str, int]:
    if len(raw) > MAX_BYTES:
        raise LocaleError(f"{len(raw)} bytes, the limit is {MAX_BYTES}")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise LocaleError("not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise LocaleError(f"not valid JSON (line {exc.lineno})") from exc
    if not isinstance(data, dict):
        raise LocaleError("the top level is not an object")
    meta = data.pop(META_KEY, None)
    name = ""
    if meta is not None:
        if not isinstance(meta, dict) or not isinstance(meta.get("name", ""), str):
            raise LocaleError(f"{META_KEY} must be an object with a text 'name'")
        name = meta.get("name", "").strip()[:MAX_NAME]
    keys = _count_leaves(data)
    if keys == 0:
        raise LocaleError("no texts")
    return data, name, keys


def load(code: str) -> dict[str, Any]:
    """The texts of one language, without ``_meta``. FileNotFoundError or LocaleError when not usable."""
    data, _name, _keys = _parse(_path_for(code))
    return data


#: What ``available`` found per file, keyed by name, valid while size and change time stay the same. The list is
#: asked for on every page load; without this every file would be read in full each time, and a broken one would be
#: warned about each time.
_seen: dict[str, tuple[tuple[int, int, int], Locale | None]] = {}


def forget() -> None:
    """Drop what ``available`` remembered; for tests that write files under the same names again and again."""
    _seen.clear()


def available() -> list[Locale]:
    """Every usable language file, sorted by code. Broken ones are skipped and logged once per state of the file."""
    directory = locales_dir()
    if not directory.is_dir():
        _seen.clear()
        return []
    result: list[Locale] = []
    files = sorted(p for p in directory.iterdir() if p.suffix == ".json")
    if len(files) > MAX_FILES:
        logger.warning("Language directory holds %d files, only the first %d are read", len(files), MAX_FILES)
        files = files[:MAX_FILES]
    for name in set(_seen) - {path.name for path in files}:
        del _seen[name]
    for path in files:
        try:
            stat = path.lstat()
        except OSError:
            continue
        # The inode as well: a file written anew within the same clock tick at the same size is still new.
        state = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
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
        _data, name, keys = _parse(_path_for(code))
    except FileNotFoundError:
        return None
    except (LocaleError, OSError) as exc:
        logger.warning("Language file %s skipped: %s", path.name, exc)
        return None
    return Locale(code=code, name=name or code, keys=keys)


def save(code: str, raw: bytes) -> Locale:
    """A language file from the operator's upload: checked like one laid into the directory, then written whole."""
    if not valid_code(code):
        raise LocaleError("not a language code")
    _data, name, keys = _parse_bytes(raw)
    directory = locales_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{code}.json"
    if target.is_symlink():
        raise LocaleError("a link, not a file")
    partial = directory / f".{code}.json.part"
    partial.write_bytes(raw)
    partial.replace(target)
    logger.info("Language file %s saved keys=%s", target.name, keys)
    return Locale(code=code, name=name or code, keys=keys)


def remove(code: str) -> bool:
    try:
        path = _path_for(code)
    except (FileNotFoundError, LocaleError):
        return False
    path.unlink()
    logger.info("Language file %s removed", path.name)
    return True
