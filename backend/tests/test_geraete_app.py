"""The shared module geraete 0.1.0 in nexpaper, beside its contract (``tests/nexgeraete``): the pairing window's QR code
is one the published iPhone app reads too (``nexpaper://pair?server=…&code=…``, traded at ``POST /api/v1/devices/pair``),
and an app built on NexKonto takes the same code at ``/api/app/1``; the old answers keep their names for the ways in."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app.models import Account

from .conftest import make_account, new_client


def program() -> TestClient:
    from app.main import app

    return TestClient(app, base_url="http://testserver")


def test_the_window_s_qr_code_pairs_the_published_app(client: TestClient, operator: Account) -> None:
    shown = client.post("/api/v1/devices/app-pairing", json={"address": "http://testserver"})
    assert shown.status_code == 201, shown.text
    body = shown.json()
    assert shown.headers["cache-control"] == "no-store"
    link = urlsplit(body["link"])
    assert (link.scheme, link.netloc) == ("nexpaper", "pair")
    query = parse_qs(link.query)
    assert query["server"] == ["http://testserver"] and query["code"] == [body["code"]]
    assert query["pairing"] == [body["id"]] and query["secret"] == [body["secret"]]
    assert body["qr_svg"].startswith("<svg") and len(body["code"]) == 14
    # nexpaper-ios 1.3 sends the code with a name of its own, as before.
    with program() as phone:
        paired = phone.post("/api/v1/devices/pair", json={"code": body["code"], "name": "iPhone von Jule"})
    assert paired.status_code == 201, paired.text
    assert paired.json()["device"]["via"] == "qr" and paired.json()["account_id"] == operator.id
    # The window learns of it through the module's route.
    state = client.get(f"/api/v1/app-pairing/{body['id']}").json()
    assert state["state"] == "used" and state["device"]["name"] == "iPhone von Jule"


def test_a_new_code_of_the_window_ends_the_one_before(client: TestClient, operator: Account) -> None:
    first = client.post("/api/v1/devices/app-pairing", json={}).json()
    second = client.post("/api/v1/devices/app-pairing", json={}).json()
    with program() as phone:
        assert phone.post("/api/v1/devices/pair", json={"code": first["code"], "name": "Old"}).status_code == 400
        assert phone.post("/api/app/1/pairing/code", json={"code": second["code"], "device_name": "iPad"},
                          headers={"X-Nex-App": "nexpaper-ios/2.0.0 (iPad Air; iPadOS 26.1)"}).status_code == 200
    listed = client.get("/api/v1/devices").json()
    # The module's way "code" is "qr" in the old list, as nexpaper named it.
    assert [(row["name"], row["via"]) for row in listed] == [("iPad", "qr")]


def test_only_a_signed_in_browser_shows_the_code(client: TestClient, operator: Account) -> None:
    with program() as stranger:
        assert stranger.post("/api/v1/devices/app-pairing", json={},
                             headers={"X-Nexpaper-Client": "tab-stranger0"}).status_code == 401
    token = client.post("/api/v1/devices", json={"name": "Phone"}).json()["token"]
    with program() as device:
        refused = device.post("/api/v1/devices/app-pairing", json={}, headers={"Authorization": f"Bearer {token}"})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "browser_only")


def test_the_operator_switches_new_devices_off_and_the_window_says_so(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/connections/interfaces", json={"pairing": False}).status_code == 200
    with new_client(make_account("noor")) as noor:
        refused = noor.post("/api/v1/devices/app-pairing", json={})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "app_pairing_disabled")
        old = noor.post("/api/v1/devices/pairing")
        assert (old.status_code, old.json()["detail"]["code"]) == (403, "app_pairing_disabled")


def test_hello_and_me_on_the_place_of_the_new_apps(client: TestClient, operator: Account) -> None:
    with program() as anyone:
        hello = anyone.get("/api/app/1/hello").json()
        assert hello["app"] == "nexpaper" and hello["api"] == 1 and "code" in hello["pairing"]
        assert anyone.get("/api/app/1/me").status_code == 401
    token = client.post("/api/v1/devices", json={"name": "Phone"}).json()["token"]
    with program() as device:
        me = device.get("/api/app/1/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["account"]["id"] == operator.id and me["device"]["name"] == "Phone" and me["device"]["this"] is True
