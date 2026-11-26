"""The operator's own language files: what is offered, what is refused, and that nothing leaves the directory.

Since the shared module sprachen 1.0.0 (E51) the routes are the module's, at the same address ``/api/v1/locales``. The
list names the built-in languages too (``built_in``, ``own``); ``added`` reads it as every caller of before did (the
old page and menus skipped the built-in codes), and ``test_old_callers_get_the_same_answers`` shows the ways of before
answer as they did. The module's own contract tests are ``tests/nexsprachen``."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import locales

GOOD = {"_meta": {"name": "Español"}, "nav": {"graph": "Grafo", "search": "Buscar"}, "save": "Guardar"}


@pytest.fixture
def folder() -> Iterator[Path]:
    directory = locales.locales_dir()
    directory.mkdir(parents=True, exist_ok=True)
    assert Path(os.environ["NEXPAPER_LOCALES_DIR"]) == directory, "never empty a directory that is not the test's own"
    for old in directory.iterdir():
        old.unlink()
    locales.forget()
    yield directory
    for old in directory.iterdir():
        old.unlink()


def added(client: TestClient) -> list[dict[str, object]]:
    """The list as a caller of before read it: the operator's files, each with ``code``, ``name``, ``keys``."""
    return [{key: entry[key] for key in ("code", "name", "keys")}
            for entry in client.get("/api/v1/locales").json() if not entry["built_in"]]


def put(folder: Path, name: str, content: object | bytes) -> Path:
    path = folder / name
    raw = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return path


def test_a_good_file_is_listed_and_served_without_its_meta(client: TestClient, folder: Path) -> None:
    put(folder, "es.json", GOOD)
    assert added(client) == [{"code": "es", "name": "Español", "keys": 3}]
    texts = client.get("/api/v1/locales/es").json()
    assert texts == {"nav": {"graph": "Grafo", "search": "Buscar"}, "save": "Guardar"}


def test_regions_and_scripts_are_codes_too_and_the_name_falls_back_to_the_code(client: TestClient, folder: Path) -> None:
    put(folder, "pt-BR.json", {"save": "Salvar"})
    put(folder, "zh-Hant.json", {"save": "儲存"})
    listed = {entry["code"]: entry["name"] for entry in added(client)}
    assert listed == {"pt-BR": "pt-BR", "zh-Hant": "zh-Hant"}
    assert client.get("/api/v1/locales/zh-Hant").json() == {"save": "儲存"}


def test_a_byte_order_mark_is_fine(client: TestClient, folder: Path) -> None:
    put(folder, "fr.json", b"\xef\xbb\xbf" + json.dumps({"save": "Enregistrer"}).encode("utf-8"))
    assert client.get("/api/v1/locales/fr").json() == {"save": "Enregistrer"}


@pytest.mark.parametrize(
    ("content", "why"),
    [
        (b"{not json", "not valid JSON"),
        (b"\xff\xfe\x00broken", "not UTF-8"),
        (json.dumps(["a", "b"]).encode(), "top level"),
        (json.dumps({"save": 5}).encode(), "only texts and groups of texts"),
        (json.dumps({"save": None}).encode(), "only texts and groups of texts"),
        (json.dumps({"save": ["a"]}).encode(), "only texts and groups of texts"),
        (json.dumps({}).encode(), "no texts"),
        (json.dumps({"_meta": {"name": 3}, "a": "b"}).encode(), "_meta"),
        (json.dumps({"": "empty key"}).encode(), "a key is empty"),
    ],
)
def test_a_broken_file_is_skipped_and_named_in_the_log_but_the_others_stay(
    client: TestClient, folder: Path, content: bytes, why: str, caplog: pytest.LogCaptureFixture
) -> None:
    put(folder, "es.json", GOOD)
    put(folder, "it.json", content)
    with caplog.at_level("WARNING", logger="nexpaper.locales"):
        assert [entry["code"] for entry in added(client)] == ["es"]
    assert any("it.json skipped" in record.getMessage() and why in record.getMessage() for record in caplog.records)
    refused = client.get("/api/v1/locales/it")
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "locale_unusable"


