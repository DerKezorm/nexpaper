"""Entry point: the FastAPI app, routers, background tasks, the built frontend."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, private
from .config import get_settings
from .db import SessionLocal, init_db
from .errors import detail
from .middleware import GuardMiddleware, RequestContextMiddleware, unhandled_error
from .routers import (
    about,
    ai,
    apikeys,
    auth,
    changes,
    devices,
    docs,
    emails,
    files,
    health,
    invites,
    oidc,
    pairing,
    passkeys,
    phone,
    public,
    push,
    resets,
    sharing,
    uploads,
    vaults,
)
from .routers import avatars as avatars_router
from .routers import backups as backups_router
from .routers import catalog as catalog_router
from .routers import documents as documents_router
from .routers import exports as exports_router
from .routers import inbox as inbox_router
from .routers import intake as intake_router
from .routers import locales as locales_router
from .routers import logs as logs_router
from .routers import ocr as ocr_router
from .routers import pagetools as pagetools_router
from .routers import paperless as paperless_router
from .routers import search as search_router
from .routers import settings as settings_router
from .routers import sorting as sorting_router
from .routers import storage as storage_router
from .routers import totp as totp_router
from .routers import v1 as v1_router
from .security import HashingBusy, purge_sessions
from .services import (
    accounts,
    backups,
    catalog,
    filecheck,
    jobs,
    locales,
    logs,
    mounts,
    notices,
    pictures,
    settings_service,
    storage,
    totp,
)
from .services import intake as intake_service
from .services import pairing as pairing_service
from .services import passkeys as passkeys_service
from .services import uploads as uploads_service

logger = logging.getLogger("nexpaper")

ROUTERS = [
    health, about, docs, locales_router, logs_router, auth, totp_router, oidc, invites, settings_router,
    backups_router, avatars_router, emails, apikeys, devices, v1_router, ai, push, passkeys, resets,
    vaults, documents_router, catalog_router, sharing, changes, public, uploads, files,
    pairing, phone, intake_router, search_router, ocr_router,
    paperless_router, exports_router,
    sorting_router,
    pagetools_router,
    storage_router,
    inbox_router,
]


def _read_log_mode() -> tuple[str, datetime | None]:
    with SessionLocal() as db:
        mode = settings_service.get(db, "log_mode")
        raw = settings_service.get(db, "log_mode_until")
    until = datetime.fromisoformat(raw).astimezone(UTC) if raw else None
    return str(mode or logs.DEFAULT_MODE), until


def _write_log_mode(mode: str, until: datetime | None) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"log_mode": mode, "log_mode_until": until.isoformat() if until else None})


async def _sweep_forever(stop: asyncio.Event) -> None:
    """Enrolments and sign-ins waiting for their second factor run out; what ran out goes from memory, ended
    sessions from the database once an hour (they stayed until someone showed them again)."""
    rounds = 0
    while not stop.is_set():
        totp.sweep()
        passkeys_service.sweep()
        if rounds % 60 == 0:
            with SessionLocal() as db:
                purge_sessions(db)
                pairing_service.sweep(db)
        rounds += 1
        try:
            await asyncio.wait_for(stop.wait(), 60)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logs.setup()
    backups.apply_pending()
    init_db()
    # A restore that could not be put in place at this start: the operators hear of it once.
    backups.report_failed_restore()
    mounts.warn_at_start(get_settings().data_dir, get_settings().database_path)
    with SessionLocal() as db:
        catalog.ensure_kinds(db)
    # Nothing is being written yet: what a broken-off write left under a temporary name goes now, and an upload that was
    # being finished when the server stopped receives again.
    storage.sweep_incoming()
    with SessionLocal() as db:
        uploads_service.recover(db)
        uploads_service.sweep(db)
    private.tighten_all()
    logs.attach_store(_read_log_mode, _write_log_mode)
    logs.apply_stored_mode()
    settings = get_settings()
    if settings.locales_dir is not None:
        settings.locales_dir.mkdir(parents=True, exist_ok=True)
    added = locales.available()
    if added:
        logger.info("Languages added by the operator: %s", ", ".join(locale.code for locale in added))
    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    settings.resolved_secret_key()
    if not settings.disable_background:
        tasks.append(asyncio.create_task(logs.run_forever(stop)))
        tasks.append(asyncio.create_task(backups.run_forever(stop)))
        tasks.append(asyncio.create_task(_sweep_forever(stop)))
        tasks.append(asyncio.create_task(jobs.run_forever(stop)))
        tasks.append(asyncio.create_task(filecheck.run_forever(stop)))
        tasks.append(asyncio.create_task(intake_service.run_forever(stop)))
    logger.info("nexpaper %s started", __version__)
    with SessionLocal() as db:
        accounts.announce_setup_code(db)
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(notices.settle, 10)
        logger.info("nexpaper stopped")


app = FastAPI(
    title="nexpaper",
    version=__version__,
    summary="The interface the web app speaks, and the one native apps and scripts use.",
    lifespan=lifespan,
    # The description is public and part of the interface (``tests/schema/openapi.json`` keeps it); the page that
    # lists it is ``routers/docs.py`` (the usual page loads its script from a CDN, which the policy of the app forbids).
    docs_url=None,
    openapi_url="/api/v1/openapi.json",
    redoc_url=None,
)
# Added last, runs first: the request id and headers wrap everything, the guard sits inside it.
app.add_middleware(GuardMiddleware)
app.add_middleware(RequestContextMiddleware)


def _bad_date_field(exc: RequestValidationError) -> str | None:
    """``date`` or ``dates[n]`` when the one thing wrong is a date of a document that is no date at all (a year past
    9999, a 30th of February); the same answer as for a date out of range, naming the same field."""
    found = exc.errors()
    if len(found) != 1 or not str(found[0].get("type", "")).startswith("date"):
        return None
    loc = tuple(part for part in found[0].get("loc", ()) if part != "body")
    if loc == ("date",):
        return "date"
    if len(loc) == 3 and loc[0] == "dates" and isinstance(loc[1], int) and loc[2] == "date":
        return f"dates[{loc[1]}]"
    return None


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.method == "PATCH" and request.url.path.startswith("/api/v1/documents/"):
        field = _bad_date_field(exc)
        if field is not None:
            return JSONResponse(
                status_code=422,
                content={"detail": detail("invalid_date", "This date is out of range.", field=field)},
            )
    fields = [".".join(str(part) for part in error.get("loc", ()) if part != "body") for error in exc.errors()]
    return JSONResponse(
        status_code=422, content={"detail": detail("invalid_input", "The input is not valid.", fields=fields)}
    )


@app.exception_handler(OverflowError)
async def _too_large_a_number(_request: Request, _exc: OverflowError) -> JSONResponse:
    # A number past what SQLite holds (an id like 99999999999999999999 in the address): not a fault of the server.
    return JSONResponse(status_code=422, content={"detail": detail("invalid_input", "The input is not valid.")})


@app.exception_handler(HashingBusy)
async def _hashing_busy(_request: Request, _exc: HashingBusy) -> JSONResponse:
    # Every slot for checking a password stayed taken for 15 s: many sign-ins at once, as in a flood of guesses.
    return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                        content={"detail": detail("busy", "The server is busy. Try again in a moment.")})


@app.exception_handler(pictures.DecodersBusy)
async def _decoders_busy(_request: Request, _exc: pictures.DecodersBusy) -> JSONResponse:
    # Every decoder stayed taken: many large photos at once. A moment later it works.
    return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                        content={"detail": detail("busy", "The server is busy. Try again in a moment.")})


@app.exception_handler(UnicodeEncodeError)
async def _not_unicode(_request: Request, _exc: UnicodeEncodeError) -> JSONResponse:
    # JSON may carry a lone surrogate ("\ud800"); no file name, path or database text can hold it.
    return JSONResponse(status_code=422, content={"detail": detail("invalid_input", "The input is not valid.")})


@app.exception_handler(StarletteHTTPException)
async def _plain_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # FastAPI's own 400 for a body that is not JSON carries only a text; give it a code like every other answer.
    if exc.status_code == 400 and isinstance(exc.detail, str):
        return JSONResponse(status_code=400, content={"detail": detail("invalid_input", "The input is not valid.")})
    return await http_exception_handler(request, exc)


app.add_exception_handler(Exception, unhandled_error)

for module in ROUTERS:
    app.include_router(module.router)


#: Files a browser asks the server about again each time: the service worker (an old one would keep its old ways for a
#: day) and the manifest.
FRESH = ("sw.js", "manifest.webmanifest")

#: The PDF frame (``frontend/pdfview.html``, the document page shows its pages with pdf.js there): a sandbox without an
#: origin of its own, scripts only from nexpaper itself (its worker from a blob), WebAssembly for pdf.js's image
#: decoders, and no network at all. The page hands it the PDF; a PDF can carry code (fonts, forms), and whatever pdf.js
#: does with it stays in here, away from the session and the API.
PDF_FRAME = "pdfview.html"
PDF_FRAME_POLICY = (
    "sandbox allow-scripts; default-src 'none'; script-src 'self' 'wasm-unsafe-eval' blob:; worker-src blob:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self' blob: data:; connect-src 'none'; "
    "frame-ancestors 'self'; base-uri 'none'; form-action 'none'; object-src 'none'"
)


class _AppFiles(StaticFiles):
    """The app's scripts and styles. They name their content and hold nothing private, so the PDF frame, which has no
    origin (``"null"``), may load them: module scripts and their styles are always fetched with CORS."""

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response


def _mount_frontend(target: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.exists():
        return
    if (dist / "assets").is_dir():
        target.mount("/assets", _AppFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()
    start_page = index.resolve()

    @target.post("/teilen", include_in_schema=False, response_model=None)
    def shared_without_worker() -> RedirectResponse:
        # Files the share menu of Android sent while the service worker was not there to catch them: such a form carries
        # the cookie and no header of nexpaper's own, so nothing of it is read or kept (``routers/phone.py``).
        return RedirectResponse("/teilen?missed=1", status_code=303)

    @target.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa(path: str) -> FileResponse | JSONResponse:
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": detail("not_found", "Not found.")})
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and root in candidate.parents and candidate != start_page:
            if path in FRESH:
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
            if path == PDF_FRAME:
                return FileResponse(candidate, media_type="text/html", headers={
                    "Content-Security-Policy": PDF_FRAME_POLICY, "X-Frame-Options": "SAMEORIGIN",
                    "Cache-Control": "no-cache"})
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


_mount_frontend(app, get_settings().frontend_dist)
