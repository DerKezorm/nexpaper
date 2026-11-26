"""What the module refuses in the app, and that a refusal writes nothing and names nothing internal: only a JSON object
of texts and groups of texts, at most 8 levels and 512 KB, UTF-8, no empty or reserved key, only a language code as a
file name, nothing outside the folder. Copied unchanged into every app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sprachen_contract import files_in, upload

DEEP = b'{"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "too deep"}}}}}}}}}'


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"no json", "not_json"),
        (b'{"a": 1}', "not_text"),
        (b'{"a": null}', "not_text"),
        (b'{"a": true}', "not_text"),
        (b'{"a": ["one", "two"]}', "not_text"),
        (b'{"a": NaN}', "not_text"),
        (b"{}", "no_texts"),
        (b'{"_meta": {"name": "Leer"}}', "no_texts"),
        (b'{"a": {}}', "no_texts"),
        (b'["no", "object"]', "not_object"),
        (b'"only a text"', "not_object"),
        (DEEP, "too_deep"),
        (b"[" * 200_000 + b"]" * 200_000, "too_deep"),
        (b'{"": "empty key"}', "key_invalid"),
        (b'{"a": {"": "empty key below"}}', "key_invalid"),
        (b'{"' + b"k" * 121 + b'": "long key"}', "key_invalid"),
        (b'{"__proto__": {"polluted": "yes"}}', "key_invalid"),
        (b"\xff\xfe not utf-8", "not_utf8"),
        (b'{"a": "\\ud800"}', "not_utf8"),
        (b'{"_meta": "Nederlands", "a": "b"}', "meta_invalid"),
        (b'{"_meta": {"name": 3}, "a": "b"}', "meta_invalid"),
    ],
)
def test_only_texts_and_groups_of_texts(app: Any, operator: Any, folder: Path, body: bytes, reason: str) -> None:
    answer = upload(operator, app.prefix, "nl", body)
    assert answer.status_code == 422, answer.text
    code, values = app.refusal(answer)
    assert (code, values.get("reason")) == ("locale_unusable", reason)
    assert files_in(folder) == []


def test_a_refused_file_leaves_the_one_before_as_it_was(app: Any, operator: Any, reader: Any, folder: Path) -> None:
    assert upload(operator, app.prefix, "nl", b'{"a": "eerst"}').status_code == 200
    before = (folder / "nl.json").read_bytes()
    for body in (b'{"a": 1}', b"no json", b'{"a": "' + b"x" * (512 * 1024) + b'"}'):
        assert upload(operator, app.prefix, "nl", body).status_code in (413, 422)
        assert (folder / "nl.json").read_bytes() == before and files_in(folder) == ["nl.json"]
    assert reader.get(f"{app.prefix}/nl").json() == {"a": "eerst"}


def test_a_byte_order_mark_and_a_name_with_control_characters_are_fine(app: Any, operator: Any, reader: Any) -> None:
    body = "\ufeff" + json.dumps({"_meta": {"name": " Neder\nlands\u0007 "}, "a": "b"})
    answer = upload(operator, app.prefix, "nl", body.encode("utf-8"))
    assert answer.status_code == 200, answer.text
    assert answer.json()["name"] == "Nederlands"
    assert reader.get(f"{app.prefix}/nl").json() == {"a": "b"}


@pytest.mark.parametrize(
    "code",
    ["nl.json", "nl-", "nl-ABCDE", "n", "nlnl", "nl_NL", "nl%20x", "..", "nl-..", "Nl", "NL", "nl%0A", "nl%00",
     "pt-br", "zh-hant", "..%2Fetc", "%2E%2E"],
)
def test_only_a_language_code_becomes_a_file_name(app: Any, operator: Any, folder: Path, code: str) -> None:
    answer = upload(operator, app.prefix, code, b'{"a": "b"}')
    assert answer.status_code in (404, 405, 422), (code, answer.status_code)
    assert files_in(folder) == []
    if answer.status_code == 422:
        assert app.refusal(answer) == ("locale_unusable", {"reason": "code"})


@pytest.mark.parametrize("code", ["nl", "pt-BR", "zh-Hant", "fil"])
def test_valid_codes_go(app: Any, operator: Any, folder: Path, code: str) -> None:
    assert upload(operator, app.prefix, code, b'{"a": "b"}').status_code == 200
    assert files_in(folder) == [f"{code}.json"]


def test_a_broken_file_in_the_folder_gives_nothing_away(app: Any, reader: Any, folder: Path) -> None:
    """Laid into the folder by hand and broken: the list passes over it, reading says only the code, no path, no file
    name, nothing of the parser or the file."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "nl.json").write_text('{"a": 1, "secret": "x"', encoding="utf-8")
    (folder / "NOT-A-CODE.json").write_text('{"a": "b"}', encoding="utf-8")
    assert [entry["code"] for entry in reader.get(app.prefix).json()] == list(app.built_in)
    answer = reader.get(f"{app.prefix}/nl")
    assert answer.status_code == 422
    assert app.refusal(answer)[0] == "locale_unusable"
    for internal in (str(folder), folder.name, "nl.json", "secret", "Expecting", "line", "char"):
        assert internal not in answer.text, internal


def test_a_link_out_of_the_folder_is_neither_read_nor_written(app: Any, operator: Any, reader: Any, folder: Path,
                                                              tmp_path: Path) -> None:
    outside = tmp_path / "secret.json"
    outside.write_text('{"secret": "not for strangers"}', encoding="utf-8")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(outside, folder / "nl.json")
    except (OSError, NotImplementedError):
        pytest.skip("this system makes no links")
    assert [entry["code"] for entry in reader.get(app.prefix).json()] == list(app.built_in)
    answer = reader.get(f"{app.prefix}/nl")
    assert answer.status_code in (404, 422) and "not for strangers" not in answer.text
    refused = upload(operator, app.prefix, "nl", b'{"a": "b"}')
    assert refused.status_code == 422 and app.refusal(refused) == ("locale_unusable", {"reason": "not_a_file"})
    assert json.loads(outside.read_text(encoding="utf-8")) == {"secret": "not for strangers"}
    assert operator.delete(f"{app.prefix}/nl").status_code == 404 and outside.is_file()


def test_a_folder_in_place_of_a_file_is_refused_and_stays(app: Any, operator: Any, folder: Path) -> None:
    (folder / "nl.json").mkdir(parents=True)
    answer = upload(operator, app.prefix, "nl", b'{"a": "b"}')
    assert answer.status_code == 422 and app.refusal(answer)[1] == {"reason": "not_a_file"}
    assert (folder / "nl.json").is_dir() and files_in(folder) == ["nl.json"]