def test_too_deep_and_too_large_are_refused(client: TestClient, folder: Path) -> None:
    deep: dict = {"a": "b"}
    for _ in range(locales.MAX_DEPTH + 1):
        deep = {"x": deep}
    put(folder, "nl.json", deep)
    put(folder, "sv.json", b'{"a": "' + b"x" * (locales.MAX_BYTES + 1) + b'"}')
    assert added(client) == []
    assert client.get("/api/v1/locales/nl").status_code == 422
    assert client.get("/api/v1/locales/sv").status_code == 422


def test_just_under_the_limits_is_accepted(client: TestClient, folder: Path) -> None:
    deep: dict = {"a": "b"}
    for _ in range(locales.MAX_DEPTH - 2):
        deep = {"x": deep}
    put(folder, "nl.json", deep)
    padding = locales.MAX_BYTES - len(b'{"a": ""}')
    put(folder, "sv.json", b'{"a": "' + b"x" * padding + b'"}')
    assert [entry["code"] for entry in added(client)] == ["nl", "sv"]


@pytest.mark.parametrize(
    "code",
    ["../secret", "..%2Fsecret", "%2e%2e", "es.json", "ES", "e", "english", "es-", "es-b", "es_ES", "es-ES-x", " es"],
)
def test_only_language_codes_are_asked_for(client: TestClient, folder: Path, code: str) -> None:
    put(folder, "es.json", GOOD)
    assert client.get(f"/api/v1/locales/{code}").status_code == 404


def test_nothing_outside_the_directory_is_read(client: TestClient, folder: Path) -> None:
    outside = folder.parent / "de.json"
    outside.write_bytes(json.dumps({"secret": "outside"}).encode())
    try:
        assert client.get("/api/v1/locales/de").status_code == 404
        assert "outside" not in client.get("/api/v1/locales/..%2Fde").text
    finally:
        outside.unlink()


def test_a_link_is_not_followed(client: TestClient, folder: Path) -> None:
    outside = folder.parent / "target.json"
    outside.write_bytes(json.dumps({"secret": "outside"}).encode())
    try:
        try:
            os.symlink(outside, folder / "es.json")
        except (OSError, NotImplementedError):
            pytest.skip("this system does not allow links for this user (Windows without developer mode)")
        assert added(client) == []
        assert "outside" not in client.get("/api/v1/locales/es").text
    finally:
        (folder / "es.json").unlink(missing_ok=True)
        outside.unlink()


def test_other_files_in_the_directory_are_ignored(client: TestClient, folder: Path) -> None:
    put(folder, "es.json", GOOD)
    put(folder, "notes.txt", b"hello")
    put(folder, "README.md", b"# languages")
    assert [entry["code"] for entry in added(client)] == ["es"]


def test_no_directory_means_no_extra_languages(client: TestClient, folder: Path) -> None:
    folder.rmdir()
    try:
        assert added(client) == []
        assert client.get("/api/v1/locales/es").status_code == 404
    finally:
        folder.mkdir()


