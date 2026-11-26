"""The module's refusals: a code, an English message, an HTTP status. The walls of ``/api/mcp`` keep the codes and
statuses each app answered so far (``AppConfig.off_status``, ``off_code``, ``invalid_code``); everything else is the
same in every app. A refusal of a tool is no refusal here: it is the tool's answer with ``isError`` (``ToolError``)."""

from __future__ import annotations

#: code -> (status, message).
CODES: dict[str, tuple[int, str]] = {
    "origin_refused": (403, "MCP is not for web pages."),
    "not_found": (404, "Not found."),
    "mcp_off": (403, "The operator has switched MCP off."),
    "too_many_attempts": (429, "Too many wrong keys. Try again later."),
    "key_invalid": (401, "No valid key."),
    "token_invalid": (401, "No valid key."),
    "ai_rests": (401, "This key works once the operator lets its account use AI again."),
    "slow_down": (429, "Too many requests with this key. Wait a minute."),
    "protocol_version": (400, "This MCP protocol version is not spoken here."),
    "too_large": (413, "The request is too large."),
    # the account's own pages
    "key_unknown": (404, "No such key."),
    "right_invalid": (422, "A right is allow, ask or deny."),
    "tool_unknown": (422, "There is no such tool here."),
    "level_invalid": (422, "There is no such level here."),
    "request_unknown": (404, "No such request."),
    "request_decided": (409, "This request was decided already."),
    "request_changed": (409, "The request was changed after it was asked. It does not run."),
    "request_expired": (409, "This request ran out."),
    "confirm_needed": (409, "This one is dangerous: confirm it once more."),
    # consent (OAuth)
    "programs_off": (404, "Connecting programs is switched off here."),
    "client_unknown": (400, "This program is not known here. Connect it again from the program."),
    "redirect_invalid": (400, "This return address does not belong to the program."),
    "pkce_required": (400, "The program must use PKCE with S256."),
    "response_type": (400, "Only the response type code is supported."),
    "resource_invalid": (400, "The program asks for access to something other than this app."),
    "areas_invalid": (422, "One of them is not yours to give."),
    "extra_invalid": (422, "There is no such extra here."),
    "ai_not_allowed": (403, "The operator does not let this account use AI."),
}


class McpRefused(Exception):  # noqa: N818 (a refusal, not a fault)
    def __init__(self, code: str, *, status: int | None = None, **details: object) -> None:
        known_status, message = CODES[code]
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or known_status
        self.details = details

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, **self.details}


class ToolError(Exception):
    """A tool that cannot do what it was asked: the text goes back as the tool's answer (``isError``), in English."""


class OAuthError(Exception):  # noqa: N818
    """An answer of the token and registration endpoints in the form of RFC 6749 (``error``, ``error_description``)."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status

    def as_dict(self) -> dict[str, str]:
        return {"error": self.error, "error_description": self.description}
