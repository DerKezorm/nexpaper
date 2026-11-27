"""Pairing (G6–G10): the QR code works once and ten minutes, the code to type in every spelling, the sign-in in the
browser with ``state`` and PKCE, the brake counts only failures, unknown, wrong, expired and used answer the same, the
limits, the switches of the operator. Red here means a stranger could take a key, or Kim could not connect at all."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from geraete_contract import NEW, auth, code_of, listed, new_device, pick_up, start_pairing


def _gone(answer: Any) -> tuple[int, str]:
    return answer.status_code, code_of(answer)


def test_the_qr_code_gives_one_device_its_own_key_once(app: Any, config: Any) -> None:
    started = start_pairing(app)
    answer = pick_up(app, started)
    assert answer.status_code == 200, answer.text
    assert answer.headers["cache-control"] == "no-store"
    body = answer.json()
    assert body["token"] == body["key"] and body["token"].startswith(config.token_prefix)
    assert body["account"]["id"] == body["account_id"] == app.account_id("owner")
    assert body["device"]["name"] == "Kim's iPhone" and body["device"]["kind"] == "ios"
    assert body["device"]["via"] == "qr" and body["device"]["model"] == "iPhone 16 Pro"
    assert app.probe(body["token"], NEW).status_code == 200
    again = pick_up(app, started)
    assert _gone(again) == (410, "pairing_gone")
    state = app.client("owner").get(f"{app.browser_prefix}/app-pairing/{started['id']}").json()
    assert state["state"] == "used" and state["device"]["name"] == "Kim's iPhone"


def test_unknown_wrong_expired_and_used_answer_the_same(app: Any) -> None:
    client = app.device_client()
    started = start_pairing(app)
    wrong = client.post(f"{app.app_prefix}/pairing/{started['id']}/key", json={"secret": "x" * 43}, headers=NEW)
    unknown = client.post(f"{app.app_prefix}/pairing/nothing-here/key", json={"secret": started["secret"]},
                          headers=NEW)
    empty = client.post(f"{app.app_prefix}/pairing/{started['id']}/key", json={}, headers=NEW)
    used_up = start_pairing(app)
    assert pick_up(app, used_up).status_code == 200
    used = pick_up(app, used_up)
    late = start_pairing(app)
    app.travel(timedelta(minutes=10, seconds=5))
    expired = pick_up(app, late)
    answers = [wrong, unknown, empty, used, expired]
    assert {(answer.status_code, answer.text) for answer in answers} == {(410, wrong.text)}
    assert code_of(wrong) == "pairing_gone"
    assert app.client("owner").get(f"{app.browser_prefix}/app-pairing/{late['id']}").json()["state"] == "expired"


def test_the_code_to_type_works_in_every_spelling_and_ten_minutes(app: Any, config: Any) -> None:
    started = start_pairing(app)
    code = started["code"]
    assert len(code.replace("-", "")) == config.code_length and "-" in code
    assert not set(code.replace("-", "")) & set("01OI")
    for spelling in (code.lower(), code.replace("-", " "), f" {code.replace('-', '')} "):
        answer = app.device_client().post(f"{app.app_prefix}/pairing/code", json={"code": spelling,
                                          "device_name": "Mila's iPad", "device_kind": "ipados"}, headers=NEW)
        if answer.status_code == 200:
            assert answer.json()["device"]["via"] == "code" and answer.json()["device"]["kind"] == "ipados"
            break
    else:
        raise AssertionError("no spelling of the code worked")
    assert app.device_client().post(f"{app.app_prefix}/pairing/code", json={"code": code},
                                    headers=NEW).status_code == 410
    late = start_pairing(app)
    app.travel(timedelta(minutes=10, seconds=5))
    assert app.device_client().post(f"{app.app_prefix}/pairing/code", json={"code": late["code"]},
                                    headers=NEW).status_code == 410


def test_the_link_names_the_address_both_ways_and_the_qr_code_scales(app: Any, config: Any) -> None:
    started = start_pairing(app)
    link = urlsplit(started["link"])
    query = parse_qs(link.query)
    assert link.scheme == config.scheme and link.netloc == "connect"
    assert query["server"] == query["address"] == [started["address"]]
    assert query["pairing"] == [started["id"]] and query["secret"] == [started["secret"]]
    assert started["qr_svg"].lstrip().startswith("<svg") and "viewBox" in started["qr_svg"]
    assert started["app_store_url"] == config.app_store_url
    answer = app.client("owner").post(f"{app.browser_prefix}/app-pairing", json={})
    assert answer.headers["cache-control"] == "no-store"


def test_only_the_hash_of_a_key_is_kept(app: Any, package: Any) -> None:
    token = new_device(app)
    stored = app.database_text()
    assert token.encode() not in stored and token[-20:].encode() not in stored
    assert package.tokens.digest(token).encode() in stored


def _verifier() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _consent(app: Any, body: dict[str, Any]) -> str:
    answer = app.client("owner").post(f"{app.browser_prefix}/app-connect", json=body)
    assert answer.status_code == 200, answer.text
    assert answer.headers["cache-control"] == "no-store"
    return str(answer.json()["redirect"])


def _code(redirect: str) -> str:
    return parse_qs(urlsplit(redirect).query)["code"][0]


def test_the_sign_in_in_the_browser_hands_a_code_for_five_minutes_once(app: Any, config: Any) -> None:
    redirect = _consent(app, {"state": "state-of-the-app-1234"})
    parts = urlsplit(redirect)
    assert f"{parts.scheme}://{parts.netloc}" == f"{config.scheme}://connected"
    assert parse_qs(parts.query)["state"] == ["state-of-the-app-1234"]
    client = app.device_client()
    answer = client.post(f"{app.app_prefix}/pairing/code", json={"code": _code(redirect)}, headers=NEW)
    assert answer.status_code == 200, answer.text
    assert answer.json()["device"]["via"] == "browser"
    assert client.post(f"{app.app_prefix}/pairing/code", json={"code": _code(redirect)}, headers=NEW).status_code == 410
    late = _consent(app, {"state": "state-of-the-app-1234"})
    app.travel(timedelta(minutes=config.connect_minutes, seconds=5))
    assert client.post(f"{app.app_prefix}/pairing/code", json={"code": _code(late)}, headers=NEW).status_code == 410
    bad = app.client("owner").post(f"{app.browser_prefix}/app-connect", json={"state": "x"})
    assert bad.status_code == 422 and code_of(bad) == "invalid_input"


def test_pkce_the_verifier_must_fit_and_a_wrong_one_uses_the_code_up(app: Any) -> None:
    verifier, challenge = _verifier()
    client = app.device_client()
    path = f"{app.app_prefix}/pairing/code"
    missing = _consent(app, {"state": "state-of-the-app-1234", "challenge": challenge})
    assert client.post(path, json={"code": _code(missing)}, headers=NEW).status_code == 410
    wrong = _consent(app, {"state": "state-of-the-app-1234", "challenge": challenge})
    assert client.post(path, json={"code": _code(wrong), "verifier": _verifier()[0]}, headers=NEW).status_code == 410
    assert client.post(path, json={"code": _code(wrong), "verifier": verifier}, headers=NEW).status_code == 410
    right = _consent(app, {"state": "state-of-the-app-1234", "challenge": challenge})
    answer = client.post(path, json={"code": _code(right), "verifier": verifier}, headers=NEW)
    assert answer.status_code == 200, answer.text
    bad = app.client("owner").post(f"{app.browser_prefix}/app-connect",
                                   json={"state": "state-of-the-app-1234", "challenge": "short"})
    assert bad.status_code == 422


def test_the_old_sign_in_page_leads_to_the_qr_codes_link(app: Any, config: Any) -> None:
    redirect = _consent(app, {"device": "Kim's iPhone"})
    query = parse_qs(urlsplit(redirect).query)
    assert redirect.startswith(f"{config.scheme}://connect?") and query["pairing"] and query["secret"]
    answer = pick_up(app, {"id": query["pairing"][0], "secret": query["secret"][0]})
    assert answer.status_code == 200


def test_the_brake_stops_guessing_and_counts_only_failures(app: Any) -> None:
    client = app.device_client()
    for _ in range(8):
        assert pick_up(app, start_pairing(app)).status_code == 200
    started = start_pairing(app)
    for _attempt in range(40):
        answer = client.post(f"{app.app_prefix}/pairing/{started['id']}/key", json={"secret": "wrong"}, headers=NEW)
        if answer.status_code == 429:
            break
        assert answer.status_code == 410
    else:
        raise AssertionError("forty wrong secrets and no brake")
    assert code_of(answer) == "too_many_attempts" and int(answer.headers["retry-after"]) >= 1
    assert pick_up(app, started).status_code == 429


def test_two_pickups_at_the_same_moment_make_one_device(app: Any) -> None:
    started = start_pairing(app)
    gate = threading.Barrier(2)
    statuses: list[int] = []

    def take() -> None:
        gate.wait()
        statuses.append(pick_up(app, started).status_code)

    threads = [threading.Thread(target=take) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(statuses) == [200, 410]
    assert len(listed(app)) == 1


def test_at_most_five_pairings_wait_and_thirty_devices(app: Any, config: Any) -> None:
    for _ in range(config.open_pairings):
        start_pairing(app)
    answer = app.client("owner").post(f"{app.browser_prefix}/app-pairing", json={})
    assert answer.status_code == 409 and code_of(answer) == "too_many_pairings"
    assert answer.json()["detail"]["max"] == config.open_pairings
    for _ in range(config.max_devices):
        app.make_legacy(app.legacy_devices()[0], account="other")
    started = start_pairing(app, "other")
    full = pick_up(app, started)
    assert full.status_code == 409 and code_of(full) == "too_many_devices"
    assert full.json()["detail"]["max"] == config.max_devices


def test_new_devices_switched_off_stops_only_new_ones(app: Any) -> None:
    token = new_device(app)
    started = start_pairing(app)
    app.switch("pairing" if "pairing" in app.config().switches else "app", False)
    answer = pick_up(app, started)
    assert answer.status_code == 403
    if "pairing" in app.config().switches:
        assert code_of(answer) == "app_pairing_disabled"
        assert app.probe(token, NEW).status_code == 200
    refused = app.client("owner").post(f"{app.browser_prefix}/app-pairing", json={})
    assert refused.status_code == 403
    sibling = app.device_client().post(f"{app.app_prefix}/devices", json={}, headers=auth(token))
    assert sibling.status_code == 403


def test_an_account_blocked_meanwhile_gets_no_device(app: Any) -> None:
    started = start_pairing(app)
    app.block()
    assert pick_up(app, started).status_code == 410
    app.unblock()
    assert pick_up(app, started).status_code == 410, "the code was used up"
    assert listed(app) == []


def test_a_new_device_is_told_by_mail_and_to_the_others(app: Any) -> None:
    new_device(app, name="Kim's iPhone")
    assert app.paired_mails()[-1] == (app.account_id("owner"), "Kim's iPhone")
