"""The frame the document page shows a PDF in (pdf.js): a sandbox of its own without network, framed only by nexpaper,
and the app's scripts readable for it (it has no origin, so it fetches them with CORS)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.middleware import CSP, RequestContextMiddleware


def built_app(tmp_path: Path) -> FastAPI:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>nexpaper</title>", encoding="utf-8")
    (dist / "pdfview.html").write_text("<!doctype html><title>PDF</title>", encoding="utf-8")
    (dist / "assets" / "pdfview-1234.js").write_text("export {}", encoding="utf-8")
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    main._mount_frontend(app, dist)
    return app


def test_the_frame_has_a_policy_of_its_own_a_sandbox_without_network(tmp_path: Path) -> None:
    with TestClient(built_app(tmp_path)) as browser:
        frame = browser.get("/pdfview.html")
        assert frame.status_code == 200 and frame.headers["content-type"].startswith("text/html")
        policies = frame.headers.get_list("content-security-policy")
        assert policies == [main.PDF_FRAME_POLICY], "the app's policy is not added on top"
        policy = policies[0]
        assert policy.startswith("sandbox allow-scripts;") and "allow-same-origin" not in policy
        assert "connect-src 'none'" in policy and "default-src 'none'" in policy
        assert "frame-ancestors 'self'" in policy and "'unsafe-eval'" not in policy
        assert frame.headers["x-frame-options"] == "SAMEORIGIN"
        assert frame.headers["cache-control"] == "no-cache"


def test_the_app_itself_keeps_its_strict_policy_and_may_not_be_framed(tmp_path: Path) -> None:
    with TestClient(built_app(tmp_path)) as browser:
        page = browser.get("/dokument/7")
        assert page.headers.get_list("content-security-policy") == [CSP.decode()]
        assert "frame-ancestors 'none'" in CSP.decode()
        assert page.headers["x-frame-options"] == "DENY"


def test_the_scripts_of_the_app_may_be_read_by_the_frame(tmp_path: Path) -> None:
    with TestClient(built_app(tmp_path)) as browser:
        script = browser.get("/assets/pdfview-1234.js", headers={"Origin": "null"})
        assert script.status_code == 200 and script.headers["access-control-allow-origin"] == "*"
        # Nothing else is opened to other sites: the API answers without it.
        assert "access-control-allow-origin" not in browser.get("/dokument/7").headers
