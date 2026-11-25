"""nexlog: the server log of every nex app, the same everywhere.

Vendored unchanged into ``backend/app/vendor/nexlog/``; a test in the app compares the files with the checksums in
``MANIFEST.json``, so a change is made in the module's source, never in the copy.

- ``config``: the app's name, folder, environment variable, clock and extra rules (``configure(AppConfig(...))``);
- ``masking``: one line per record, keys, tokens and passwords blacked out;
- ``context``: request number and account in every line (``bind_request``, ``set_actor``);
- ``handlers``: the file that rolls over, the console, the four levels (``setup``, ``apply_mode``, ``clear``);
- ``modes``: the stored level and its end, the environment, the watchdog (``attach_store``, ``set_mode``, ``state``);
- ``files``: reading (newest first, filters, pages, older files), the download, the retention;
- ``api``: the routes for the page (needs FastAPI; imported only by ``from app.vendor.nexlog import api``).

The names of nexnotes' ``services/logs.py`` stand here unchanged, so an app's ``services/logs.py`` may become
``from app.vendor.nexlog import *``.
"""

from __future__ import annotations

from . import context, files, handlers, masking, modes
from .config import AppConfig, configure, current
from .context import (
    bind_request,
    current_actor,
    current_request_id,
    new_request_id,
    set_actor,
    unbind_request,
)
from .files import (
    BACKUP_COUNT,
    DATE_FORMAT,
    DOWNLOAD_LIMIT,
    LEVEL_ORDER,
    LINE_PATTERN,
    LOG_FORMAT,
    MAX_BYTES_DEEP,
    MAX_BYTES_NORMAL,
    RETENTION_DAYS,
    LogLine,
    download_name,
    download_text,
    log_dir,
    log_file,
    moment_of,
    parse_line,
    purge_old,
    read,
    rotated_files,
)
from .handlers import (
    DEEP_MODES,
    DEFAULT_MODE,
    MODES,
    NOISY_LOGGERS,
    SILENT_LOGGERS,
    apply_mode,
    clear,
    current_mode,
    setup,
    shutdown,
)
from .masking import one_line, redact, shorten_address
from .modes import (
    ALLOWED_MINUTES,
    PAGE_MINUTES,
    ModeState,
    apply_stored_mode,
    attach_store,
    detach_store,
    enforce_expiry,
    env_mode,
    normalize_mode,
    normalize_until,
    run_forever,
    set_mode,
    state,
)

__version__ = "1.0.0"

__all__ = [
    "ALLOWED_MINUTES",
    "BACKUP_COUNT",
    "DATE_FORMAT",
    "DEEP_MODES",
    "DEFAULT_MODE",
    "DOWNLOAD_LIMIT",
    "LEVEL_ORDER",
    "LINE_PATTERN",
    "LOG_FORMAT",
    "MAX_BYTES_DEEP",
    "MAX_BYTES_NORMAL",
    "MODES",
    "NOISY_LOGGERS",
    "PAGE_MINUTES",
    "RETENTION_DAYS",
    "SILENT_LOGGERS",
    "AppConfig",
    "LogLine",
    "ModeState",
    "__version__",
    "apply_mode",
    "apply_stored_mode",
    "attach_store",
    "bind_request",
    "clear",
    "configure",
    "context",
    "current",
    "current_actor",
    "current_mode",
    "current_request_id",
    "detach_store",
    "download_name",
    "download_text",
    "enforce_expiry",
    "env_mode",
    "files",
    "handlers",
    "log_dir",
    "log_file",
    "masking",
    "modes",
    "moment_of",
    "new_request_id",
    "normalize_mode",
    "normalize_until",
    "one_line",
    "parse_line",
    "purge_old",
    "read",
    "redact",
    "rotated_files",
    "run_forever",
    "set_actor",
    "set_mode",
    "setup",
    "shorten_address",
    "shutdown",
    "state",
    "unbind_request",
]
