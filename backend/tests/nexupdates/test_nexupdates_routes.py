"""The update check in the app, over its real routes, with the stand-in for GitHub counting every question: off means
nothing goes out by itself (not on opening the page, not in the background), the button asks also when off, only the
operator switches and asks, a member learns nothing of the check, not even the switch (U2, U15), the bell hears of each
new version once (U3), in the language of each operator's account (U17), the setup asks once (U1), and a version from
before keeps its switch. Copied unchanged into every app."""

from __future__ import annotations

from typing import Any

import pytest
from updates_contract import background_stays_quiet, plug


def _state(client: Any, app: Any) -> dict[str, Any]:
    answer = client.get(f"{app.prefix}/updates")
    assert answer.status_code == 200, answer.text
    return answer.json()


def _switch(client: Any, app: Any, on: bool) -> Any:
    return client.put(f"{app.prefix}/updates", json={"update_check": on})


@pytest.mark.parametrize(("latest", "than", "newer"), [("v0.10.0", "0.9.0", True), ("v1.10.0", "1.9.9", True),
                                                       ("v0.9.0", "0.10.0", False), ("v2.0.0", "10.0.0", False)])
def test_versions_are_compared_as_numbers(nexupdates: Any, latest: str, than: str, newer: bool) -> None:
    assert nexupdates.is_newer(latest, than) is newer


def test_the_about_page_names_version_licence_and_where_it_comes_from(app: Any, anonymous: Any,
                                                                      nexupdates: Any) -> None:
    """U18: the project page is what the app gives (empty while the pages are off; then the page shows no row)."""
    config = nexupdates.current()
    about = anonymous.get(app.prefix).json()
    assert about["version"] == config.running()
    assert about["repo_url"] == f"https://github.com/{config.repo}"
    assert about["releases_url"] == f"https://github.com/{config.repo}/releases"
    assert about["project_url"] == config.project_url and about["license"] == config.license


def test_off_nothing_goes_out_by_itself(app: Any, operator: Any, member: Any, github: Any) -> None:
    assert _switch(operator, app, False).status_code == 200
    assert app.stored_switch() not in (None, True, "1", 1)
    for _ in range(2):
        operator.get(app.prefix)
        assert _state(operator, app)["update_check"] is False
        member.get(f"{app.prefix}/updates")
        app.look()
    assert github.requests == []
    if app.has_bell:
        assert app.bell() == []


def test_the_button_asks_also_when_off_and_only_the_operator_may(app: Any, operator: Any, member: Any,
                                                                  anonymous: Any, github: Any) -> None:
    _switch(operator, app, False)
    assert member.post(f"{app.prefix}/updates/check").status_code == 403
    assert anonymous.post(f"{app.prefix}/updates/check").status_code in (401, 403)
    assert github.requests == []
    found = operator.post(f"{app.prefix}/updates/check").json()
    assert (found["update_check"], found["checked"], found["latest"], found["newer"]) == (False, True, "v99.0.0", True)
    assert found["release_url"].endswith("/releases/tag/v99.0.0")
    assert len(github.requests) == 1


def test_only_the_operator_switches(app: Any, operator: Any, member: Any, anonymous: Any) -> None:
    before = app.stored_switch()
    assert _switch(member, app, False).status_code == 403
    assert _switch(anonymous, app, False).status_code in (401, 403)
    assert app.stored_switch() == before
    assert _switch(operator, app, False).json()["update_check"] is False
    assert _switch(operator, app, True).json()["update_check"] is True


def test_on_the_operator_s_page_asks_once_a_day(app: Any, operator: Any, github: Any) -> None:
    _switch(operator, app, True)
    first = _state(operator, app)
    assert (first["checked"], first["latest"], first["newer"]) == (True, "v99.0.0", True)
    _state(operator, app)
    _state(operator, app)
    assert len(github.requests) == 1


def test_a_member_learns_nothing_of_the_check_not_even_the_switch(app: Any, operator: Any, member: Any,
                                                                  anonymous: Any, github: Any, nexupdates: Any) -> None:
    """U15, U21: the old route keeps its form for every account (nexnotes answered each with 200), but a member gets
    every field of the state and the switch empty in its old type, ``hidden`` true, and never sets off a question;
    without a session 401."""
    _switch(operator, app, True)  # switching on is the operator's decision: it may ask at once
    shown = _state(operator, app)
    github.requests.clear()
    nexupdates.forget()
    answer = member.get(f"{app.prefix}/updates")
    assert answer.status_code == 200, answer.status_code
    seen = answer.json()
    assert set(seen) == set(shown), "the same fields as the operator's"
    assert seen == {"update_check": False, "checked": False, "latest": None, "newer": False, "checked_at": None,
                    "release_url": None, "hidden": True}
    assert shown["hidden"] is False and shown["update_check"] is True
    assert "99.0.0" not in answer.text
    assert anonymous.get(f"{app.prefix}/updates").status_code == 401
    assert member.get(app.prefix).json()["version"] == nexupdates.current().running()
    assert github.requests == []