def test_a_broken_file_is_warned_about_once_not_on_every_page_load(
    client: TestClient, folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    put(folder, "it.json", b"{broken")
    with caplog.at_level("WARNING", logger="nexpaper.locales"):
        for _ in range(5):
            assert added(client) == []
    assert sum("it.json skipped" in record.getMessage() for record in caplog.records) == 1


def test_a_repaired_file_shows_up_and_a_removed_one_goes(client: TestClient, folder: Path) -> None:
    path = put(folder, "it.json", b"{broken")
    assert added(client) == []
    put(folder, "it.json", {"_meta": {"name": "Italiano"}, "save": "Salva"})
    assert added(client) == [{"code": "it", "name": "Italiano", "keys": 1}]
    path.unlink()
    assert added(client) == []


def test_the_operator_uploads_and_removes_a_language(client: TestClient, folder: Path) -> None:
    from .conftest import make_account, sign_in

    body = json.dumps(GOOD, ensure_ascii=False).encode("utf-8")
    assert client.put("/api/v1/locales/es", content=body).status_code == 401
    sign_in(client, make_account("member"))
    assert client.put("/api/v1/locales/es", content=body).status_code == 403
    sign_in(client, make_account("boss", "operator"))
    saved = client.put("/api/v1/locales/es", content=body)
    assert saved.status_code == 200 and saved.json() == {"code": "es", "name": "Español", "keys": 3}
    assert client.get("/api/v1/locales/es").json()["save"] == "Guardar"
    assert [entry["code"] for entry in added(client)] == ["es"]
    # Checked like a file laid into the directory: nothing broken gets in, and nothing lands outside.
    for code, raw in (("fr", b"{not json"), ("fr", b'{"a": 1}'), ("../x", body), ("es.json", body)):
        refused = client.put(f"/api/v1/locales/{code}", content=raw)
        assert refused.status_code in (404, 422), code
    assert client.put("/api/v1/locales/fr", content=b" " * (locales.MAX_BYTES + 1)).status_code == 413
    assert sorted(path.name for path in folder.iterdir()) == ["es.json"]
    assert client.delete("/api/v1/locales/es").status_code == 204
    assert client.delete("/api/v1/locales/es").status_code == 404
    assert added(client) == []


def test_a_file_too_large_is_refused_before_it_is_read(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    put(folder, "es.json", b" " * (locales.MAX_BYTES + 1))

    def never(self: Path) -> bytes:
        raise AssertionError(f"{self.name} was read whole")

    monkeypatch.setattr(Path, "read_bytes", never)
    assert locales.available() == []


def test_old_callers_get_the_same_answers(client: TestClient, folder: Path) -> None:
    """The ways of before, as the page of before and a script used them: the list keeps ``code``, ``name``, ``keys``
    for every file (the built-in languages come first, marked, with no file: ``own`` false, ``keys`` 0; a file over
    French marks French as ``own``), the texts, saving with ``{code, name, keys}``, removing with 204, and the refusals
    with their codes of before in nexpaper's form."""
    from .conftest import make_account, sign_in

    put(folder, "es.json", GOOD)
    put(folder, "fr.json", {"save": "Enregistrer"})
    listed = client.get("/api/v1/locales").json()
    assert [(entry["code"], entry["built_in"], entry["own"], entry["keys"]) for entry in listed] == [
        ("de", True, False, 0), ("en", True, False, 0), ("fr", True, True, 1), ("es", False, True, 3)]
    assert all({"code", "name", "keys"} <= set(entry) for entry in listed)
    assert client.get("/api/v1/locales/es").json() == {"nav": {"graph": "Grafo", "search": "Buscar"}, "save": "Guardar"}
    assert client.get("/api/v1/locales/fr").json() == {"save": "Enregistrer"}
    missing = client.get("/api/v1/locales/it")
    assert missing.status_code == 404 and missing.json()["detail"] == {"code": "not_found", "message": "Not found."}
    sign_in(client, make_account("boss", "operator"))
    saved = client.put("/api/v1/locales/it", content=json.dumps({"save": "Salva"}).encode())
    assert saved.status_code == 200 and saved.json() == {"code": "it", "name": "it", "keys": 1}
    refused = client.put("/api/v1/locales/nl", content=b"{not json")
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "locale_unusable"
    large = client.put("/api/v1/locales/nl", content=b" " * (locales.MAX_BYTES + 1))
    assert large.status_code == 413 and large.json()["detail"]["code"] == "too_large"
    assert large.json()["detail"]["max_mb"] == 0.5
    assert client.delete("/api/v1/locales/it").status_code == 204
    gone = client.delete("/api/v1/locales/it")
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "not_found"


def test_the_profile_takes_a_built_in_or_an_added_language_only(client: TestClient, folder: Path) -> None:
    """``PUT /api/v1/me/language`` checks with ``nexsprachen.known``: French and an added file go, a code without a
    file is refused as before (``unknown_language``)."""
    from .conftest import make_account, sign_in

    sign_in(client, make_account("reader"))
    assert client.put("/api/v1/me/language", json={"language": "fr"}).status_code == 200
    refused = client.put("/api/v1/me/language", json={"language": "it"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "unknown_language"
    put(folder, "it.json", {"save": "Salva"})
    assert client.put("/api/v1/me/language", json={"language": "it"}).json()["language"] == "it"
