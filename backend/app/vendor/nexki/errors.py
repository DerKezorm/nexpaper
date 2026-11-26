"""The module's refusals: a fixed code, an English sentence for whoever uses the API directly, an HTTP status, and the
values the interface fills into its own words (``seconds``, ``answered``, ``said``). The interface has its words in
``ki.<language>.json``; the codes never change."""

from __future__ import annotations

#: code -> (status, message).
CODES: dict[str, tuple[int, str]] = {
    # the chain of switches, in its order
    "ai_off": (409, "No AI is set up or allowed on this server."),
    "ai_not_allowed": (403, "Your operator has not allowed the AI for your account."),
    "ai_switched_off": (403, "You switched the AI off for yourself."),
    "ai_app_refused": (403, "The AI is not allowed for this."),
    "ai_incomplete": (409, "The AI service is not set up completely."),
    "ai_own_off": (409, "Accounts do not set up their own AI service on this server."),
    # the address
    "ai_api_unknown": (422, "There is no such kind of AI interface."),
    "ai_mode_unknown": (422, "There is no such way to set up the AI."),
    "ai_address_missing": (422, "Give the address of the service."),
    "ai_address_invalid": (422, "This is not an address of a service."),
    "ai_https_required": (422, "A service on the internet is reached over https only."),
    "ai_address_refused": (422, "This address is never reached."),
    "ai_address_private": (422, "This address lies in the own network, and the operator has not listed its host."),
    "ai_address_mixed": (422, "This name points into the own network and onto the internet at once."),
    "ai_hosts_invalid": (422, "One of the hosts is not a host name or address."),
    # the request
    "ai_unreachable": (502, "The server cannot reach the AI service."),
    "ai_timeout": (504, "The AI service took too long."),
    "ai_key_refused": (502, "The AI service refused the key."),
    "ai_address_not_found": (502, "The AI service does not know this address."),
    "ai_service_busy": (502, "The AI service is busy. Try again in a moment."),
    "ai_service_failed": (502, "The AI service answered with an error."),
    "ai_unreadable": (502, "The answer of the AI service could not be read."),
    "ai_empty": (502, "The AI service gave back nothing."),
    "ai_used_up": (
        502,
        "The model used up its room for an answer before it wrote one. A thinking model needs its thinking switched "
        "off.",
    ),
    "ai_no_list": (422, "This service lists no models; type the name of the model."),
    "ai_no_models": (422, "This service offers no models."),
    # the brakes
    "ai_too_often": (429, "Too many requests to the AI. Wait a little."),
    "ai_day_used": (429, "The requests to the AI for today are used up."),
    "ai_busy": (409, "The AI is already working on a request of yours."),
    "ai_server_busy": (503, "The AI is busy right now. Try again in a moment."),
    "ai_task_unknown": (422, "There is no such task."),
}

#: The order of the chain of switches: the first that says no is the reason given.
CHAIN = ("ai_off", "ai_not_allowed", "ai_switched_off", "ai_app_refused", "ai_own_off", "ai_incomplete")


class AiRefused(Exception):  # noqa: N818 (a refusal, not a fault)
    """A refusal with its code. ``values`` go to the interface (``seconds``, ``answered``, ``said``)."""

    def __init__(self, code: str, *, status: int | None = None, **values: object) -> None:
        known_status, message = CODES[code]
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or known_status
        self.values = values

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, **self.values}
