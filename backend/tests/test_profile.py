"""A display name per account: changed by the account itself; the name stays what one signs in with."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Account

from .conftest import person


def test_the_own_display_name_is_set_cleaned_and_taken_back(client: TestClient, account: Account) -> None:
    answer = client.put("/api/v1/me/profile", json={"display_name": "  Tess   Ter  "})
    assert answer.status_code == 200
    assert answer.json()["display_name"] == "Tess Ter"
    assert client.get("/api/v1/auth/me").json()["display_name"] == "Tess Ter"
    # The name to sign in with does not change.
    assert client.get("/api/v1/auth/me").json()["name"] == "tester"
    assert client.put("/api/v1/me/profile", json={"display_name": ""}).json()["display_name"] == ""


def test_a_display_name_is_not_too_long_and_has_no_control_characters(client: TestClient, account: Account) -> None:
    assert client.put("/api/v1/me/profile", json={"display_name": "x" * 80}).status_code == 200
    long = client.put("/api/v1/me/profile", json={"display_name": "x" * 81})
    assert (long.status_code, long.json()["detail"]["code"]) == (422, "display_name_too_long")
    control = client.put("/api/v1/me/profile", json={"display_name": "Tess\nTer"})
    assert (control.status_code, control.json()["detail"]["code"]) == (422, "display_name_invalid")
    assert client.get("/api/v1/auth/me").json()["display_name"] == "x" * 80


DEFAULTS = {"mode": "system", "quick_start": True, "view": "list", "ai": True, "notify_login": True,
            "timezone_source": "browser", "default_vault": None, "timezone": ""}


def test_light_or_dark_is_kept_with_the_account(client: TestClient, account: Account) -> None:
    assert client.get("/api/v1/auth/me").json()["profile"] == DEFAULTS
    saved = client.put("/api/v1/me/preferences", json={"mode": "dark"})
    assert saved.status_code == 200 and saved.json() == {**DEFAULTS, "mode": "dark"}
    assert client.get("/api/v1/auth/me").json()["profile"]["mode"] == "dark"
    for wrong in ({"mode": "sepia"}, {"mode": True}, {"palette": "salbei"}, {"mode": ["dark"]}):
        answer = client.put("/api/v1/me/preferences", json=wrong)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "bad_preference", wrong
    assert client.get("/api/v1/auth/me").json()["profile"]["mode"] == "dark", "a refused value changes nothing"


def test_there_is_one_accent_and_no_palette_to_choose() -> None:
    from app.routers.auth import PROFILE

    assert "palette" not in PROFILE


def test_the_profile_is_the_own_account_s_only(client: TestClient, account: Account) -> None:
    from .conftest import person

    with person("mia") as mia:
        assert mia.put("/api/v1/me/preferences", json={"mode": "light"}).status_code == 200
    assert client.get("/api/v1/auth/me").json()["profile"]["mode"] == "system"


def test_the_archive_view_the_quick_start_and_the_time_zone_are_kept_with_the_account(
    client: TestClient, account: Account
) -> None:
    saved = client.put("/api/v1/me/preferences", json={"view": "grid", "quick_start": False, "timezone": "Asia/Tokyo"})
    assert saved.status_code == 200
    assert client.get("/api/v1/auth/me").json()["profile"] == {
        **DEFAULTS, "view": "grid", "quick_start": False, "timezone": "Asia/Tokyo"}
    for wrong in ({"view": "kacheln"}, {"view": 1}, {"quick_start": 1}, {"quick_start": "yes"},
                  {"timezone": "Mars/Olympus"}, {"timezone": "../../etc/passwd"}, {"timezone": 7}, {"timezone": ""},
                  {"timezone": "x" * 300}):
        answer = client.put("/api/v1/me/preferences", json=wrong)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "bad_preference", wrong
    assert client.get("/api/v1/auth/me").json()["profile"]["timezone"] == "Asia/Tokyo"
    assert client.get("/api/v1/auth/me").json()["profile"]["quick_start"] is False


def test_the_default_vault_is_a_vault_the_person_may_add_to_or_none(client: TestClient, account: Account) -> None:
    own = client.get("/api/v1/vaults").json()[0]["id"]
    assert client.put("/api/v1/me/preferences", json={"default_vault": own}).json()["default_vault"] == own
    assert client.put("/api/v1/me/preferences", json={"default_vault": None}).json()["default_vault"] is None
    with person("other") as other:
        foreign = other.get("/api/v1/vaults").json()[0]["id"]
    for wrong in ({"default_vault": 0}, {"default_vault": -1}, {"default_vault": "1"}, {"default_vault": True},
                  {"default_vault": 1.5}, {"default_vault": 2**40}, {"default_vault": foreign},
                  {"default_vault": own + 1000}):
        answer = client.put("/api/v1/me/preferences", json=wrong)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "bad_preference", wrong


def test_a_browser_does_not_overrule_a_time_zone_the_person_chose(client: TestClient, account: Account) -> None:
    chosen = client.put("/api/v1/me/preferences", json={"timezone": "Asia/Tokyo", "timezone_source": "manual"})
    assert chosen.status_code == 200
    reported = client.put("/api/v1/me/preferences", json={"timezone": "Europe/Berlin", "timezone_source": "browser"})
    assert reported.status_code == 200 and reported.json()["timezone"] == "Asia/Tokyo"
    assert reported.json()["timezone_source"] == "manual"
    # The person may go back to the browser's zone.
    back = client.put("/api/v1/me/preferences", json={"timezone": "Europe/Berlin", "timezone_source": "manual"})
    assert back.json()["timezone"] == "Europe/Berlin"
    assert client.put("/api/v1/me/preferences", json={"timezone_source": "phone"}).status_code == 422
