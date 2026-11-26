"""The about page and the update check (block X2), since the shared module ``nexupdates`` (updates 0.1.1).

The check is a side matter: when GitHub is slow, gone or answers rubbish, the page shows no answer and nothing else
changes. No test here reaches GitHub; the conftest points the address at a port that refuses. Only an operator sees the
state (U15, U21): a member's page gets the form of before with every field empty and ``hidden`` true. The contract
tests of the module (``tests/nexupdates``) hold the rest; these keep what nexpaper's own tests held before.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Self

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.models import Account
from app.services import updates
from app.vendor.nexupdates import check

from .conftest import person

#: The real client, before any test puts a stand-in in its place.
REAL_CLIENT = httpx.Client


def answers(monkeypatch: pytest.MonkeyPatch, tag: str | None) -> list[int]:
    asked: list[int] = []

    def ask() -> str | None:
        asked.append(1)
        return tag

    monkeypatch.setattr(check, "ask", ask)
    return asked


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("v0.2.0", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("v0.1.0", "0.2.0", False),
        # What a comparison of text gets wrong, exactly once: at the tenth minor version.
        ("v0.10.0", "0.9.0", True),
        ("v0.9.0", "0.10.0", False),
        ("v1.0.0", "0.99.0", True),
        ("not-a-tag", "0.1.0", False),
        ("", "0.1.0", False),
    ],
)
def test_versions_are_compared_as_numbers(latest: str, current: str, expected: bool) -> None:
    assert updates.is_newer(latest, current) is expected


def test_the_about_page_names_version_licence_and_where_it_comes_from(client: TestClient, account: Account) -> None:
    about = client.get("/api/v1/about").json()
    assert about["version"] == __version__
    assert about["license"] == "AGPL-3.0"
    assert about["repo_url"] == "https://github.com/DerKezorm/nexpaper"
    assert about["releases_url"] == "https://github.com/DerKezorm/nexpaper/releases"
    # The project pages are switched off: no project page, the about page leaves the row out (U18).
    assert about["project_url"] == ""


def test_only_the_operator_sees_the_answer_switches_or_asks(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = answers(monkeypatch, "v99.0.0")
    seen = client.get("/api/v1/about/updates").json()
    assert (seen["update_check"], seen["checked"], seen["latest"], seen["newer"]) == (True, True, "v99.0.0", True)
    assert seen["release_url"] == "https://github.com/DerKezorm/nexpaper/releases/tag/v99.0.0"
    assert seen["hidden"] is False
    # A member gets the form of before, every field empty, and its page never asks (U15, U21).
    anna = person("anna")
    hidden = anna.get("/api/v1/about/updates")
    assert hidden.status_code == 200
    assert hidden.json() == {"update_check": False, "checked": False, "latest": None, "newer": False,
                             "checked_at": None, "release_url": None, "hidden": True}
    updates.forget()
    anna.get("/api/v1/about/updates")
    assert len(asked) == 1
    assert anna.post("/api/v1/about/updates/check").status_code == 403
    assert anna.put("/api/v1/about/updates", json={"update_check": False}).status_code == 403
    # Without an account: nothing.
    assert TestClient(client.app).get("/api/v1/about/updates").status_code == 401


def test_on_by_default_asked_once_a_day_and_again_when_a_day_is_over(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = answers(monkeypatch, "v0.0.1")
    first = client.get("/api/v1/about/updates").json()
    assert (first["update_check"], first["checked"], first["newer"]) == (True, True, False)
    client.get("/api/v1/about/updates")
    client.get("/api/v1/about/updates")
    assert len(asked) == 1
    # A day later the next look asks again.
    old = check._known
    assert old is not None and old.checked_at is not None
    check._known = updates.State(
        current=old.current, latest=old.latest, checked_at=old.checked_at - timedelta(hours=25)
    )
    client.get("/api/v1/about/updates")
    assert len(asked) == 2


def test_off_means_not_by_itself_and_the_button_still_asks(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = answers(monkeypatch, "v99.0.0")
    off = client.put("/api/v1/about/updates", json={"update_check": False}).json()
    assert (off["update_check"], off["checked"], off["latest"]) == (False, False, None)
    assert client.get("/api/v1/about/updates").json()["checked"] is False
    assert asked == []
    now = client.post("/api/v1/about/updates/check").json()
    assert (now["update_check"], now["checked"], now["newer"]) == (False, True, True)
    assert len(asked) == 1
    # Switched on again: from then on by itself.
    assert client.put("/api/v1/about/updates", json={"update_check": True}).json()["update_check"] is True


def test_the_button_asks_even_within_the_day(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = answers(monkeypatch, "v0.0.1")
    client.get("/api/v1/about/updates")
    client.post("/api/v1/about/updates/check")
    assert len(asked) == 2


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("no network"),
        httpx.ReadTimeout("slow"),
        httpx.InvalidURL("bad address"),  # not an httpx.HTTPError: a list of names would miss it
        ValueError("not JSON"),
        RuntimeError("anything else"),
    ],
)
def test_a_failure_at_github_breaks_nothing(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    class Broken:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, *args: object, **kwargs: object) -> httpx.Response:
            raise failure

        def stream(self, *args: object, **kwargs: object) -> httpx.Response:
            raise failure

    monkeypatch.setattr(check.httpx, "Client", Broken)
    answer = client.get("/api/v1/about/updates")
    assert answer.status_code == 200
    assert (answer.json()["checked"], answer.json()["latest"], answer.json()["newer"]) == (True, None, False)
    assert client.post("/api/v1/about/updates/check").status_code == 200


def test_a_private_repository_or_an_error_page_is_no_answer(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    def transport(status: int, body: object) -> type:
        def make(*args: object, **kwargs: object) -> httpx.Client:
            return REAL_CLIENT(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)))

        return make  # type: ignore[return-value]

    # While the repository is private GitHub says "not found".
    monkeypatch.setattr(check.httpx, "Client", transport(404, {"message": "Not Found"}))
    assert client.post("/api/v1/about/updates/check").json()["latest"] is None
    monkeypatch.setattr(check.httpx, "Client", transport(200, {"tag_name": "v9.9.9"}))
    shown = client.post("/api/v1/about/updates/check").json()
    assert (shown["latest"], shown["newer"]) == ("v9.9.9", True)
    # An error page is no answer, whatever it carries; what the last good check found stays (review before 1.0.0).
    monkeypatch.setattr(check.httpx, "Client", transport(503, {"tag_name": "v1.2.3"}))
    assert client.post("/api/v1/about/updates/check").json()["latest"] == "v9.9.9"
    updates.forget()
    assert client.post("/api/v1/about/updates/check").json()["latest"] is None
    monkeypatch.setattr(check.httpx, "Client", transport(200, ["not", "a", "release"]))
    assert client.post("/api/v1/about/updates/check").json()["latest"] is None


def test_the_question_goes_to_the_releases_of_nexpaper_and_carries_nothing_else(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []

    def make(*args: object, headers: dict[str, str] | None = None, **kwargs: object) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"tag_name": "v0.0.1"})

        # The headers the module gives its client, the rest of the network a stand-in.
        return REAL_CLIENT(transport=httpx.MockTransport(handle), headers=headers)

    monkeypatch.setattr(check.httpx, "Client", make)
    monkeypatch.setattr(updates, "get_settings", lambda: type("S", (), {"update_url": ""})())
    client.post("/api/v1/about/updates/check")
    assert [str(request.url) for request in seen] == ["https://api.github.com/repos/DerKezorm/nexpaper/releases/latest"]
    assert seen[0].method == "GET" and seen[0].content == b""
    assert "cookie" not in seen[0].headers and "authorization" not in seen[0].headers
    # A neutral name, without the version of this server (U10).
    assert seen[0].headers["user-agent"] == "nex-update-check"


def test_a_setup_page_of_before_stores_nothing_and_the_check_stays_on(client: TestClient) -> None:
    """U1 for an old page (1.12.0 sends no box): nothing is stored, the daily check stays on as before; the box of the
    new page is stored as given (the contract tests hold that)."""
    from app.db import SessionLocal
    from app.models import Setting

    from .conftest import PASSWORD, SETUP_CODE

    made = client.post("/api/v1/setup", json={"code": SETUP_CODE, "name": "boss", "password": PASSWORD})
    assert made.status_code == 200
    with SessionLocal() as db:
        assert db.get(Setting, "update_check") is None
    assert client.get("/api/v1/about/updates").json()["update_check"] is True
