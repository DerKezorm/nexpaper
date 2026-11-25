"""The routes, for FastAPI (every nex app). Not loaded by ``nexsicherung/__init__.py``: ``from app.vendor.nexsicherung
import routes``.

``router(...)`` gives the module's own ways (the page "Speicher und Sicherung" uses only these); ``legacy_router(...)``
gives the app's old ways under its old prefix and password header, answering in the old shapes (facts and findings at
the top level), so that old clients and the app's old tests keep working. Both call the same functions. Every route is
for the operator only (the app's dependency); download, restore, delete and upload ask for the operator's password
once more (the app's ``confirm``: a stolen session alone must not carry a backup away or bring an old one back).

Module's ways under ``prefix`` (default ``/api/server/storage``):

=======  =========================================  =============================================================
GET      ``{prefix}``                               the card "Speicher" (``space.overview``)
GET      ``{prefix}/backups``                       the card "Sicherung": schedule, last, failure, the list
PUT      ``{prefix}/backups/schedule``              ``{every, time, keep}``
POST     ``{prefix}/backups``                       "Jetzt sichern" ``{note}`` → 201 ``{name, entry}``, 409 if running
POST     ``{prefix}/backups/upload``                the ZIP as body, password in the header (base64 of UTF-8) → 201
POST     ``{prefix}/backups/{name}/check``          ``{archive_password?}`` → the brief
POST     ``{prefix}/backups/{name}/download``       ``{password, archive_password?}`` → the file
POST     ``{prefix}/backups/{name}/restore``        ``{password, archive_password?}`` → 202 (restart) or 200 (now)
DELETE   ``{prefix}/backups/{name}``                ``{password}`` → 204
DELETE   ``{prefix}/backups/restore-failed``        the page saw the failed restore → 204
=======  =========================================  =============================================================
"""

import base64
import binascii
from collections.abc import Callable
from typing import Annotated, Any, get_origin

import anyio
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import archives, plan, restore, space
from .config import NOW, current
from .errors import BackupError
from .model import Entry

#: The header of the module's upload route: the body is the archive, so the password comes as base64 of its UTF-8.
PASSWORD_HEADER = "x-backup-password"
ErrorMaker = Callable[[str, str, int], Exception]


def default_error(code: str, text: str, status: int) -> Exception:
    return HTTPException(status, detail={"code": code, "message": text})


def _operator(operator: Any) -> Any:
    """The app's dependency for "operator only": an ``Annotated[..., Depends(...)]`` as the app writes it
    (``OperatorAccount``), or the dependency function itself."""
    if get_origin(operator) is Annotated:
        return operator
    return Annotated[Any, Depends(operator)]


def header_password(request: Request, header: str) -> str:
    raw = request.headers.get(header, "")
    try:
        return base64.b64decode(raw, validate=True).decode("utf-8")[:200] if raw else ""
    except (binascii.Error, UnicodeDecodeError):
        return ""


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=200)


class PasswordIn(BaseModel):
    #: The operator's password once more; an account from a provider has none and needs none (the app's ``confirm``).
    password: str = Field(default="", max_length=200)


class DownloadIn(PasswordIn):
    #: Only where the app encrypts its downloads (``AppConfig.download_password``, nexmail): the file's password.
    archive_password: str | None = Field(default=None, max_length=200)


#: The shortest password of an encrypted download (nexmail's rule before the module).
ARCHIVE_PASSWORD_MIN = 8


class CheckIn(BaseModel):
    #: Only for a locked archive (nexmail): the password the archive was encrypted with.
    archive_password: str | None = Field(default=None, max_length=200)


class RestoreIn(PasswordIn):
    archive_password: str | None = Field(default=None, max_length=200)


class ScheduleIn(BaseModel):
    every: str = Field(max_length=16)
    time: str = Field(max_length=5)
    keep: Any


def entry_view(entry: Entry) -> dict[str, Any]:
    return dict(entry.__dict__)


