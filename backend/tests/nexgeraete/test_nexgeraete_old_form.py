"""The published iPhone apps notice nothing (G4, G5): their calls, without ``X-Nex-App``, answered exactly as before,
in the app's form. ``nex``: nexnotes-ios 1.0.0 (``{token, account, device}``, ``410 pairing_gone``,
``device_disconnected``); ``tasks``: nextasks-ios 1.4.x and nexlore-ios 1.2.x (``X-Pairing-Secret``, ``{device}``,
``{key, account{id: number, name}}``, ``404 app_pairing_unknown``, ``401 not_signed_in``, ``{"status": "ok"}``);
``mail``: nexmail-ios 1.1.x (the same with ``account.id`` as text, ``detail`` as text, ``schluessel``). Red here means
a published app breaks."""

from __future__ import annotations

from typing import Any

from geraete_contract import start_pairing

#: Per form: the refusals the published app reads, as (status, body) without the message where it has one.
GONE = {"nex": (410, "pairing_gone"), "tasks": (404, "app_pairing_unknown"), "mail": (404, "app_kopplung_unbekannt")}
OUT = {"nex": (401, "device_disconnected"), "tasks": (401, "not_signed_in"), "mail": (401, "nicht_angemeldet")}
OFF = {"nex": (403, "app_disabled"), "tasks": (403, "app_disabled"), "mail": (403, "app_abgeschaltet")}
SIBLINGS = {"nex": (429, "too_many_attempts"), "tasks": (429, "too_many"), "mail": (429, "app_zu_viele_geraete")}


def _detail(answer: Any, form: str) -> tuple[int, str]:
    detail = answer.json()["detail"]
    if form == "mail":
        assert isinstance(detail, str), answer.text
        return answer.status_code, detail
    assert set(detail) >= {"code", "message"}, answer.text
    return answer.status_code, detail["code"]


def _pick_up(app: Any, form: str, started: dict[str, Any], secret: str | None = None) -> Any:
    """The QR code the way the published app sends it."""
    client = app.device_client()
    path = f"{app.app_prefix}/pairing/{started['id']}/key"
    if form == "nex":
        return client.post(path, json={"secret": secret or started["secret"], "device_name": "Kim's iPhone",
                                       "device_kind": "ios"})
    return client.post(path, json={"device": "Kim's iPhone"},
                       headers={"X-Pairing-Secret": secret or started["secret"]})


def _check_paired(app: Any, form: str, answer: Any, status: int = 200) -> str:
    assert answer.status_code == status, answer.text
    assert answer.headers["cache-control"] == "no-store"
    body = answer.json()
    owner = app.account_id("owner")
    if form == "nex":
        assert set(body) >= {"token", "account", "device"}
        assert isinstance(body["account"]["id"], int) and body["account"]["id"] == owner
        assert set(body["account"]) >= {"id", "name", "login", "email", "avatar", "operator"}
        assert set(body["device"]) >= {"id", "name", "kind", "created_at", "last_seen_at"}
        return str(body["token"])
    assert set(body) == {"key", "account"} and set(body["account"]) == {"id", "name"}
    assert body["account"]["name"] == "Kim Example"
    if form == "tasks":
        assert isinstance(body["account"]["id"], int) and body["account"]["id"] == owner
    else:
        assert body["account"]["id"] == str(owner)
    return str(body["key"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_the_qr_code_as_the_published_app_picks_it_up(app: Any, config: Any) -> None:
    form = config.form
    started = start_pairing(app)
    token = _check_paired(app, form, _pick_up(app, form, started))
    assert app.probe(token).status_code == 200
    assert _detail(_pick_up(app, form, started), form) == GONE[form]
    assert _detail(_pick_up(app, form, start_pairing(app), secret="wrong"), form) == GONE[form]


def test_the_typed_code_as_the_published_app_sends_it(app: Any, config: Any) -> None:
    form = config.form
    started = start_pairing(app)
    body: dict[str, Any] = {"code": started["code"].lower()}
    body.update({"device_name": "Kim's iPhone"} if form == "nex" else {"device": "Kim's iPhone"})
    _check_paired(app, form, app.device_client().post(f"{app.app_prefix}/pairing/code", json=body))
    again = app.device_client().post(f"{app.app_prefix}/pairing/code", json=body)
    assert _detail(again, form) == GONE[form]


def test_a_device_refused_hears_the_old_code(app: Any, config: Any) -> None:
    form = config.form
    token = _check_paired(app, form, _pick_up(app, form, start_pairing(app)))
    assert _detail(app.probe(None), form) == OUT[form]
    assert _detail(app.probe(config.token_prefix + "x" * 43), form) == OUT[form]
    app.switch("app", False)
    assert _detail(app.probe(token), form) == OFF[form]
    app.switch("app", True)
    app.block()
    blocked = _detail(app.probe(token), form)
    assert blocked == ((401, "account_blocked") if form == "nex" else OUT[form])


def test_the_sibling_as_the_published_app_asks_for_it(app: Any, config: Any) -> None:
    form = config.form
    token = _check_paired(app, form, _pick_up(app, form, start_pairing(app)))
    body = {"device_name": "Kim's iPad"} if form == "nex" else {"device": "Kim's iPad"}
    status = 201 if form == "nex" else 200
    for _ in range(config.siblings_per_hour):
        _check_paired(app, form, app.device_client().post(f"{app.app_prefix}/devices", json=body,
                                                          headers=_bearer(token)), status)
    refused = app.device_client().post(f"{app.app_prefix}/devices", json=body, headers=_bearer(token))
    assert _detail(refused, form) == SIBLINGS[form] and "retry-after" in refused.headers
    if form == "mail":
        assert refused.json()["werte"] == {"max": config.siblings_per_hour}


def test_push_and_disconnecting_as_the_published_app_does_it(app: Any, config: Any, package: Any) -> None:
    form = config.form
    token = _check_paired(app, form, _pick_up(app, form, start_pairing(app)))
    _private, public = package.seal.key_pair()
    body = {"ticket": "ticket-old", ("schluessel" if form == "mail" else "key"): public}
    client = app.device_client()
    answer = client.put(f"{app.app_prefix}/push", json=body, headers=_bearer(token))
    if form == "nex":
        assert answer.status_code == 204 and answer.content == b""
    else:
        assert answer.status_code == 200 and answer.json() == {"status": "ok"}
    if config.legacy_kinds:
        app.tell("owner", config.legacy_kinds[0])
        assert len(app.relay.to("ticket-old")) == 1
    bad = client.put(f"{app.app_prefix}/push", json={**body, ("schluessel" if form == "mail" else "key"): "no"},
                     headers=_bearer(token))
    expected = {"nex": (422, "push_ticket_invalid"), "tasks": (422, "invalid_input"),
                "mail": (400, "kein_gueltiger_schluessel")}[form]
    assert _detail(bad, form) == expected
    off = client.delete(f"{app.app_prefix}/push", headers=_bearer(token))
    assert (off.status_code, off.content or b"") == (204, b"") if form == "nex" else off.json() == {"status": "ok"}
    assert client.delete(f"{app.app_prefix}/device", headers=_bearer(token)).status_code == 204
    assert _detail(app.probe(token), form) == OUT[form]
