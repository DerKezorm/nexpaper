"""The routes of "What's new" in the app, on the contract's own texts (``wasneu_contract.texts``, running 2.3.0): who
reads what, what an account read and how it puts it away, the languages, the sections for operators, the routes of
before (W5 to W10, W18). Copied unchanged into every app."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import wasneu_contract
from wasneu_contract import RUNNING


def _versions(items: list[dict[str, Any]]) -> list[str]:
    return [item["version"] for item in items]


def _state(app: Any, role: str, seen: str, language: str | None = "en") -> dict[str, Any]:
    app.set_seen(role, seen)
    query = f"?language={language}" if language else ""
    answer = app.client(role).get(f"{app.prefix}{query}")
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_without_a_session_nothing_is_read_and_nothing_put_away(app: Any, anonymous: Any, swapped: ModuleType) -> None:
    assert anonymous.get(app.prefix).status_code == 401
    assert anonymous.get(f"{app.prefix}/history").status_code == 401
    assert anonymous.post(f"{app.prefix}/seen").status_code == 401
    for route in app.old_seen:
        assert anonymous.post(route).status_code == 401, route


def test_an_account_reads_what_came_after_its_version_the_newest_first(app: Any, swapped: ModuleType) -> None:
    found = _state(app, "member", "2.2.0")
    assert (found["version"], found["seen"]) == (RUNNING, "2.2.0")
    assert _versions(found["unread"]) == [RUNNING, "2.2.1"]
    assert found["more"] is False and found["earlier"] is True
    assert found["current"]["version"] == RUNNING
    first = found["unread"][0]
    assert (first["language"], first["lead"]) == ("en", f"Lead en {RUNNING}")
    assert first["sections"][0]["title"] == f"Part en {RUNNING}" and first["small"] == [f"Small en {RUNNING}"]


def test_sections_for_operators_reach_only_operators(app: Any, swapped: ModuleType) -> None:
    member = _state(app, "member", "2.0.0")
    operator = _state(app, "operator", "2.0.0")
    # 2.1.0 has only a section for operators: a member has no text of it at all (W8).
    assert _versions(member["unread"]) == [RUNNING, "2.2.1", "2.2.0"]
    assert _versions(operator["unread"]) == [RUNNING, "2.2.1", "2.2.0", "2.1.0"]
    assert [part["title"] for part in member["unread"][0]["sections"]] == [f"Part en {RUNNING}"]
    assert [part.get("operator", False) for part in operator["unread"][0]["sections"]] == [False, True]
    history = app.client("member").get(f"{app.prefix}/history?language=en").json()
    assert "2.1.0" not in _versions(history["entries"])
    assert all(not part.get("operator") for item in history["entries"] for part in item["sections"])


def test_after_a_long_time_away_at_most_five_texts_and_the_rest_under_earlier(app: Any, swapped: ModuleType) -> None:
    operator = _state(app, "operator", "0.9.0")
    assert _versions(operator["unread"]) == [RUNNING, "2.2.1", "2.2.0", "2.1.0", "2.0.0"]
    assert operator["more"] is True
    member = _state(app, "member", "0.9.0")
    assert _versions(member["unread"]) == [RUNNING, "2.2.1", "2.2.0", "2.0.0", "1.0.0"] and member["more"] is False


@pytest.mark.parametrize("seen", ["", "garbage", "v2.0.0", "2.2"])
def test_a_version_read_in_no_known_form_shows_only_the_newest_text(app: Any, swapped: ModuleType, seen: str) -> None:
    assert _versions(_state(app, "member", seen)["unread"]) == [RUNNING]


@pytest.mark.parametrize("seen", [RUNNING, "2.5.0", "10.0.0"])
def test_nothing_is_unread_at_the_running_version_or_after_a_step_back(
    app: Any, swapped: ModuleType, seen: str
) -> None:
    found = _state(app, "member", seen)
    assert found["unread"] == [] and found["current"]["version"] == RUNNING


def test_a_fix_without_its_own_text_shows_no_banner_and_about_the_text_before(app: Any, tmp_path: Path) -> None:
    with wasneu_contract.swapped(app, tmp_path / "fix", version="2.3.1"):
        found = _state(app, "member", RUNNING)
        assert found["version"] == "2.3.1" and found["unread"] == []
        assert found["current"]["version"] == RUNNING
        # Who read only 2.2.0 still reads 2.3.0 and 2.2.1 after the fix.
        assert _versions(_state(app, "member", "2.2.0")["unread"]) == [RUNNING, "2.2.1"]


def test_the_history_holds_every_text_up_to_the_running_version_and_nothing_broken(
    app: Any, operator: Any, swapped: ModuleType
) -> None:
    answer = operator.get(f"{app.prefix}/history?language=en")
    assert answer.status_code == 200, answer.text
    found = answer.json()
    assert found["version"] == RUNNING
    # 2.4.0 is not out yet; 2.0.5 (empty) and v2.0.6 (no version) are left out, never shown half.
    assert _versions(found["entries"]) == [RUNNING, "2.2.1", "2.2.0", "2.1.0", "2.0.0", "1.0.0"]


def test_each_language_reads_its_own_text_and_english_where_it_has_none(app: Any, swapped: ModuleType) -> None:
    other = next((code for code in swapped.current().languages if code != "en"), None)
    if other is None:
        pytest.skip("the app has English only")
    for asked in (other, f"{other}-XY"):
        found = _state(app, "member", "0.9.0", asked)
        assert {item["version"]: item["language"] for item in found["unread"]} == {
            RUNNING: other, "2.2.1": other, "2.2.0": other, "2.0.0": other, "1.0.0": "en"
        }, asked
        assert found["unread"][0]["lead"] == f"Lead {other} {RUNNING}"


@pytest.mark.parametrize("asked", ["nl", "xx-YY", "../../etc/passwd", "en\n", "EN"])
def test_a_language_without_texts_reads_english(app: Any, swapped: ModuleType, asked: str) -> None:
    app.set_seen("member", "2.2.0")
    answer = app.client("member").get(app.prefix, params={"language": asked})
    assert answer.status_code == 200, answer.text
    assert {item["language"] for item in answer.json()["unread"]} == {"en"}


def test_putting_away_is_the_accounts_own_and_holds(app: Any, swapped: ModuleType) -> None:
    app.set_seen("member", "2.0.0")
    app.set_seen("operator", "2.0.0")
    answer = app.client("member").post(f"{app.prefix}/seen")
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"seen": RUNNING}
    assert app.stored_seen("member") == RUNNING
    assert app.stored_seen("operator") == "2.0.0"
    assert app.client("member").get(f"{app.prefix}?language=en").json()["unread"] == []
    assert _versions(app.client("operator").get(f"{app.prefix}?language=en").json()["unread"])[0] == RUNNING


def test_the_routes_of_before_put_the_running_version_away_as_well(app: Any, swapped: ModuleType) -> None:
    for route in app.old_seen:
        app.set_seen("member", "2.0.0")
        answer = app.client("member").post(route)
        assert answer.status_code == 200, (route, answer.text)
        assert app.stored_seen("member") == RUNNING, route


def test_the_account_still_names_the_version_it_read(app: Any, swapped: ModuleType) -> None:
    if not app.me:
        pytest.skip("the app has no route that names the account")
    app.set_seen("member", "2.2.0")
    assert app.client("member").get(app.me).json()[app.me_field] == "2.2.0"


def test_a_new_account_starts_with_the_running_version_read(app: Any, nexwasneu: ModuleType) -> None:
    """A fresh account is not greeted with news (W5); the app's own version, not the contract's."""
    assert app.new_account_seen() == nexwasneu.current().running() == nexwasneu.seen_for_new_account()


def test_the_routes_stand_in_the_description(app: Any, anonymous: Any) -> None:
    answer = anonymous.get("/openapi.json")
    if answer.status_code != 200:
        pytest.skip("the app shows no description")
    paths = answer.json()["paths"]
    for path, method in ((app.prefix, "get"), (f"{app.prefix}/history", "get"), (f"{app.prefix}/seen", "post")):
        assert method in paths.get(path, {}), path
