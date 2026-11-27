"""The three forms of the app routes (G4, G5). A request with ``X-Nex-App`` is answered in ``nex``; one without it in
the app's old form, so that the published iPhone apps notice nothing:

- ``nex`` (nexnotes, nextime): ``{token, key, account{id,name,login,email,avatar,operator}, account_id, device}``,
  errors ``{"detail": {"code", "message"}}`` with the codes of G12, ``PUT/DELETE push`` 204;
- ``tasks`` (nextasks, nexlore): ``{key, account{id, name}}``, ``404 app_pairing_unknown``, ``401 not_signed_in``,
  ``429 too_many``, ``409 app_too_many_pairings``, ``PUT/DELETE push`` 200 ``{"status": "ok"}``;
- ``mail`` (nexmail): ``{key, account{id as text, name}}``, ``{"detail": "<code>", "werte": {…}}`` with
  ``app_kopplung_unbekannt``, ``nicht_angemeldet``, ``app_abgeschaltet``, ``zu_viele_versuche``,
  ``app_zu_viele_geraete``, ``kein_gueltiger_schluessel``.

Routes only the new apps call (the list, renaming, the kinds) answer in ``nex`` whatever the form."""

from __future__ import annotations

from typing import Any

from .config import CLIENT_HEADER, FORM_MAIL, FORM_NEX, FORM_TASKS, AppConfig
from .errors import SIGNED_OUT, DeviceRefused
from .model import Device, Holder

Answer = tuple[int, Any, dict[str, str] | None]

#: code -> (status, code, message) in the form ``tasks``; codes missing here keep the module's.
_TASKS: dict[str, tuple[int, str, str]] = {
    "pairing_gone": (404, "app_pairing_unknown", "No such pairing."),
    "too_many_attempts": (429, "too_many", "Too many attempts. Try again later."),
    "too_many_new_devices": (429, "too_many", "Too many new devices in an hour. Try again later."),
    "too_many_pairings": (409, "app_too_many_pairings", "At most 5 pairings may wait at once."),
    "push_ticket_invalid": (422, "invalid_input", "The input is not valid."),
    **{code: (401, "not_signed_in", "No valid device key.") for code in SIGNED_OUT},
}
#: code -> (status, code) in the form ``mail``.
_MAIL: dict[str, tuple[int, str]] = {
    "pairing_gone": (404, "app_kopplung_unbekannt"),
    "app_disabled": (403, "app_abgeschaltet"),
    "app_pairing_disabled": (403, "app_abgeschaltet"),
    "too_many_attempts": (429, "zu_viele_versuche"),
    "too_many_new_devices": (429, "app_zu_viele_geraete"),
    "too_many_pairings": (409, "app_zu_viele_kopplungen"),
    "too_many_devices": (409, "app_zu_viele_geraete"),
    "push_ticket_invalid": (400, "kein_gueltiger_schluessel"),
    "not_found": (404, "nicht_gefunden"),
    **{code: (401, "nicht_angemeldet") for code in SIGNED_OUT},
}


def form_of(config: AppConfig, headers: Any) -> str:
    """``nex`` with ``X-Nex-App``, else the app's old form."""
    return FORM_NEX if headers.get(CLIENT_HEADER) else config.form


def refusal(form: str, refused: DeviceRefused) -> Answer:
    """Status, body and headers of a refusal in ``form``."""
    if form == FORM_TASKS and refused.code in _TASKS:
        status, code, message = _TASKS[refused.code]
        values: dict[str, Any] = dict(refused.values)
        if refused.code == "push_ticket_invalid":
            values = {"fields": ["key"]}
        return status, {"detail": {"code": code, "message": message, **values}}, refused.headers
    if form == FORM_MAIL:
        status, code = _MAIL.get(refused.code, (refused.status, refused.public_code))
        body: dict[str, Any] = {"detail": code}
        if refused.values and refused.code != "push_ticket_invalid":
            body["werte"] = {key: value for key, value in refused.values.items() if key != "fields"}
        return status, body, refused.headers
    return refused.status, {"detail": refused.as_dict()}, refused.headers


def account_out(holder: Holder) -> dict[str, Any]:
    """The account as the form ``nex`` names it (nexnotes ``account_out``)."""
    return {
        "id": holder.id,
        "name": holder.name,
        "login": holder.login,
        "email": holder.email,
        "avatar": holder.avatar,
        "operator": holder.operator,
    }


def paired(form: str, token: str, holder: Holder, device: Device, entry: dict[str, Any], *, sibling: bool) -> Answer:
    """The answer to a new device: QR code, code and sibling answer alike within a form. ``Cache-Control:
    no-store``: a key must not stay behind in any cache."""
    headers = {"Cache-Control": "no-store"}
    if form == FORM_TASKS:
        return 200, {"key": token, "account": {"id": holder.id, "name": holder.name}}, headers
    if form == FORM_MAIL:
        return 200, {"key": token, "account": {"id": str(holder.id), "name": holder.name}}, headers
    body = {"token": token, "key": token, "account": account_out(holder), "account_id": holder.id, "device": entry}
    return (201 if sibling else 200), body, headers


def done(form: str) -> Answer:
    """``PUT``/``DELETE push``: 204 in ``nex``, ``{"status": "ok"}`` in the old forms."""
    if form in (FORM_TASKS, FORM_MAIL):
        return 200, {"status": "ok"}, None
    return 204, None, None
