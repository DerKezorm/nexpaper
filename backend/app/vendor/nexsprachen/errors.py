"""The fixed codes of the module's refusals and the reasons a file is not usable. A route answers
``{"detail": {"code", "message", …values}}`` (nexnotes' form, or the app's own through ``error``); the page shows
``errors.<code>`` and, for ``locale_unusable``, ``reasons.<reason>`` in the module's words. No refusal names a path, a
file name, a line of the file or a message of the parser."""

from __future__ import annotations

#: code -> HTTP status. The codes nexnotes' routes answered stay the same (``not_found``, ``locale_unusable``,
#: ``too_large``).
CODES: dict[str, int] = {
    "not_found": 404,
    "locale_unusable": 422,
    "too_large": 413,
    "locale_not_saved": 500,
}

#: reason -> the English words after "This language file cannot be used: ". The reasons say what is wrong with the
#: file in general terms, never where or with which content.
REASONS: dict[str, str] = {
    "code": "not a language code",
    "not_utf8": "not UTF-8 text",
    "not_json": "not valid JSON",
    "not_object": "the top level is not an object",
    "too_deep": "nested deeper than 8 levels",
    "not_text": "only texts and groups of texts are allowed",
    "key_invalid": "a key is empty, longer than 120 characters or reserved",
    "no_texts": "no texts",
    "meta_invalid": "_meta must be an object with a text 'name'",
    "too_large": "larger than 512 KB",
    "not_a_file": "not a plain file",
}


class LocaleError(ValueError):
    """Why a file is not usable: ``reason`` (one of ``REASONS``) and its English words, which name no content."""

    def __init__(self, reason: str) -> None:
        if reason not in REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        super().__init__(REASONS[reason])
        self.reason = reason


class SaveError(OSError):
    """The file was fine but could not be written (disk full, no rights). Nothing of it is left behind."""