class _Kit:
    """What the routes share: the app's error maker, its ``confirm`` and how an account is named to the check."""

    def __init__(self, error: ErrorMaker | None, confirm: Callable[[Request, Any, str], None],
                 viewer: Callable[[Any], Any]) -> None:
        self.error = error or default_error
        self.confirm = confirm
        self.viewer = viewer

    def fail(self, exc: BackupError) -> Exception:
        return self.error(exc.code, exc.text, exc.status)

    def download(self, name: str, account: Any, archive_password: str | None = None) -> FileResponse:
        config = current()
        if config.download_password and len(archive_password or "") < ARCHIVE_PASSWORD_MIN:
            raise self.fail(BackupError("archive_password_short",
                                        "The file needs a password of at least 8 characters."))
        try:
            source = archives.path_of(name)
            given = archive_password if config.download_password else None
            path = config.hooks.download(source, archive_password=given)
        except BackupError as exc:
            raise self.fail(exc) from exc
        config.logger.warning("Backup downloaded name=%s by=%s", name, getattr(account, "name", "?"))
        media = "application/zip" if path.suffix == ".zip" else "application/octet-stream"
        # A file the app made for this download (nexmail's encrypted one) goes once it is sent.
        cleanup = BackgroundTask(path.unlink, missing_ok=True) if path != source else None
        return FileResponse(path, media_type=media, filename=path.name.lstrip("."),
                            headers={"Cache-Control": "no-store"}, background=cleanup)

    async def upload(self, request: Request, account: Any, header: str) -> str:
        await anyio.to_thread.run_sync(self.confirm, request, account, header_password(request, header))
        limit = current().upload_max
        received = archives.temporary_upload()
        size = 0
        try:
            async with await anyio.open_file(received, "wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise self.fail(BackupError("backup_too_large", "The file is larger than allowed."))
                    await handle.write(chunk)
            if not size:
                raise self.fail(BackupError("empty", "The file is empty."))
            try:
                name = await anyio.to_thread.run_sync(archives.receive, received)
            except BackupError as exc:
                raise self.fail(exc) from exc
        finally:
            received.unlink(missing_ok=True)
        current().logger.warning("Backup uploaded name=%s by=%s bytes=%s", name, getattr(account, "name", "?"), size)
        return name

    def restore(self, name: str, body: RestoreIn, request: Request, account: Any) -> tuple[Any, dict[str, Any], bool]:
        self.confirm(request, account, body.password)
        try:
            if current().restore == NOW:
                brief, result = restore.restore_now(name, viewer=self.viewer(account),
                                                    archive_password=body.archive_password)
                return brief, result, False
            brief = restore.stage_restore(name, viewer=self.viewer(account), archive_password=body.archive_password)
        except BackupError as exc:
            raise self.fail(exc) from exc
        restore.restart_soon()
        return brief, {}, True


def router(*, operator: Any, confirm: Callable[[Request, Any, str], None], prefix: str = "/api/server/storage",
           error: ErrorMaker | None = None, viewer: Callable[[Any], Any] = lambda account: getattr(account, "id", None),
           password_header: str = PASSWORD_HEADER, tags: list[str] | None = None) -> APIRouter:
    """The module's own routes. ``operator``: the app's operator-only dependency. ``confirm(request, account,
    password)``: the app's check of the operator's password (raises its own error when wrong; an account from a
    provider passes on a fresh sign-in). ``error(code, text, status)``: the app's error maker (default: HTTPException
    with ``{"code", "message"}``)."""
    kit = _Kit(error, confirm, viewer)
    Operator = _operator(operator)
    api = APIRouter(prefix=prefix, tags=tags or ["storage"])

    @api.get("", summary="What the app takes on the disk, how full it is, network shares (operator)")
    def storage(_account: Operator) -> dict[str, Any]:
        return space.overview()

    @api.get("/backups", summary="The schedule, the last backup, a failure, and the list (operator)")
    def backups(_account: Operator) -> dict[str, Any]:
        return {**plan.summary(), "backups": [entry_view(entry) for entry in archives.entries()]}

    @api.put("/backups/schedule", summary="Automatic backups: off, daily, weekly, monthly; the time; how many")
    def schedule(body: ScheduleIn, _account: Operator) -> dict[str, Any]:
        try:
            saved = plan.save(plan.checked(body.every, body.time, body.keep))
        except BackupError as exc:
            raise kit.fail(exc) from exc
        return {"every": saved.every, "time": saved.time, "keep": saved.keep}

    @api.post("/backups", status_code=201, summary="Make a backup now")
    def make(account: Operator, body: NoteIn = Body(default_factory=NoteIn)) -> dict[str, Any]:  # noqa: B008
        try:
            path = archives.create(note=body.note, wait=False)
        except BackupError as exc:
            raise kit.fail(exc) from exc
        found = next((entry for entry in archives.entries() if entry.name == path.name), None)
        return {"name": path.name, "entry": entry_view(found) if found else None}

    @api.delete("/backups/restore-failed", status_code=204, summary="The failed restore was seen")
    def dismiss(_account: Operator) -> None:
        restore.forget_failed()

    @api.post("/backups/upload", status_code=201, summary="Bring in a backup from elsewhere (the body is the "
              "archive); needs the password again, in the header")
    async def upload(request: Request, account: Operator) -> dict[str, str]:
        return {"name": await kit.upload(request, account, password_header)}

    @api.post("/backups/{name}/check", summary="The trial run: whole or not, what a restore would change")
    def check(name: str, account: Operator, body: CheckIn = Body(default_factory=CheckIn)) -> dict[str, Any]:  # noqa: B008
        try:
            return restore.check(name, viewer=kit.viewer(account), archive_password=body.archive_password).view()
        except BackupError as exc:
            raise kit.fail(exc) from exc

    @api.post("/backups/{name}/download", summary="The archive itself; needs the password again")
    def download(name: str, body: DownloadIn, request: Request, account: Operator) -> FileResponse:
        kit.confirm(request, account, body.password)
        return kit.download(name, account, body.archive_password)

    @api.post("/backups/{name}/restore", summary="Keep the current state, then restore; needs the password again")
    def restore_route(name: str, body: RestoreIn, request: Request, account: Operator) -> Any:
        brief, result, restarting = kit.restore(name, body, request, account)
        from fastapi.responses import JSONResponse

        return JSONResponse({**brief.view(), "result": result, "restarting": restarting},
                            status_code=202 if restarting else 200)

    @api.delete("/backups/{name}", status_code=204, summary="Delete a backup; needs the password again")
    def delete(name: str, body: PasswordIn, request: Request, account: Operator) -> None:
        kit.confirm(request, account, body.password)
        try:
            archives.remove(name)
        except BackupError as exc:
            raise kit.fail(exc) from exc

    return api


def legacy_router(*, prefix: str, password_header: str, operator: Any, confirm: Callable[[Request, Any, str], None],
                  error: ErrorMaker | None = None,
                  viewer: Callable[[Any], Any] = lambda account: getattr(account, "id", None),
                  check_raises_too_new: bool = False, tags: list[str] | None = None) -> APIRouter:
    """The app's old ways (``/api/backups``, nexpaper ``/api/v1/backups``) with its old password header
    (``x-<app>-password``), in the old shapes: the list as an array of flat entries, ``{name}`` after making or
    bringing in, the check flat with ``usable``, the restore 202 with ``restarting``. ``check_raises_too_new``: the
    app's old check refused an archive of a newer version with 400 ``backup_too_new`` (nexnotes, nextime, nexfolk)
    instead of answering it."""
    kit = _Kit(error, confirm, viewer)
    Operator = _operator(operator)
    api = APIRouter(prefix=prefix, tags=tags or ["backups"])

    @api.get("")
    def listing(_account: Operator) -> list[dict[str, Any]]:
        return [entry.flat() for entry in archives.entries() if entry.readable]

    @api.post("", status_code=201)
    def create(_account: Operator, body: NoteIn = Body(default_factory=NoteIn)) -> dict[str, str]:  # noqa: B008
        try:
            return {"name": archives.create(note=body.note, wait=False).name}
        except BackupError as exc:
            raise kit.fail(exc) from exc

    @api.post("/upload", status_code=201)
    async def upload(request: Request, account: Operator) -> dict[str, str]:
        return {"name": await kit.upload(request, account, password_header)}

    @api.post("/{name}/check")
    def check(name: str, account: Operator) -> dict[str, Any]:
        try:
            brief = restore.check(name, viewer=kit.viewer(account))
        except BackupError as exc:
            raise kit.fail(exc) from exc
        if check_raises_too_new and brief.too_new:
            raise kit.fail(BackupError("backup_too_new", f"the archive comes from version {brief.version}, newer "
                                                         "than this one"))
        return brief.flat()

    @api.post("/{name}/restore", status_code=202)
    def restore_route(name: str, body: RestoreIn, request: Request, account: Operator) -> Any:
        brief, result, restarting = kit.restore(name, body, request, account)
        from fastapi.responses import JSONResponse

        return JSONResponse({**brief.flat(), **result, "restarting": restarting},
                            status_code=202 if restarting else 200)

    @api.post("/{name}/download")
    def download(name: str, body: DownloadIn, request: Request, account: Operator) -> FileResponse:
        kit.confirm(request, account, body.password)
        return kit.download(name, account, body.archive_password)

    @api.delete("/{name}", status_code=204)
    def delete(name: str, body: PasswordIn, request: Request, account: Operator) -> None:
        kit.confirm(request, account, body.password)
        try:
            archives.remove(name)
        except BackupError as exc:
            raise kit.fail(exc) from exc

    return api
