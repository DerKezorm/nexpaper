"""The app on the home screen: the manifest with its name and colours, its shortcuts and the share target of Android,
the service worker for Web Push and for files shared from other apps (it answers that one form and keeps nothing else),
and a Content Security Policy that lets it register in the built app, where it counts."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.middleware import CSP
from app.services import locales
from app.services import manifest as manifest_service

PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public"


def test_the_policy_lets_the_service_worker_and_the_manifest_in(client: TestClient) -> None:
    policy = client.get("/api/v1/health").headers["content-security-policy"]
    assert "worker-src 'self'" in policy and "manifest-src 'self'" in policy
    assert "worker-src 'none'" not in policy and "'unsafe-eval'" not in policy
    assert policy.encode() == CSP


def test_the_manifest_names_the_app_its_shortcuts_and_the_share_target() -> None:
    """As the mock: shortcuts to the quick upload and the camera, and the share target (POST with files) at /teilen,
    which the service worker answers."""
    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "nexpaper" and manifest["short_name"] == "nexpaper"
    assert manifest["start_url"] == "/" and manifest["display"] == "standalone"
    assert manifest["background_color"] == manifest["theme_color"] == "#f7f3ec"
    assert manifest["icons"][0]["src"] == "/logo.svg"
    # The file speaks English; the server names the shortcuts in the browser's language (below).
    assert [(item["name"], item["url"]) for item in manifest["shortcuts"]] == [
        ("Upload", "/schnell"), ("Take a photo", "/kamera")]
    target = manifest["share_target"]
    assert (target["action"], target["method"], target["enctype"]) == ("/teilen", "POST", "multipart/form-data")
    assert target["params"]["files"][0]["name"] == "files"
    assert "application/pdf" in target["params"]["files"][0]["accept"]


def test_the_service_worker_serves_push_and_the_shared_files_only() -> None:
    worker = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in worker.splitlines() if not line.lstrip().startswith("//"))
    assert "addEventListener('push'" in code and "addEventListener('notificationclick'" in code
    # The fetch handler answers the form to /teilen of this site and nothing else; it makes no request of its own and
    # keeps nothing but the shared files (src/sw.test.ts runs it).
    assert code.count("respondWith") == 1 and "url.pathname !== '/teilen'" in code and "request.method !== 'POST'" in code
    assert "url.origin !== self.location.origin" in code
    for never in ("fetch(", "importScripts", "caches.match"):
        assert never not in code, never
    # A tap opens a path of nexpaper, never another site.
    assert "startsWith('//')" in code


def test_the_built_app_serves_the_worker_and_the_manifest_fresh(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>nexpaper</title>", encoding="utf-8")
    (dist / "sw.js").write_text((PUBLIC / "sw.js").read_text(encoding="utf-8"), encoding="utf-8")
    (dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    (dist / "logo.svg").write_text("<svg/>", encoding="utf-8")
    built = FastAPI()
    main._mount_frontend(built, dist)
    with TestClient(built) as browser:
        worker = browser.get("/sw.js")
        assert worker.status_code == 200 and "javascript" in worker.headers["content-type"]
        assert worker.headers["cache-control"] == "no-cache"
        assert browser.get("/manifest.webmanifest").headers["cache-control"] == "no-cache"
        assert "cache-control" not in browser.get("/logo.svg").headers


def test_phones_get_png_symbols_and_notifications_a_png_icon_and_a_badge() -> None:
    """Review of B6: iPhone and Android want PNG for the home screen, a maskable one, and notifications draw no SVG."""
    import struct

    def size_of(name: str) -> tuple[int, int]:
        data = (PUBLIC / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
        return struct.unpack(">II", data[16:24])

    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    pngs = {icon["src"]: icon for icon in manifest["icons"] if icon["type"] == "image/png"}
    assert {(src, icon["sizes"], icon["purpose"]) for src, icon in pngs.items()} == {
        ("/icon-192.png", "192x192", "any"), ("/icon-512.png", "512x512", "any"),
        ("/icon-maskable-512.png", "512x512", "maskable")}
    for src, icon in pngs.items():
        width, height = size_of(src.lstrip("/"))
        assert f"{width}x{height}" == icon["sizes"], src
    assert size_of("apple-touch-icon.png") == (180, 180) and size_of("badge-96.png") == (96, 96)
    index = (PUBLIC.parent / "index.html").read_text(encoding="utf-8")
    assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png" />' in index
    worker = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    assert "icon: '/icon-192.png'" in worker and "badge: '/badge-96.png'" in worker


# --- The manifest in the language of the browser (#job-215) ------------------------------------------------------------

I18N = PUBLIC.parent / "src" / "i18n"


@pytest.fixture
def home_screen(tmp_path: Path) -> Iterator[TestClient]:
    """The built app with the real manifest, and an empty folder of the operator's languages."""
    folder = locales.locales_dir()
    folder.mkdir(parents=True, exist_ok=True)
    assert Path(os.environ["NEXPAPER_LOCALES_DIR"]) == folder, "never empty a directory that is not the test's own"
    for old in folder.iterdir():
        old.unlink()
    locales.forget()
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>nexpaper</title>", encoding="utf-8")
    (dist / "manifest.webmanifest").write_bytes((PUBLIC / "manifest.webmanifest").read_bytes())
    built = FastAPI()
    main._mount_frontend(built, dist)
    with TestClient(built) as browser:
        yield browser
    for old in folder.iterdir():
        old.unlink()
    locales.forget()


