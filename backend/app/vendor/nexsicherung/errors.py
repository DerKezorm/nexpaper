"""The fixed error codes of the module. A route answers them as ``{"detail": {"code", "message"}}`` (or through the
app's own ``error`` maker); the page shows ``sicherung.error.<code>``."""

from __future__ import annotations

#: code -> HTTP status. The codes the apps' backup routes answered before stay the same (``not_found``,
#: ``backup_invalid``, ``backup_damaged``, ``backup_too_new``, ``backup_too_large``, ``backup_running``, ``empty``).
CODES: dict[str, int] = {
    "not_found": 404,
    "empty": 400,
    "backup_invalid": 400,
    "backup_damaged": 400,
    "backup_too_new": 400,
    "backup_too_large": 413,
    "backup_running": 409,
    "backup_blocked": 400,
    "backup_disk_full": 507,
    "backup_write_failed": 507,
    "archive_password_needed": 400,
    "archive_password_wrong": 400,
    "archive_password_short": 400,
    "restore_options_invalid": 422,
    "schedule_invalid": 422,
    "time_invalid": 422,
    "keep_invalid": 422,
}


class BackupError(Exception):
    """A refusal with a fixed code. ``text`` is English, for the log and for clients without the page's words.
    ``status`` follows the code unless given."""

    def __init__(self, code: str, text: str, status: int | None = None) -> None:
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = status if status is not None else CODES.get(code, 400)
