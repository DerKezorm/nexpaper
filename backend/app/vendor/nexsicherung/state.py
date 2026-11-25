"""What the module remembers between starts, in one small file beside the backups (``sicherung-state.json``, only the
owner's): the last failure of a copy, the last scheduled attempt, a restore that failed at the start, the last
restore. Not in the app's database: a restore swaps the database, and what happened around it must survive that."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from . import tools
from .config import current

FILE = "sicherung-state.json"
_lock = threading.Lock()


def read() -> dict[str, Any]:
    path = current().backups / FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def update(**changes: Any) -> dict[str, Any]:
    """Merge ``changes`` into the file (None removes a key), written whole under a new name and swapped in."""
    with _lock:
        folder = tools.private_folder(current().backups)
        state = read()
        for key, value in changes.items():
            if value is None:
                state.pop(key, None)
            else:
                state[key] = value
        temporary = folder / f".{FILE}.{os.getpid()}.part"
        tools.new_file(temporary)
        temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, folder / FILE)
        return state
