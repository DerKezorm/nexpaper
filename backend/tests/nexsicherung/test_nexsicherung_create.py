"""Making a backup over the old way (``POST <legacy_prefix>``) and the module's own (``POST <prefix>/backups``) keeps
what the apps' own routes had on ``konten`` (measured in all six apps): a note longer than 200 characters is refused
with 422, and without a session the request is refused with 401 (with the headers of the app's own page; a foreign
form without them meets the app's own guard before). Nothing is made either way. Copied unchanged into every app."""

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


def test_without_a_session_nothing_is_made_and_the_answer_is_401(app: Any) -> None:
    stranger = app.anonymous()
    before = _count(app)
    for way in _ways(app):
        assert stranger.post(way).status_code == 401, way
        assert stranger.post(way, json={"note": "x"}).status_code == 401, way
    assert _count(app) == before
