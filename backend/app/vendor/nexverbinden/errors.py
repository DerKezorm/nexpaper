"""The module's refusals: a code, an English message, an HTTP status, in the form every app answers
(``{"detail": {"code", "message"}}``). A refusal of a partner never goes on as 401 to the own page (the browser would
sign the account out): what a partner said becomes a code here with status 409, and anything on the way 502."""

from __future__ import annotations

#: code -> (status, message).
CODES: dict[str, tuple[int, str]] = {
    # the account's page
    "partner_unknown": (404, "This app does not connect with that one."),
    "not_connected": (404, "Not connected."),
    "address_invalid": (422, "This is not an address of a nex app."),
    "address_port": (422, "Ports below 1024 other than 80 and 443 are not asked."),
    "address_refused": (422, "This address is never asked."),
    "wrong_app": (409, "Another app answers at this address."),
    "partner_too_old": (409, "The app at this address cannot connect this way yet. Connect it by hand."),
    "partner_off": (409, "The operator of the other app has switched connections off."),
    "unreachable": (502, "The other app cannot be reached right now."),
    "refused": (409, "The other app does not take this connection any more."),
    "resting": (409, "The other app lets this connection rest."),
    "consent_failed": (409, "The other app did not confirm the connection. Connect again."),
    "slow_down": (429, "Too many tries. Wait a minute."),
    "return_invalid": (400, "This return does not belong to a connection started here. Connect again."),
    "connections_off": (403, "The operator has switched connections with other nex apps off."),
    # the consent page
    "client_invalid": (400, "The app that asks cannot be checked."),
    "redirect_invalid": (400, "This return address does not belong to the app that asks."),
    "pkce_required": (400, "The app that asks must use PKCE with S256."),
    "areas_invalid": (422, "One of them is not yours to give."),
    # between the apps
    "origin_refused": (403, "This is not for web pages."),
    "token_invalid": (401, "No valid connection."),
    "account_resting": (401, "The account rests on this side."),
    "purpose_missing": (403, "The connection does not allow this."),
}


class Refused(Exception):  # noqa: N818 (a refusal, not a fault)
    def __init__(self, code: str, *, status: int | None = None, **details: object) -> None:
        known_status, message = CODES[code]
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or known_status
        self.details = details

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, **self.details}


class GrantError(Exception):
    """An answer of the token route in the form of RFC 6749 (``error``, ``error_description``); ``error`` may be one of
    the module's own (``account_resting``, ``connection_resting``, ``connections_off``) so that the other side knows
    which state to show."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status

    def as_dict(self) -> dict[str, str]:
        return {"error": self.error, "error_description": self.description}
