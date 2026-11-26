"""Making a backup over the old way (``POST <legacy_prefix>``) and the module's own (``POST <prefix>/backups``) keeps
what the apps' own routes had on ``konten`` (measured in all six apps): a note longer than 200 characters is refused
with 422, and without a session the request is refused with 401 (with the headers of the app's own page; a foreign
form without them meets the app's own guard before). Nothing is made either way. Since 1.0.3 (E63) the note is the
page's too ("Jetzt sichern" asks for it): optional, without a body as before, blank is no note, and the list shows it.
Copied unchanged into every app."""

from __future__ import annotations

from typing import Any

from sicherung_contract import package_of


def _ways(app: Any) -> list[str]:
    return [f"{app.prefix}/backups"] + ([app.legacy_prefix] if app.legacy_prefix else [])


def _count(app: Any) -> int:
    return len(package_of(app).archives.entries())


def test_a_note_longer_than_200_characters_is_refused_with_422(app: Any) -> None:
    client = app.operator()
    before = _count(app)
    for way in _ways(app):
        assert client.post(way, json={"note": "x" * 201}).status_code == 422, way
    assert _count(app) == before
    made = client.post(_ways(app)[-1], json={"note": "x" * 200})
    assert made.status_code == 201, made.text


def _notes(app: Any) -> dict[str, str]:
    answer = app.operator().get(f"{app.prefix}/backups")
    assert answer.status_code == 200, answer.text
    return {item["name"]: item["note"] for item in answer.json()["backups"]}


def test_a_note_is_optional_blank_is_none_and_the_list_shows_it(app: Any) -> None:
    """E63: every way takes the note or none; without a body it goes as before (E53), only blanks make no note, the
    note is kept without the blanks around it, 200 characters fit, and the list names each backup's own note."""
    client = app.operator()
    for way in _ways(app):
        made: dict[str, str] = {}
        for body, kept in ((None, ""), ({}, ""), ({"note": ""}, ""), ({"note": "   "}, ""),
                           ({"note": "  vor dem Umzug  "}, "vor dem Umzug"), ({"note": "ü" * 200}, "ü" * 200)):
            answer = client.post(way, json=body) if body is not None else client.post(way)
            assert answer.status_code == 201, (way, body, answer.text)
            made[answer.json()["name"]] = kept
        listed = _notes(app)
        assert {name: listed[name] for name in made} == made, way


def test_without_a_session_nothing_is_made_and_the_answer_is_401(app: Any) -> None:
    stranger = app.anonymous()
    before = _count(app)
    for way in _ways(app):
        assert stranger.post(way).status_code == 401, way
        assert stranger.post(way, json={"note": "x"}).status_code == 401, way
    assert _count(app) == before
