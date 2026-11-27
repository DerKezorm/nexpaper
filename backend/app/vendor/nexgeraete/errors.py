"""The module's refusals (G12): a code, an English message, an HTTP status. The old forms of the app routes name them
otherwise (``forms.py``); the browser routes and every request with ``X-Nex-App`` hear these."""

from __future__ import annotations

#: code -> (status, message). Messages English (the outside is English); the pages and apps show their own words.
CODES: dict[str, tuple[int, str]] = {
    "device_disconnected": (401, "This device was disconnected. Connect it again."),
    "account_blocked": (401, "This account is blocked or deleted."),
    "second_factor_required": (401, "Set up your second factor in the browser first, then connect again."),
    "app_disabled": (403, "The operator has switched the app off."),
    "app_pairing_disabled": (403, "The operator does not let new devices connect."),
    "browser_only": (403, "Only in the browser."),
    "pairing_gone": (410, "This code has expired, was used already, or is not valid."),
    "too_many_attempts": (429, "Too many attempts. Try again later."),
    #: Only inside the module: the public code is ``too_many_attempts`` (nexmail ``app_zu_viele_geraete``).
    "too_many_new_devices": (429, "Too many new devices in an hour. Try again later."),
    "too_many_pairings": (409, "Too many codes are waiting already."),
    "too_many_devices": (409, "This account has as many devices as it may."),
    "not_found": (404, "Not found."),
    "name_invalid": (422, "The name is empty, too long, or holds control characters."),
    "invalid_input": (422, "The input is not valid."),
    "push_ticket_invalid": (422, "The ticket or the key is not usable."),
    "kind_unknown": (422, "There is no such kind of notification here."),
    "app_address_missing": (422, "The server does not know its address. The operator sets it."),
}

#: What the module's codes are called in the form ``nex`` where they differ.
PUBLIC: dict[str, str] = {"too_many_new_devices": "too_many_attempts"}


class DeviceRefused(Exception):  # noqa: N818 (a refusal, not a fault)
    def __init__(self, code: str, *, retry_after: int | None = None, **values: object) -> None:
        status, message = CODES[code]
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.retry_after = retry_after
        self.values = values

    @property
    def public_code(self) -> str:
        return PUBLIC.get(self.code, self.code)

    def as_dict(self) -> dict[str, object]:
        """The body's ``detail`` in the form ``nex``: ``{"code", "message", …values}``."""
        return {"code": self.public_code, "message": self.message, **self.values}

    @property
    def headers(self) -> dict[str, str] | None:
        return {"Retry-After": str(self.retry_after)} if self.retry_after is not None else None


#: The refusals of a device's key: the old forms make one of them (``not_signed_in``, ``nicht_angemeldet``).
SIGNED_OUT = ("device_disconnected", "account_blocked", "second_factor_required")
