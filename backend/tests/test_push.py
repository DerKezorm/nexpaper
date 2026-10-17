"""Web Push: a device signs up, a message reaches it encrypted as RFC 8291 has it and signed as RFC 8292 has it, a device
that left is removed, and the address a browser hands over never leads the server anywhere but to a push service in
the public internet. What a device handed over lies sealed; a person reaches only their own devices."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import Account
from app.services import push, webpush

from .clear import deep_log, found_in, journal_kept, word  # noqa: F401 - fixtures
from .conftest import DATA_DIR, PASSWORD, make_account, new_client
from .fake_push import ADDRESS, HOST, FakePushService, public_resolver

FIREFOX = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"}


def sign_up(client: TestClient, fake: FakePushService, **extra: object) -> tuple[dict, object]:
    device = fake.device()
    answer = client.post("/api/v1/push/devices", json=device.subscription(**extra), headers=FIREFOX)
    assert answer.status_code == 201, answer.text
    return answer.json(), device


# --- Encryption and signature ---------------------------------------------------------------------------------------


def test_a_probe_arrives_encrypted_as_rfc_8291_and_signed_as_rfc_8292(client: TestClient, account: Account,
                                                                      push_service: FakePushService) -> None:
    client.put("/api/v1/settings/push", json={"contact": "mailto:paper@example.com"})
    sign_up(client, push_service)
    result = client.post("/api/v1/push/test")
    assert result.status_code == 200 and result.json() == {"sent": 1, "gone": 0, "failed": 0}
    [came] = push_service.received
    assert came.message["title"] == "nexpaper" and came.message["body"]
    assert came.message["url"] == "/" and came.message["desk"] == "/"
    assert came.claims["aud"] == f"https://{HOST}" and came.claims["sub"] == "mailto:paper@example.com"
    assert 0 < came.claims["exp"] - time.time() <= 24 * 3600
    assert came.headers["ttl"] == str(webpush.TTL_SECONDS) and came.headers["content-type"] == "application/octet-stream"
    # The key in the header is the one the browser signed up with.
    key = client.get("/api/v1/push").json()["key"]
    assert came.headers["authorization"].endswith(f", k={key}")
    assert client.get("/api/v1/push").json()["devices"][0]["last"] is not None


def test_two_messages_to_the_same_device_differ_entirely(client: TestClient, account: Account,
                                                         push_service: FakePushService) -> None:
    sign_up(client, push_service)
    client.post("/api/v1/push/test")
    client.post("/api/v1/push/test")
    first, second = (request.content for request in push_service.requests)
    # A fresh key and salt for every message: nothing repeats that would tell two equal texts apart.
    assert first[:16] != second[:16] and first[21:86] != second[21:86]


def test_the_key_pair_is_made_once_and_kept_sealed(client: TestClient, account: Account) -> None:
    first = client.get("/api/v1/push").json()["key"]
    assert client.get("/api/v1/push").json()["key"] == first
    assert len(webpush.unb64url(first)) == 65
    stored = client.get("/api/v1/settings/push").json()
    assert stored["key"] == f"{first[:4]}…{first[-4:]}"
    from app.db import SessionLocal
    from app.services import settings_service

    with SessionLocal() as db:
        sealed = str(settings_service.get(db, "push_key_enc"))
    assert "PRIVATE KEY" not in sealed and len(sealed) > 100


def test_a_key_pair_another_process_made_meanwhile_is_kept(client: TestClient, account: Account,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import SessionLocal
    from app.services import settings_service

    with SessionLocal() as db:
        first = webpush.public_key(db)
    real = settings_service.get
    stale = ["push_key_enc"]

    def read(db: object, key: str) -> object:
        # This process read before the other one wrote: no key yet.
        if key in stale:
            stale.remove(key)
            return ""
        return real(db, key)  # type: ignore[arg-type]

    monkeypatch.setattr(settings_service, "get", read)
    with SessionLocal() as db:
        assert webpush.public_key(db) == first, "the pair that stands is kept, not overwritten"
    assert stale == []


def test_two_first_needs_at_once_make_one_key_pair(client: TestClient, account: Account) -> None:
    from app.db import SessionLocal

    keys: list[str] = []
    start = threading.Barrier(6)

    def one() -> None:
        start.wait()
        with SessionLocal() as db:
            keys.append(webpush.public_key(db))

    threads = [threading.Thread(target=one) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(keys)) == 1 and len(keys) == 6


# --- Devices --------------------------------------------------------------------------------------------------------


def test_a_device_is_named_after_its_browser_and_the_name_can_change(client: TestClient, account: Account,
                                                                    push_service: FakePushService) -> None:
    device, _ = sign_up(client, push_service)
    assert device["name"] == "Firefox on Windows" and device["since"] and device["last"] is None
    german = client.post("/api/v1/push/devices", json=push_service.device().subscription(installed=True),
                         headers={**FIREFOX, "X-Nexpaper-Language": "de"})
    assert german.json()["name"] == "nexpaper unter Windows"
    renamed = client.put(f"/api/v1/push/devices/{device['id']}", json={"name": "  Mein   Laptop "})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Mein Laptop"
    for bad in ("", "a" * 61, "zwei\nZeilen", "un" + chr(0x202E) + "sichtbar"):
        assert client.put(f"/api/v1/push/devices/{device['id']}", json={"name": bad}).status_code == 422, bad
    assert [entry["name"] for entry in client.get("/api/v1/push").json()["devices"]] == ["Mein Laptop",
                                                                                      "nexpaper unter Windows"]


def test_the_same_browser_twice_stays_one_device_also_at_the_same_moment(client: TestClient, account: Account,
                                                                         push_service: FakePushService) -> None:
    device = push_service.device()
    answers: list[int] = []
    start = threading.Barrier(5)

    def one() -> None:
        with new_client(account) as browser:
            start.wait()
            answers.append(browser.post("/api/v1/push/devices", json=device.subscription()).status_code)

    threads = [threading.Thread(target=one) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [200, 200, 200, 200, 201]
    assert len(client.get("/api/v1/push").json()["devices"]) == 1
    found = client.post("/api/v1/push/devices/lookup", json={"endpoint": device.endpoint}).json()["id"]
    assert found == client.get("/api/v1/push").json()["devices"][0]["id"]
    assert client.post("/api/v1/push/devices/lookup", json={"endpoint": device.endpoint + "x"}).json() == {"id": None}


def test_a_person_has_at_most_ten_devices(client: TestClient, account: Account, push_service: FakePushService) -> None:
    for _ in range(push.DEVICES_MAX):
        sign_up(client, push_service)
    refused = client.post("/api/v1/push/devices", json=push_service.device().subscription())
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "push_too_many_devices"


def test_keys_that_are_not_a_point_on_the_curve_are_refused(client: TestClient, account: Account,
                                                            push_service: FakePushService) -> None:
    device = push_service.device()
    for p256dh, auth in ((device.p256dh[:-4], device.auth), (device.p256dh, device.auth[:-2]),
                         ("B" + "A" * 86, device.auth), ("not base64!", device.auth)):
        answer = client.post("/api/v1/push/devices", json={"endpoint": device.endpoint, "p256dh": p256dh, "auth": auth})
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "push_keys_invalid"


def test_a_device_that_left_is_removed_a_busy_or_broken_service_is_not(client: TestClient, account: Account,
                                                                       push_service: FakePushService) -> None:
    devices = [sign_up(client, push_service)[1] for _ in range(5)]
    for device, status in zip(devices, (404, 410, 429, 500, 201), strict=True):
        push_service.answers[device.endpoint.rsplit("/", 1)[-1]] = status
    assert client.post("/api/v1/push/test").json() == {"sent": 1, "gone": 2, "failed": 2}
    assert len(client.get("/api/v1/push").json()["devices"]) == 3
    # Tried again next time: the busy one and the broken one are still there.
    assert client.post("/api/v1/push/test").json() == {"sent": 1, "gone": 0, "failed": 2}


def test_a_redirect_is_not_followed_and_a_large_answer_not_read(client: TestClient, account: Account,
                                                                push_service: FakePushService,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    sign_up(client, push_service)
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(301, headers={"Location": "http://127.0.0.1:8560/api/v1/auth/me"})
        # Past the limit: the body is thrown away unread, its status still counts (a finding of the review).
        return httpx.Response(410, content=b"x" * (push.ANSWER_MAX + 1))

    monkeypatch.setattr(push, "transport", httpx.MockTransport(answer))
    assert client.post("/api/v1/push/test").json() == {"sent": 0, "gone": 0, "failed": 1}
    assert len(client.get("/api/v1/push").json()["devices"]) == 1
    assert client.post("/api/v1/push/test").json() == {"sent": 0, "gone": 1, "failed": 0}
    assert len(seen) == 2 and all(ADDRESS in url for url in seen)
    assert client.get("/api/v1/push").json()["devices"] == []


def test_a_service_that_does_not_answer_holds_nobody_past_the_deadline(client: TestClient, account: Account,
                                                                       push_service: FakePushService,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    sign_up(client, push_service)
    clock = [0.0]
    monkeypatch.setattr(push, "ticks", lambda: clock[0])

    def late(request: httpx.Request) -> httpx.Response:
        clock[0] += push.SECONDS + 1
        raise httpx.ReadTimeout("no answer", request=request)

    monkeypatch.setattr(push, "transport", httpx.MockTransport(late))
    assert client.post("/api/v1/push/test").json() == {"sent": 0, "gone": 0, "failed": 1}


def test_a_probe_without_a_device_says_so(client: TestClient, account: Account) -> None:
    answer = client.post("/api/v1/push/test")
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "push_no_devices"


# --- Where a message may go -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", [
    "http://push.example.com/wpush/v2/abc",
    "https://93.184.215.14/wpush/v2/abc",
    "https://[2606:2800:220:1::248]/wpush/v2/abc",
    "https://[::ffff:127.0.0.1]/x",
    "https://2130706433/x",
    "https://0x7f.0.0.1/x",
    "https://push.example.com:8443/wpush/v2/abc",
    "https://user:secret@push.example.com/wpush/v2/abc",
    "https://evil.example.org/wpush/v2/abc",
    "https://fcm.googleapis.com.evil.example.org/fcm/send/abc",
    "https://evilfcm.googleapis.com/fcm/send/abc",
    "https://localhost/x",
    "https://push.example.com/x#y",
    "ftp://push.example.com/x",
    "https://push.example.com/a b",
    "https://" + "a" * 1000 + ".example.com/x",
])
def test_an_address_that_is_not_a_known_push_service_is_refused(client: TestClient, account: Account,
                                                               push_service: FakePushService, endpoint: str) -> None:
    keys = push_service.device()
    answer = client.post("/api/v1/push/devices", json={"endpoint": endpoint, "p256dh": keys.p256dh, "auth": keys.auth})
    assert answer.status_code == 422, endpoint
    assert answer.json()["detail"]["code"] in ("push_endpoint_invalid", "push_endpoint_refused",
                                               "push_service_unknown", "invalid_input"), endpoint
    assert client.get("/api/v1/push").json()["devices"] == []
    assert push_service.requests == []


@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "192.168.1.20", "169.254.169.254", "::1", "fd00::5",
                                     "100.64.0.1", "64:ff9b::a9fe:a9fe", "0.0.0.0"])
def test_a_push_service_whose_name_leads_into_an_own_network_is_refused(client: TestClient, account: Account,
                                                                        push_service: FakePushService,
                                                                        monkeypatch: pytest.MonkeyPatch,
                                                                        address: str) -> None:
    monkeypatch.setattr(push, "resolver", lambda host, port: [address])
    answer = client.post("/api/v1/push/devices", json=push_service.device().subscription())
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "push_endpoint_refused"
    assert push_service.requests == []


def test_a_name_that_turns_to_an_own_network_later_gets_nothing(client: TestClient, account: Account,
                                                                push_service: FakePushService,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    sign_up(client, push_service)
    lookups: list[str] = []

    def rebinding(host: str, port: int) -> list[str]:
        lookups.append(host)
        return [ADDRESS, "192.168.1.1"]

    monkeypatch.setattr(push, "resolver", rebinding)
    assert client.post("/api/v1/push/test").json() == {"sent": 0, "gone": 0, "failed": 1}
    assert push_service.requests == [] and lookups == [HOST]
    assert len(client.get("/api/v1/push").json()["devices"]) == 1


def test_a_push_service_taken_off_the_list_gets_nothing_more(client: TestClient, account: Account,
                                                             push_service: FakePushService) -> None:
    sign_up(client, push_service)
    assert client.put("/api/v1/settings/push", json={"hosts": []}).status_code == 200
    assert client.post("/api/v1/push/test").json() == {"sent": 0, "gone": 0, "failed": 1}
    assert push_service.requests == []


def test_the_known_push_services_are_allowed_and_the_operator_adds_names_never_addresses(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakePushService()
    monkeypatch.setattr(push, "resolver", public_resolver)
    for host in ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com",
                 "wns2-par02p.notify.windows.com"):
        device = fake.device(host)
        assert client.post("/api/v1/push/devices", json=device.subscription()).status_code == 201, host
    refused = client.post("/api/v1/push/devices", json=fake.device().subscription())
    assert refused.json()["detail"]["code"] == "push_service_unknown"
    for entry in ("10.0.0.1", "[::1]", "push.example.com:8443", "https://push.example.com", "localhost", "a..b"):
        answer = client.put("/api/v1/settings/push", json={"hosts": [entry]})
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "push_host_invalid", entry
    added = client.put("/api/v1/settings/push", json={"hosts": ["Push.Example.com.", "", "push.example.com",
                                                             "fcm.googleapis.com"]})
    assert added.json()["hosts"] == ["push.example.com"]
    assert client.post("/api/v1/push/devices", json=fake.device().subscription()).status_code == 201
    too_many = client.put("/api/v1/settings/push", json={"hosts": [f"p{n}.example.com" for n in range(push.HOSTS_MAX + 1)]})
    assert too_many.status_code == 422 and too_many.json()["detail"]["code"] == "push_too_many_hosts"


def test_the_contact_is_a_mail_address_or_an_https_address(client: TestClient, account: Account) -> None:
    for good in ("mailto:paper@example.com", "https://paper.example.com", ""):
        assert client.put("/api/v1/settings/push", json={"contact": good}).status_code == 200, good
    for bad in ("paper@example.com", "mailto:", "http://paper.example.com", "javascript:alert(1)",
                "mailto:a@example.com\r\nBcc: b@example.com", "https://u:p@example.com", "mailto:" + "a" * 300):
        answer = client.put("/api/v1/settings/push", json={"contact": bad})
        assert answer.status_code == 422, bad
    shown = client.get("/api/v1/settings/push").json()
    assert shown["contact"] == "" and shown["contact_used"] == webpush.PLACEHOLDER_CONTACT
    assert client.put("/api/v1/settings", json={"public_url": "https://paper.example.com"}).status_code == 200
    assert client.get("/api/v1/settings/push").json()["contact_used"] == "https://paper.example.com"


# --- Rights ---------------------------------------------------------------------------------------------------------


def test_a_person_never_sees_or_changes_the_devices_of_another(client: TestClient, account: Account,
                                                               push_service: FakePushService) -> None:
    own, device = sign_up(client, push_service)
    with new_client(make_account("rike")) as rike:
        assert rike.get("/api/v1/push").json()["devices"] == []
        assert rike.put(f"/api/v1/push/devices/{own['id']}", json={"name": "meins"}).status_code == 404
        assert rike.delete(f"/api/v1/push/devices/{own['id']}").status_code == 404
        assert rike.post("/api/v1/push/devices/lookup", json={"endpoint": device.endpoint}).json() == {"id": None}
        assert rike.post("/api/v1/push/test").status_code == 409
        # The same browser address signed up by somebody else is that person's device of their own.
        assert rike.post("/api/v1/push/devices", json=device.subscription()).status_code == 201
        assert rike.get("/api/v1/settings/push").status_code == 403
        assert rike.put("/api/v1/settings/push", json={"hosts": []}).status_code == 403
        assert rike.post("/api/v1/settings/push/renew", json={"current_password": PASSWORD}).status_code == 403
        rike_devices = rike.get("/api/v1/push").json()["devices"]
    assert [entry["id"] for entry in client.get("/api/v1/push").json()["devices"]] == [own["id"]]
    # The operator sees how many, never whose or which.
    view = client.get("/api/v1/settings/push").json()
    assert view["devices"] == 2
    assert rike_devices[0]["id"] not in str(view) and "Firefox" not in str(view) and "rike" not in str(view)
    assert client.delete(f"/api/v1/push/devices/{rike_devices[0]['id']}").status_code == 404
    # Nor when somebody is reminded: the list of accounts holds nothing a person chose for themselves.
    listed = client.get("/api/v1/accounts").json()
    assert len(listed) == 2 and all("profile" not in entry and "reminder" not in str(entry) for entry in listed)


def test_renewing_the_keys_needs_the_password_and_signs_every_device_off(client: TestClient, account: Account,
                                                                         push_service: FakePushService) -> None:
    sign_up(client, push_service)
    before = client.get("/api/v1/push").json()["key"]
    wrong = client.post("/api/v1/settings/push/renew", json={"current_password": "not the password"})
    assert wrong.status_code == 401 and len(client.get("/api/v1/push").json()["devices"]) == 1
    renewed = client.post("/api/v1/settings/push/renew", json={"current_password": PASSWORD})
    assert renewed.status_code == 200 and renewed.json()["devices"] == 0
    after = client.get("/api/v1/push").json()
    assert after["devices"] == [] and after["key"] != before


def test_deleting_an_account_takes_its_devices(client: TestClient, account: Account,
                                               push_service: FakePushService) -> None:
    rike = make_account("rike")
    with new_client(rike) as browser:
        assert browser.post("/api/v1/push/devices", json=push_service.device().subscription()).status_code == 201
    assert client.get("/api/v1/settings/push").json()["devices"] == 1
    assert client.request("DELETE", f"/api/v1/accounts/{rike.id}", json={"confirm_name": "rike", "current_password": PASSWORD}).status_code == 204
    assert client.get("/api/v1/settings/push").json()["devices"] == 0


# --- Sealed ---------------------------------------------------------------------------------------------------------


def test_what_a_device_handed_over_lies_sealed(client: TestClient, account: Account, push_service: FakePushService,
                                               word: str, deep_log: None, journal_kept: None) -> None:  # noqa: F811
    device = push_service.device()
    token = device.endpoint.rsplit("/", 1)[-1]
    made = client.post("/api/v1/push/devices", json=device.subscription())
    assert made.status_code == 201
    client.put(f"/api/v1/push/devices/{made.json()['id']}", json={"name": f"Laptop {word}"})
    assert client.post("/api/v1/push/test").json()["sent"] == 1
    database = get_settings().database_path
    searched = 0
    for path in Path(DATA_DIR).rglob("*"):
        if not path.is_file() or path.suffix == ".zip":
            continue
        searched += 1
        data = path.read_bytes()
        for secret in (word, token, device.p256dh, device.auth):
            assert not found_in(data, secret), (path.name, secret[:4])
    assert searched > 3 and database.with_name(database.name + "-wal").stat().st_size > 0
    # Floor: it is there, readable through the API.
    assert word in client.get("/api/v1/push").text


# --- Nothing a person stored ----------------------------------------------------------------------------------------


def test_a_message_never_carries_what_a_person_stored(client: TestClient, account: Account,
                                                      push_service: FakePushService, word: str) -> None:  # noqa: F811
    client.put("/api/v1/me/profile", json={"display_name": f"Name {word}"})
    client.put("/api/v1/me/preferences", json={"timezone": "Europe/Berlin"})
    sign_up(client, push_service)
    for _ in range(3):
        client.post("/api/v1/push/test")
    assert len(push_service.received) == 3
    for came in push_service.received:
        assert word not in str(came.message)


# --- Findings of the review -----------------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["https://[::1", "https://[push.example.com]/x", "https://[fcm.googleapis.com]/x",
                                      "https://a℀b.example.com/x"])
def test_an_address_python_cannot_split_is_a_wrong_address_not_a_server_fault(
    client: TestClient, account: Account, push_service: FakePushService, endpoint: str
) -> None:
    keys = push_service.device()
    answer = client.post("/api/v1/push/devices", json={"endpoint": endpoint, "p256dh": keys.p256dh, "auth": keys.auth})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "push_endpoint_invalid", endpoint


def test_a_name_in_full_width_letters_is_kept_as_the_name_it_reads_as(
    client: TestClient, account: Account, push_service: FakePushService
) -> None:
    device = push_service.device()
    wide = device.endpoint.replace("https://push", "https://ｐush")
    answer = client.post("/api/v1/push/devices", json={"endpoint": wide, "p256dh": device.p256dh, "auth": device.auth})
    assert answer.status_code == 201, answer.text
    assert client.post("/api/v1/push/test").json() == {"sent": 1, "gone": 0, "failed": 0}
    assert push_service.received and push_service.received[0].url == device.endpoint.replace(HOST, ADDRESS)


def test_one_broken_device_never_holds_up_the_others(client: TestClient, account: Account,
                                                     push_service: FakePushService,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    sign_up(client, push_service)
    sign_up(client, push_service)
    original = push._deliver_one
    calls: list[int] = []

    def breaks_once(*args: object) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise UnicodeEncodeError("ascii", "ｐ", 0, 1, "made to fail")
        return original(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(push, "_deliver_one", breaks_once)
    assert client.post("/api/v1/push/test").json() == {"sent": 1, "gone": 0, "failed": 1}


def test_ten_devices_at_most_also_when_they_sign_up_at_the_same_moment(
    client: TestClient, account: Account, push_service: FakePushService, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(push.DEVICES_MAX - 2):
        sign_up(client, push_service)
    # Between counting and writing every one of them waits a moment: all have counted before any has written.
    sealing = push._seal

    def slow_seal(*args: object) -> str:
        time.sleep(0.3)
        return sealing(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(push, "_seal", slow_seal)
    devices = [push_service.device() for _ in range(6)]
    answers: list[int] = []
    start = threading.Barrier(len(devices))

    def one(device: object) -> None:
        start.wait()
        answers.append(client.post("/api/v1/push/devices", json=device.subscription()).status_code)  # type: ignore[attr-defined]

    threads = [threading.Thread(target=one, args=(device,)) for device in devices]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert answers.count(201) == 2 and answers.count(409) == 4
    assert len(client.get("/api/v1/push").json()["devices"]) == push.DEVICES_MAX
