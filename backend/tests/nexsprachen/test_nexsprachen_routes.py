"""The routes in the app: the list of built-in and own languages, reading without signing in (or not, as the app
says), uploading and removing only for the operator, the template, a file over a built-in language. Copied unchanged
into every app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sprachen_contract import files_in, upload

DUTCH = {"_meta": {"name": "Nederlands"}, "common": {"close": "Sluiten"}, "nav": {"notes": "Notities"}}


def _codes(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [entry["code"] for entry in response.json()]


def test_the_list_holds_the_built_in_languages_and_nothing_else_at_first(app: Any, reader: Any) -> None:
    listed = reader.get(app.prefix)
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {"code": code, "name": name, "keys": 0, "built_in": True, "own": False} for code, name in app.built_in.items()
    ]
    assert listed.headers.get("cache-control") == "no-cache"


def test_the_operator_adds_a_language_and_the_reader_gets_only_its_texts(app: Any, operator: Any, reader: Any) -> None:
    added = upload(operator, app.prefix, "nl", json.dumps(DUTCH).encode())
    assert added.status_code == 200, added.text
    assert added.json() == {"code": "nl", "name": "Nederlands", "keys": 2}
    entries = reader.get(app.prefix).json()
    assert entries[-1] == {"code": "nl", "name": "Nederlands", "keys": 2, "built_in": False, "own": True}
    assert [entry["code"] for entry in entries[:-1]] == list(app.built_in)
    texts = reader.get(f"{app.prefix}/nl")
    assert texts.status_code == 200 and texts.json() == {"common": {"close": "Sluiten"}, "nav": {"notes": "Notities"}}
    assert set(entries[-1]) == {"code", "name", "keys", "built_in", "own"}


def test_reading_without_signing_in_is_as_the_app_says(app: Any, operator: Any, anonymous: Any) -> None:
    assert upload(operator, app.prefix, "nl", json.dumps(DUTCH).encode()).status_code == 200
    for path in (app.prefix, f"{app.prefix}/nl", f"{app.prefix}/template"):
        answer = anonymous.get(path)
        if app.public_read:
            assert answer.status_code in ((200, 404) if path.endswith("template") else (200,)), (path, answer.text)
        else:
            assert answer.status_code in (401, 403), (path, answer.status_code)
            assert "Sluiten" not in answer.text


def test_a_member_and_a_stranger_neither_add_nor_remove(app: Any, operator: Any, member: Any, anonymous: Any,
                                                         folder: Path) -> None:
    assert upload(operator, app.prefix, "nl", json.dumps(DUTCH).encode()).status_code == 200
    before = (folder / "nl.json").read_bytes()
    for client in (member, anonymous):
        assert upload(client, app.prefix, "fr", b'{"a": "b"}').status_code in (401, 403)
        assert upload(client, app.prefix, "nl", b'{"a": "b"}').status_code in (401, 403)
        assert client.delete(f"{app.prefix}/nl").status_code in (401, 403)
    assert files_in(folder) == ["nl.json"] and (folder / "nl.json").read_bytes() == before


def test_removing_a_language_and_one_that_is_not_there(app: Any, operator: Any, reader: Any) -> None:
    assert upload(operator, app.prefix, "nl", json.dumps(DUTCH).encode()).status_code == 200
    assert operator.delete(f"{app.prefix}/nl").status_code == 204
    assert _codes(reader.get(app.prefix)) == list(app.built_in)
    gone = operator.delete(f"{app.prefix}/nl")
    assert gone.status_code == 404 and app.refusal(gone)[0] == "not_found"
    missing = reader.get(f"{app.prefix}/nl")
    assert missing.status_code == 404 and app.refusal(missing)[0] == "not_found"


def test_a_file_for_a_built_in_language_holds_only_the_texts_it_replaces(app: Any, operator: Any, reader: Any) -> None:
    code, name = next(iter(app.built_in.items()))
    assert reader.get(f"{app.prefix}/{code}").status_code == 404, "a built-in language has no file of its own at first"
    assert upload(operator, app.prefix, code, b'{"common": {"close": "Zumachen"}}').status_code == 200
    entry = reader.get(app.prefix).json()[0]
    assert entry == {"code": code, "name": name, "keys": 1, "built_in": True, "own": True}
    assert reader.get(f"{app.prefix}/{code}").json() == {"common": {"close": "Zumachen"}}
    assert operator.delete(f"{app.prefix}/{code}").status_code == 204
    assert reader.get(app.prefix).json()[0]["own"] is False


def test_replacing_a_language_takes_the_new_file_whole(app: Any, operator: Any, reader: Any) -> None:
    assert upload(operator, app.prefix, "nl", json.dumps(DUTCH).encode()).status_code == 200
    assert upload(operator, app.prefix, "nl", b'{"only": "dit"}').status_code == 200
    assert reader.get(f"{app.prefix}/nl").json() == {"only": "dit"}
    assert reader.get(app.prefix).json()[-1]["name"] == "nl", "without _meta the name is the code"


def test_the_template_is_the_apps_english_texts_with_a_name_to_fill_in(app: Any, reader: Any) -> None:
    answer = reader.get(f"{app.prefix}/template")
    if not app.has_template:
        assert answer.status_code == 404
        return
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-disposition"].startswith("attachment; filename=")
    assert answer.headers["content-disposition"].endswith('-language-template.json"')
    data = answer.json()
    assert set(data["_meta"]) == {"name"} and len(data) >= 2
    assert all(isinstance(value, (str, dict)) for value in data.values())


def test_a_file_too_large_names_the_limit_and_leaves_nothing(app: Any, operator: Any, nexsprachen: Any,
                                                             folder: Path) -> None:
    answer = upload(operator, app.prefix, "nl", b'{"a": "' + b"x" * (nexsprachen.MAX_BYTES + 10) + b'"}')
    assert answer.status_code == 413
    code, values = app.refusal(answer)
    assert code == "too_large" and values.get("max_kb") == 512
    assert files_in(folder) == []


def test_every_further_prefix_serves_the_same(app: Any, operator: Any, reader: Any) -> None:
    assert upload(operator, app.prefix, "nl", json.dumps(DUTCH).encode()).status_code == 200
    for prefix in app.also:
        assert _codes(reader.get(prefix)) == [*app.built_in, "nl"], prefix
        assert reader.get(f"{prefix}/nl").json()["common"] == {"close": "Sluiten"}
