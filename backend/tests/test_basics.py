"""Health, about, the security headers, the error shape, and the built frontend with its path guard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import __version__
from app.main import _mount_frontend


def test_health_and_about(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok", "version": __version__}
    about = client.get("/api/v1/about").json()
    assert about["version"] == __version__ and about["license"] == "AGPL-3.0"


def test_every_answer_carries_the_security_headers(client: TestClient) -> None:
    for response in (client.get("/api/v1/health"), client.get("/api/v1/nothing-here")):
        headers = response.headers
        csp = headers["content-security-policy"]
        assert "script-src" not in csp or "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "same-origin"


def test_invalid_input_names_the_field_with_a_code(client: TestClient, operator: str) -> None:
    response = client.put("/api/v1/logs/level", json={"mode": "loud"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_input"
    assert response.json()["detail"]["fields"] == ["mode"]


def test_api_docs_are_off_by_default(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def _built(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_bytes(b"<!doctype html><title>nexpaper</title>")
    (dist / "assets" / "app.js").write_bytes(b"console.log(1)")
    (dist / "favicon.svg").write_bytes(b"<svg/>")
    (tmp_path / "secret.txt").write_bytes(b"outside")
    app = FastAPI()
    _mount_frontend(app, dist)
    return TestClient(app)


def test_the_frontend_serves_files_and_falls_back_to_the_start_page(tmp_path: Path) -> None:
    client = _built(tmp_path)
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    start = client.get("/notes/some/deep/link")
    assert "<title>nexpaper</title>" in start.text and start.headers["cache-control"] == "no-cache"


def test_the_frontend_never_serves_outside_its_directory(tmp_path: Path) -> None:
    client = _built(tmp_path)
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/..%2fsecret.txt"):
        assert "outside" not in client.get(path).text, path


def test_unknown_api_paths_are_404_not_the_start_page(tmp_path: Path) -> None:
    client = _built(tmp_path)
    for path in ("/api", "/api/", "/api/v1/nothing"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["detail"]["code"] == "not_found"


def test_a_cookie_suffix_keeps_two_instances_on_one_host_apart(monkeypatch) -> None:
    from app.config import Settings

    assert Settings(cookie_suffix="_second").cookie_name_suffix() == "_second"
    assert Settings(cookie_suffix="a;b=c d").cookie_name_suffix() == "abcd"
    assert Settings().cookie_name_suffix() == ""


def test_the_image_starts_uvicorn_without_its_server_header() -> None:
    """Every way the container starts the server leaves out "server: uvicorn": the command, and the entrypoint when
    somebody changed the command."""
    root = Path(__file__).resolve().parents[2]
    command = next(line for line in (root / "Dockerfile").read_text(encoding="utf-8").splitlines() if line.startswith("CMD"))
    assert '"--no-server-header"' in command
    entrypoint = (root / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "set -- \"$@\" --no-server-header" in entrypoint


def test_build_output_and_data_never_go_into_a_commit() -> None:
    """What `git add -A` would take: never the environments, the built frontend, its build cache or any data."""
    import os
    import shutil
    import subprocess
    import time

    import pytest

    root = Path(__file__).resolve().parents[2]
    if shutil.which("git") is None or not (root / ".git").exists():
        if os.environ.get("CI"):
            pytest.fail("CI without a git checkout")
        pytest.skip("no git checkout here")
    # Another git command in the same tree (a commit in another window, an index being written) can make one listing
    # fail for a moment: asked again, a few times, before the test calls it a failure.
    for attempt in range(4):
        done = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root,
                              capture_output=True, text=True, check=False, timeout=60)
        if done.returncode == 0:
            break
        time.sleep(0.5 * (attempt + 1))
    assert done.returncode == 0, done.stderr[-500:]
    listed = done.stdout.splitlines()
    assert len(listed) > 50, "the listing went wrong"
    forbidden = ("node_modules/", ".venv/", "/dist/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", "/data/")
    bad = [path for path in listed if any(part in "/" + path for part in forbidden)
           or path.endswith((".tsbuildinfo", ".pyc", ".db", ".db-wal", "secret.key"))]
    assert bad == []


def test_the_entrypoint_does_as_root_only_what_the_compose_file_allows() -> None:
    """The compose file drops every capability but CHOWN, DAC_READ_SEARCH, SETUID and SETGID. Root then may not
    delete a file of the user nexpaper: the write test is made and removed by that user, never by root (found on
    the first start of the image, which stopped with "Permission denied")."""
    root = Path(__file__).resolve().parents[2]
    entrypoint = (root / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "touch /data/.write-test && rm -f /data/.write-test" in entrypoint
    as_root = [line.strip() for line in entrypoint.splitlines() if line.strip().startswith(("rm ", "rm -"))]
    assert as_root == [], "root removes nothing in /data"
    for capability in ("CHOWN", "DAC_READ_SEARCH", "SETUID", "SETGID"):
        assert f"- {capability}" in compose
