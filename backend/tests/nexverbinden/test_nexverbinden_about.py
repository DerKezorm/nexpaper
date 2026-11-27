"""Since 0.1.13 (decisions V49 to V53): nexfolk asks the app what it has about the contact the account looks at
("In den anderen Apps"): how many, the next or the last one, where to open it; never contents, only in the areas the
connection was given, braked per connection. Runs only in an app that grants a purpose about a person
(``about_purpose`` in the adapter), against a reference that plays nexfolk. Copied unchanged into every app."""

from __future__ import annotations

from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from verbinden_partner import ROLES


def _person(pkg: ModuleType, **given: Any) -> Any:
    return pkg.Person(**({"name": "Pat Example", "mails": ("pat@example.com",), "phones": ("+49 30 1234567",)} | given))


def _ask(w: Any, person: Any) -> Any:
    return w.pkg.about(
        w.partner.store,
        w.partner.config,
        ROLES["owner"][0],
        w.app.config().app_name,
        w.app.about_purpose,
        person,
        datetime.now(UTC),
    )


def _token(w: Any) -> str:
    return w.pkg.access(
        w.partner.store, w.partner.config, ROLES["owner"][0], w.app.config().app_name, datetime.now(UTC)
    ).token


def test_the_purpose_is_one_of_the_catalog_about_a_person(about_world: Any) -> None:
    w = about_world
    purpose = w.pkg.CATALOG.purpose(w.app.config().app_name, w.app.about_purpose)
    assert purpose.person and purpose.level == "read"
    assert w.app.about_purpose in w.pkg.CATALOG.uses("nexfolk", w.app.config().app_name)
    assert "nexfolk" in w.app.config().usable
    # V53: both cards and the consent page say that nexfolk sends a person.
    assert w.card("app")["receives_person"] is True and w.card("app")["sends_person"] is False
    assert w.card("partner")["sends_person"] is True
    started = w.start("partner")
    info = w.app.client("owner").get(f"{w.pkg.PREFIX}/consent", params=w.consent_params(started.json()["go"])).json()
    assert info["partner_sends_person"] is True and info["app_sends_person"] is False


def test_nexfolk_learns_how_many_and_the_next_only_in_the_areas_given(about_world: Any) -> None:
    w = about_world
    choice = [area["id"] for area in w.card("app")["areas_choice"]]
    assert choice, "a purpose about a person has areas: the card asks for them"
    given = choice[:1]
    done = w.connect("partner", areas=given if len(choice) > 1 else None)
    assert done.status_code == 200, done.text
    person = _person(w.pkg)
    assert _ask(w, person)["count"] == 0
    for area in choice[:2]:
        w.app.about_seed(w.app.about_purpose, area, person)
    found = _ask(w, person)
    assert set(found) == {"count", "next", "last", "open"}
    # Only the areas given count (with one area the account has, that one).
    assert found["count"] == 1
    assert found["next"] is not None or found["last"] is not None
    assert found["open"] is None or found["open"].startswith(w.app.base + "/")
    titles = w.pkg.CATALOG.purpose(w.app.config().app_name, w.app.about_purpose).titles
    for moment in (found["next"], found["last"]):
        if moment is not None:
            assert len(moment["title"]) <= 200 and (titles or moment["title"] == "")
    # Somebody else: nothing.
    nobody = w.pkg.Person(name="Nobody Elsewhere", mails=("nobody@example.org",))
    assert _ask(w, nobody)["count"] == 0


def test_a_question_names_a_person_within_the_limits(about_world: Any) -> None:
    w = about_world
    assert w.connect("partner").status_code == 200
    token = _token(w)
    route = f"{w.pkg.PREFIX}/about/{w.app.about_purpose}"
    program = w.program()
    asked = {"Authorization": f"Bearer {token}"}
    assert program.get(route, params={"name": "Pat Example"}, headers=asked).status_code == 200
    for wrong in ({}, {"mail": [f"m{n}@example.com" for n in range(11)]}, {"mail": "no-at"}, {"phone": "call me"},
                  {"name": "x" * 201}, {"other": "1"}, {"name": "Pat", "mail": "no-at"}):  # fmt: skip
        found = program.get(route, params=wrong, headers=asked)
        assert found.status_code == 422 and found.json()["detail"]["code"] == "person_invalid", wrong
    assert program.get(route, params={"name": "Pat"}).status_code == 401
    assert (
        program.get(route, params={"name": "Pat"}, headers={**asked, "Origin": "https://x.example.com"}).status_code
        == 403
    )
    found = program.get(f"{w.pkg.PREFIX}/about/no.such", params={"name": "Pat"}, headers=asked)
    assert found.status_code == 404 and found.json()["detail"]["code"] == "about_unknown"
    # A purpose of the app that is not about a person is not asked here.
    own = w.pkg.CATALOG.purposes[w.app.config().app_name]
    for other in [pid for pid, purpose in own.items() if not purpose.person]:
        found = program.get(f"{w.pkg.PREFIX}/about/{other}", params={"name": "Pat"}, headers=asked)
        assert found.status_code == 404 and found.json()["detail"]["code"] == "about_unknown", other


def test_the_app_brakes_questions_per_connection(about_world: Any) -> None:
    w = about_world
    assert w.connect("partner").status_code == 200
    w.pkg.connect.BRAKE.forget()
    token = _token(w)
    route = f"{w.pkg.PREFIX}/about/{w.app.about_purpose}"
    program = w.program()
    asked = {"Authorization": f"Bearer {token}"}
    codes = [
        program.get(route, params={"name": "Pat"}, headers=asked).status_code
        for _ in range(w.app.config().about_per_minute + 1)
    ]
    assert codes[:-1] == [200] * w.app.config().about_per_minute
    assert codes[-1] == 429


def test_a_connection_without_the_purpose_learns_nothing(about_world: Any) -> None:
    """Only a connection that was given the purpose may ask; the app checks it at every question (``require``)."""
    from dataclasses import replace

    w = about_world
    assert w.connect("partner").status_code == 200
    token = _token(w)
    store = w.app.store
    connection = store.connection(w.app.account_id("owner"), "nexfolk")
    store.save(replace(connection, grants=tuple(p for p in connection.grants if p != w.app.about_purpose)))
    store.commit()
    found = w.program().get(
        f"{w.pkg.PREFIX}/about/{w.app.about_purpose}",
        params={"name": "Pat"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert found.status_code == 403 and found.json()["detail"]["code"] == "purpose_missing"


def test_a_connection_about_a_person_opens_nothing_else(about_world: Any) -> None:
    """Since 0.1.14 (found in nextime): the connection of nexfolk may ask about a person and nothing more; every other
    purpose of the app refuses it (403), also where the app's own routes take a token by its level ("read")."""
    w = about_world
    assert w.connect("partner").status_code == 200
    app = w.app.config().app_name
    asked = set(w.pkg.CATALOG.uses("nexfolk", app))
    for purpose in [p for p in w.pkg.CATALOG.purposes[app] if p not in asked]:
        path = w.app.probe(purpose)
        assert path, purpose
        answer = w.partner_calls_app(path)
        assert getattr(answer, "status", None) == 403, (purpose, answer)
