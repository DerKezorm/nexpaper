"""The description of the API for people: ``/api/v1/docs``, made from the OpenAPI description
(``/api/v1/openapi.json``).

A plain page without a script and without anything loaded from elsewhere, so that it works under the strict content
security policy of the app and does not call a CDN. The description itself is the truth; this page only lists it.
"""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import __version__

router = APIRouter(prefix="/api/v1", tags=["docs"])

STYLE = (
    "body{font:16px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#2e2720;"
    "background:#f7f3ec}h1,h2{font-weight:600}h2{margin-top:2rem;border-bottom:1px solid #e4dacb;"
    "padding-bottom:.25rem}code{font:14px ui-monospace,monospace}.row{display:flex;gap:.75rem;padding:.35rem 0;"
    "border-bottom:1px solid #efe7da}.m{min-width:4.5rem;font-weight:700;color:#9a6a3a}.p{flex:1;word-break:break-all}"
    ".s{flex:2;color:#625648}.k{font-size:.8rem;color:#7f7264}a{color:#9a6a3a}"
    "@media (prefers-color-scheme:dark){body{color:#f1e8dc;background:#171310}h2{border-color:#392f27}"
    ".row{border-color:#2a231d}.s{color:#c9baa8}.m,a{color:#d9ad7c}.k{color:#a39280}}"
)


def _rows(schema: dict[str, Any]) -> dict[str, list[tuple[str, str, str, bool]]]:
    """Per tag: (method, path, summary, needs a token) for every route, in the order of the description."""
    found: dict[str, list[tuple[str, str, str, bool]]] = {}
    for path, methods in schema.get("paths", {}).items():
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tag = (operation.get("tags") or ["other"])[0]
            found.setdefault(tag, []).append(
                (method.upper(), path, str(operation.get("summary") or ""), bool(operation.get("security")))
            )
    return found


@router.get("/docs", include_in_schema=False, response_class=HTMLResponse)
def docs(request: Request) -> HTMLResponse:
    schema = request.app.openapi()
    intro = (
        "<p>Everything the web app does goes through this interface. Browsers sign in with a session cookie; "
        "devices and programs send <code>Authorization: Bearer &lt;token&gt;</code>. "
        'The machine-readable description is <a href="/api/v1/openapi.json">openapi.json</a>. '
        "What is under <code>/api/v1</code> stays as it is: new fields may come, nothing is renamed or "
        "taken away.</p>"
    )
    body = [f"<h1>nexpaper API {escape(__version__)}</h1>", intro]
    for tag, rows in sorted(_rows(schema).items()):
        body.append(f"<h2>{escape(tag)}</h2>")
        for method, path, summary, secured in rows:
            body.append(
                f'<div class="row"><span class="m">{escape(method)}</span><code class="p">{escape(path)}</code>'
                f'<span class="s">{escape(summary)}</span>'
                f'<span class="k">{"token or session" if secured else "open"}</span></div>'
            )
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>nexpaper API</title><style>{STYLE}</style></head>'
            f"<body>{''.join(body)}</body></html>")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