#: ``UpdatesOut`` as nexnotes described it before the module (E53): the module may only add to it (U21).
OLD_UPDATES_OUT = {
    "update_check": {"type": "boolean"},
    "checked": {"type": "boolean"},
    "latest": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "newer": {"type": "boolean"},
    "checked_at": {"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
    "release_url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
}
OLD_REQUIRED = {"update_check"}


def _types(schema: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in schema.items() if key not in ("title", "default", "description")}


def test_the_description_of_the_state_only_adds_to_the_old_one(app: Any) -> None:
    """U21 (E53): a generated client of before (nexpaper-ios) keeps reading every answer of the state: each old field
    in its old type, nothing taken from what was required; the one new field is ``hidden``, a boolean."""
    described = app.description()
    schemas = described["components"]["schemas"]
    for path, method in ((f"{app.prefix}/updates", "get"), (f"{app.prefix}/updates/check", "post"),
                         (f"{app.prefix}/updates", "put")):
        answer = described["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        schema = schemas[answer["$ref"].rsplit("/", 1)[-1]]
        found = {key: _types(value) for key, value in schema["properties"].items()}
        assert {key: found.get(key) for key in OLD_UPDATES_OUT} == OLD_UPDATES_OUT, (path, method)
        assert set(found) - set(OLD_UPDATES_OUT) == {"hidden"} and found["hidden"] == {"type": "boolean"}
        assert OLD_REQUIRED <= set(schema.get("required", ())), (path, method)


def test_the_operator_sees_no_release_yet_where_the_repository_is_not_public(app: Any, operator: Any,
                                                                              github: Any) -> None:
    """U20: GitHub answers 404 for a private repository; the card says "Noch keine Veröffentlichung gefunden."."""
    github.status, github.tag = 404, None
    found = operator.post(f"{app.prefix}/updates/check").json()
    assert (found["checked"], found["latest"], found["newer"], found["release_url"]) == (True, None, False, None)


def test_the_question_carries_nothing_of_the_server(app: Any, operator: Any, github: Any, nexupdates: Any) -> None:
    operator.post(f"{app.prefix}/updates/check")
    request = github.requests[0]
    assert request.method == "GET" and request.url == nexupdates.current().url()
    assert request.headers["user-agent"] == "nex-update-check"
    assert request.headers["accept"] == "application/vnd.github+json"
    for name in ("cookie", "authorization", "x-forwarded-for"):
        assert name not in request.headers, name
    assert nexupdates.current().running() not in request.headers["user-agent"]


def test_only_a_tag_of_the_fixed_form_counts(app: Any, operator: Any, github: Any) -> None:
    for tag in ("v1.2.3-rc1", "latest", "<script>", "v1.2", "v99.0.0.1"):
        github.tag = tag
        found = operator.post(f"{app.prefix}/updates/check").json()
        assert (found["latest"], found["newer"], found["release_url"]) == (None, False, None), tag


def test_errors_and_oversized_answers_are_no_answer_and_keep_the_last_good_one(app: Any, operator: Any,
                                                                              github: Any) -> None:
    for status, body in ((404, None), (500, None), (200, b"not json"), (200, b'{"tag_name": "v9.9.9", "x": "'
                                                                           + b"y" * (300 * 1024) + b'"}')):
        github.status, github.body = status, body
        found = operator.post(f"{app.prefix}/updates/check").json()
        assert found["latest"] is None, (status, body and body[:20])
    github.status, github.body, github.tag = 200, None, "v99.1.0"
    assert operator.post(f"{app.prefix}/updates/check").json()["latest"] == "v99.1.0"
    github.fail = True
    kept = operator.post(f"{app.prefix}/updates/check").json()
    assert (kept["latest"], kept["newer"]) == ("v99.1.0", True)


def test_the_bell_hears_of_each_new_version_once(app: Any, operator: Any, github: Any, nexupdates: Any) -> None:
    _switch(operator, app, True)
    if not app.has_bell:
        background_stays_quiet(app, github)
        return
    app.look()
    app.look()
    assert app.bell() == ["v99.0.0"]
    nexupdates.forget()
    app.look()
    assert app.bell() == ["v99.0.0"], "the told version is stored, a restart does not tell again"
    github.tag = "v98.0.0"
    nexupdates.forget()
    app.look()
    assert app.bell() == ["v99.0.0"], "never about an older version than the one told"
    github.tag = "v99.0.1"
    nexupdates.forget()
    app.look()
    assert app.bell() == ["v99.0.0", "v99.0.1"]


def test_the_bell_speaks_the_language_of_each_operator_s_account(app: Any, operator: Any, github: Any,
                                                                  nexupdates: Any) -> None:
    """U17: one notice per operator, in the language of the account (as the mails of post, E26)."""
    _switch(operator, app, True)
    if not app.has_bell:
        background_stays_quiet(app, github)
        return
    app.look()
    notices = app.bell_notices()
    assert notices, "no notice at all"
    for language, version, title in notices:
        assert version == "v99.0.0" and title == nexupdates.notice(language, version)["title"], (language, title)


def test_the_bell_never_hears_of_the_running_version_or_an_older_one(app: Any, operator: Any, github: Any,
                                                                       nexupdates: Any) -> None:
    _switch(operator, app, True)
    if not app.has_bell:
        background_stays_quiet(app, github)
        return
    running = nexupdates.parse(nexupdates.current().running())
    assert running is not None
    for tag in (f"v{running[0]}.{running[1]}.{running[2]}", "v0.0.1"):
        github.tag = tag
        nexupdates.forget()
        app.look()
    assert app.bell() == []


def test_the_setup_asks_once_and_a_new_installation_keeps_its_answer(app: Any, github: Any) -> None:
    assert app.stored_switch() is None
    app.setup(False)
    assert app.stored_switch() not in (None, True, "1", 1)
    app.look()
    assert github.requests == [] and (not app.has_bell or app.bell() == [])


def test_the_setup_ticked_checks_by_itself(app: Any, github: Any) -> None:
    app.setup(True)
    if not app.has_bell:
        # U19: nothing in the background; the first visit of an operator on "Über" asks, once.
        background_stays_quiet(app, github)
        operator = app.client("operator")
        assert _state(operator, app)["latest"] == "v99.0.0"
        _state(operator, app)
        assert len(github.requests) == 1
        return
    app.look()
    assert len(github.requests) == 1 and app.bell() == ["v99.0.0"]


def test_the_bell_is_given_exactly_where_the_app_has_one(app: Any, nexupdates: Any) -> None:
    """U-1 (0.1.2): an app tells the contract whether it has a bell (``has_bell``), and gives ``configure`` its
    ``on_newer`` exactly then."""
    assert (nexupdates.current().on_newer is not None) == app.has_bell


def test_devices_are_given_exactly_where_the_app_pairs_them(app: Any, nexupdates: Any) -> None:
    """U24 (0.1.3): an app with paired devices gives ``configure`` ``devices_want`` and ``on_devices``, else none."""
    config = nexupdates.current()
    assert (config.devices_want is not None and config.on_devices is not None) == app.has_devices
    assert (config.devices_want is None) == (config.on_devices is None)


def test_a_device_of_an_operator_that_wants_new_versions_counts_as_a_bell(app: Any, operator: Any, github: Any,
                                                                           nexupdates: Any) -> None:
    """U24: while such a device is there, the background looks at most once a day and tells it once per version,
    with a bell and without; without such a device an app without a bell stays as U19 says."""
    if not app.has_devices:
        return
    _switch(operator, app, True)
    app.want_on_device(False)
    if not app.has_bell:
        background_stays_quiet(app, github)
    else:
        app.look()
        assert app.bell() == ["v99.0.0"]
    assert app.devices_told() == []
    app.want_on_device(True)
    github.tag = "v99.0.1"
    nexupdates.forget()
    before = len(github.requests)
    app.look()
    app.look()
    assert len(github.requests) == before + 1, "at most once a day"
    assert app.devices_told() == ["v99.0.1"]
    if app.has_bell:
        assert app.bell() == ["v99.0.0", "v99.0.1"]
    nexupdates.forget()
    app.look()
    assert app.devices_told() == ["v99.0.1"], "each version once"
    app.want_on_device(False)
    github.tag = "v99.0.2"
    nexupdates.forget()
    app.look()
    assert app.devices_told() == ["v99.0.1"], "a device that no longer wants it hears nothing"


def test_off_a_device_that_wants_new_versions_changes_nothing(app: Any, operator: Any, github: Any,
                                                                nexupdates: Any) -> None:
    """U24: only while the operator allowed the check (U2)."""
    if not app.has_devices:
        return
    _switch(operator, app, False)
    app.want_on_device(True)
    for _ in range(2):
        nexupdates.forget()
        app.look()
    assert github.requests == [] and app.devices_told() == []


def test_a_switch_from_before_stays_as_it_was(app: Any, github: Any) -> None:
    """Test "Bestand": the version before switched off; after the update nothing goes out, the routes answer the
    same."""
    app.store_legacy_switch(False)
    app.restart()
    plug(app, github)
    operator = app.client("operator")
    assert _state(operator, app)["update_check"] is False
    app.look()
    assert github.requests == []
    app.store_legacy_switch(True)
    app.restart()
    plug(app, github)
    assert _state(app.client("operator"), app)["update_check"] is True


def test_every_further_prefix_serves_the_same(app: Any, operator: Any) -> None:
    for prefix in app.also:
        assert operator.get(prefix).json()["version"] == operator.get(app.prefix).json()["version"]
        assert operator.get(f"{prefix}/updates").status_code == 200
