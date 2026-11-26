"""The module's refusals: a code, an English message, an HTTP status. An app whose answers had other codes or statuses
keeps them (``AppConfig.error_codes``, ``AppConfig.error_status``): the module's code travels along as
``key_code``."""

from __future__ import annotations

from .config import AppConfig

#: code -> (status, message). Messages English (the outside is English); the page shows its own words per code.
CODES: dict[str, tuple[int, str]] = {
    "api_off": (403, "The operator has switched the programming interface off."),
    "mcp_off": (403, "The operator has switched MCP access off."),
    "token_invalid": (401, "This key is not valid."),
    "second_factor_required": (401, "This key works once its account has a second factor."),
    "kind_unknown": (404, "There is no such kind of key here."),
    "kind_not_creatable": (403, "Keys of this kind are not made by hand here."),
    "key_not_editable": (403, "Keys of this kind cannot be changed."),
    "name_missing": (422, "Give the key a name."),
    "name_too_long": (422, "The name is too long."),
    "right_invalid": (422, "This right is not offered."),
    "option_invalid": (422, "This extra is not offered."),
    "option_retired": (422, "This extra is no longer offered for keys; switch it off, or make an MCP key."),
    "ai_not_allowed": (403, "The operator does not let this account use AI."),
    "ai_rests": (401, "This key works once the operator lets its account use AI again."),
    "choose_areas": (422, "Choose at least one."),
    "areas_invalid": (422, "One of them is not yours to give."),
    "days_invalid": (422, "This lifetime is not offered."),
    "too_many_keys": (409, "This account has as many keys as it may."),
    "not_found": (404, "No such key."),
    "switch_unknown": (422, "There is no such switch here."),
}


class KeyRefused(Exception):  # noqa: N818 (a refusal, not a fault)
    def __init__(self, code: str, *, config: AppConfig | None = None, **details: object) -> None:
        status, message = CODES[code]
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.public_code = config.public_code(code) if config else code
        self.status = config.error_status.get(code, status) if config else status

    def as_dict(self) -> dict[str, object]:
        """The body of the answer: ``{"code", "message", …details}``; ``key_code`` where the app names it otherwise."""
        body: dict[str, object] = {"code": self.public_code, "message": self.message, **self.details}
        if self.public_code != self.code:
            body["key_code"] = self.code
        return body