def shortcuts(browser: TestClient, accept: str | None) -> tuple[str, list[tuple[str, str]], dict]:
    answer = browser.get("/manifest.webmanifest", headers={"Accept-Language": accept} if accept is not None else {})
    assert answer.status_code == 200
    manifest = answer.json()
    return manifest["lang"], [(item["name"], item["short_name"]) for item in manifest["shortcuts"]], manifest


def test_the_manifest_names_the_shortcuts_in_the_language_of_the_browser(home_screen: TestClient) -> None:
    base = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    german = ("de", [("Hochladen", "Hochladen"), ("Fotografieren", "Kamera")])
    english = ("en", [("Upload", "Upload"), ("Take a photo", "Camera")])
    for accept, wanted in (
        ("de-DE,de;q=0.9,en;q=0.8", german),
        ("de", german),
        ("en-US,en;q=0.9,de;q=0.8", english),
        # The weight counts, not only the order; a language nexpaper does not have is passed over.
        ("en;q=0.2, fr;q=1, de;q=0.7", german),
        ("fr-FR, fr;q=0.9", english),
        ("", english),
        (None, english),
        ("*", english),
        ("de;q=0", english),
    ):
        language, names, manifest = shortcuts(home_screen, accept)
        assert (language, names) == wanted, accept
        # Everything else is the file as it was built: the icons, the share target, the addresses.
        assert {k: v for k, v in manifest.items() if k not in ("lang", "description", "shortcuts")} == {
            k: v for k, v in base.items() if k not in ("description", "shortcuts")}
        assert [item["url"] for item in manifest["shortcuts"]] == ["/schnell", "/kamera"]
    assert shortcuts(home_screen, "de")[2]["description"].startswith("Eine leichte Ablage")
    answer = home_screen.get("/manifest.webmanifest", headers={"Accept-Language": "de"})
    assert answer.headers["content-type"] == "application/manifest+json"
    assert answer.headers["cache-control"] == "no-cache" and answer.headers["vary"] == "Accept-Language"
    assert answer.headers["content-language"] == "de"


def test_a_language_the_operator_added_names_the_shortcuts_too(home_screen: TestClient) -> None:
    folder = locales.locales_dir()
    (folder / "es.json").write_text(json.dumps({
        "_meta": {"name": "Español"}, "save": "Guardar",
        # "uploadShort" left out: English; a name far too long is no name.
        "manifest": {"upload": "Subir", "camera": "Hacer una foto", "cameraShort": "x" * 500},
    }), encoding="utf-8")
    (folder / "de.json").write_text(json.dumps({"manifest": {"camera": "Knipsen"}}), encoding="utf-8")
    (folder / "nl.json").write_text("{ broken", encoding="utf-8")
    locales.forget()
    assert shortcuts(home_screen, "es-ES,es;q=0.9")[:2] == ("es", [("Subir", "Upload"), ("Hacer una foto", "Camera")])
    # A file for a shipped language lays itself over the shipped words.
    assert shortcuts(home_screen, "de")[:2] == ("de", [("Hochladen", "Hochladen"), ("Knipsen", "Kamera")])
    # A broken file is no language nexpaper has.
    assert shortcuts(home_screen, "nl")[:2] == ("en", [("Upload", "Upload"), ("Take a photo", "Camera")])


def test_the_words_of_the_server_are_those_of_the_interface() -> None:
    """The template of a new language is the interface's en.json: its ``manifest`` section is what a translator sees."""
    for language, words in manifest_service.SHIPPED.items():
        shipped = json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))["manifest"]
        assert shipped == words, language
        assert set(words) == set(manifest_service.KEYS)
