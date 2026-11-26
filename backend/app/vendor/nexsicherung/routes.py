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

Names in the description of the interface (E53, ``/openapi.json``): both routers take ``operation_ids`` and
``summaries`` (by the name of a route, ``ROUTES`` and ``LEGACY_ROUTES``) and ``schema_names`` (by the module's name of
a schema, ``SCHEMAS``; a value is a name or a dotted place and name like ``app.routers.backups.PasswordIn``, which
FastAPI writes ``app__routers__backups__PasswordIn`` where two classes share the name). Schemas given one name become
one schema with the fields of all (the restore's ``archive_password`` and ``options`` beside the password; not
required). An app gives the same ``schema_names`` to both routers. ``FORMER_SCHEMAS`` and ``former_names(prefix)`` are
the names an app's own backup routes had before the module (the same in every app that had them). Without them the
module's names stay (for an app that took the module before it kept the old names).
"""

import base64
import binascii
import re
from collections.abc import Callable
from typing import Annotated, Any, get_origin

import anyio
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, create_model
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
    #: Since E38: the answers to the app's questions in the dialog (``AppConfig.restore_options``).
    options: dict[str, str | bool | int] | None = Field(default=None, max_length=20)


class ScheduleIn(BaseModel):
    every: str = Field(max_length=16)
    time: str = Field(max_length=5)
    keep: Any


#: The schemas of the module by their names, in the order their fields are put together when several get one name.
SCHEMAS: dict[str, type[BaseModel]] = {"NoteIn": NoteIn, "PasswordIn": PasswordIn, "CheckIn": CheckIn,
                                       "DownloadIn": DownloadIn, "RestoreIn": RestoreIn, "ScheduleIn": ScheduleIn}
#: The routes of ``router`` and of ``legacy_router`` by name (their functions), for ``operation_ids`` and ``summaries``.
ROUTES = ("storage", "backups", "schedule", "make", "dismiss", "upload", "check", "download", "restore_route", "delete")
LEGACY_ROUTES = ("listing", "create", "upload", "check", "restore_route", "download", "delete")

#: The schema names the apps' own backup routes had before the module (E53): the body of making a backup
#: ``CreateIn``, of deleting and restoring ``PasswordIn``, of downloading ``DownloadIn``, all in
#: ``app.routers.backups`` (FastAPI wrote ``app__routers__backups__PasswordIn`` where the app had other classes of the
#: name). The module's ``ScheduleIn`` gets a name of its own, so an app's ``ScheduleIn`` keeps its short name; with
#: ``NoteIn`` and ``RestoreIn`` gone from the description the app's own ones keep theirs too.
FORMER_SCHEMAS: dict[str, str] = {
    "NoteIn": "app.routers.backups.CreateIn",
    "PasswordIn": "app.routers.backups.PasswordIn",
    "RestoreIn": "app.routers.backups.PasswordIn",
    "DownloadIn": "app.routers.backups.DownloadIn",
    "ScheduleIn": "BackupScheduleIn",
}


def former_names(prefix: str) -> dict[str, dict[str, str]]:
    """The names the apps' own routes under ``prefix`` had before the module (``legacy_router(...,
    **former_names(prefix))``): the restore's operationId and summary, the summaries of upload and download, and
    ``FORMER_SCHEMAS``."""
    restore = re.sub(r"\W", "_", f"restore{prefix}/{{name}}/restore") + "_post"
    return {
        "operation_ids": {"restore_route": restore},
        "summaries": {
            "upload": "Bring in an archive from elsewhere (the body is the ZIP); needs the password again",
            "download": "The archive itself, to keep a copy elsewhere; needs the password again",
            "restore_route": "Restore",
        },
        "schema_names": dict(FORMER_SCHEMAS),
    }


#: One class per name and set of sources, so that both routers (and a router mounted twice) share it.
_named: dict[tuple[str, tuple[str, ...]], type[BaseModel]] = {}


def _checked(given: dict[str, str] | None, known: tuple[str, ...], what: str) -> dict[str, str]:
    given = dict(given or {})
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)} (known: {', '.join(known)})")
    return given


def schemas(schema_names: dict[str, str] | None = None) -> dict[str, type[BaseModel]]:
    """The schema classes the routes use: the module's own, or under the names the app gives. Several given one name
    become one class with the fields of all (the same field must have the same type in each)."""
    names = _checked(schema_names, tuple(SCHEMAS), "schema")
    groups: dict[str, list[str]] = {}
    for key in SCHEMAS:
        groups.setdefault(names.get(key, key), []).append(key)
    found: dict[str, type[BaseModel]] = {}
    for target, keys in groups.items():
        if keys == [target]:
            model = SCHEMAS[target]
        else:
            model = _named.get((target, tuple(keys)))
            if model is None:
                fields: dict[str, Any] = {}
                for key in keys:
                    for field, info in SCHEMAS[key].model_fields.items():
                        if field in fields and fields[field][0] != info.annotation:
                            raise ValueError(f"{target}: field {field} differs between {', '.join(keys)}")
                        fields[field] = (info.annotation, info)
                place, _, name = target.rpartition(".")
                model = create_model(name, __module__=place or __name__, **fields)
                _named[(target, tuple(keys))] = model
        for key in keys:
            found[key] = model
    return found


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

    def restore(self, name: str, body: Any, request: Request, account: Any) -> tuple[Any, dict[str, Any], bool]:
        self.confirm(request, account, body.password)
        try:
            if current().restore == NOW:
                brief, result = restore.restore_now(name, viewer=self.viewer(account),
                                                    archive_password=body.archive_password, options=body.options)
                return brief, result, False
            brief = restore.stage_restore(name, viewer=self.viewer(account), archive_password=body.archive_password,
                                          options=body.options)
        except BackupError as exc:
            raise self.fail(exc) from exc
        restore.restart_soon()
        return brief, {}, True


def router(*, operator: Any, confirm: Callable[[Request, Any, str], None], prefix: str = "/api/server/storage",
           error: ErrorMaker | None = None, viewer: Callable[[Any], Any] = lambda account: getattr(account, "id", None),
           password_header: str = PASSWORD_HEADER, tags: list[str] | None = None,
           operation_ids: dict[str, str] | None = None, summaries: dict[str, str] | None = None,
           schema_names: dict[str, str] | None = None) -> APIRouter:
    """The module's own routes. ``operator``: the app's operator-only dependency. ``confirm(request, account,
    password)``: the app's check of the operator's password (raises its own error when wrong; an account from a
    provider passes on a fresh sign-in). ``error(code, text, status)``: the app's error maker (default: HTTPException
    with ``{"code", "message"}``). ``operation_ids``, ``summaries`` (by ``ROUTES``), ``schema_names`` (by
    ``SCHEMAS``): names in the description (E53); give ``schema_names`` the same as to ``legacy_router``."""
    kit = _Kit(error, confirm, viewer)
    Operator = _operator(operator)
    api = APIRouter(prefix=prefix, tags=tags or ["storage"])
    ids = _checked(operation_ids, ROUTES, "route")
    said = _checked(summaries, ROUTES, "route")
    S = schemas(schema_names)
    Note, Password, Check, Download, Restore, Schedule = (S["NoteIn"], S["PasswordIn"], S["CheckIn"],
                                                          S["DownloadIn"], S["RestoreIn"], S["ScheduleIn"])

    def named(route: str, summary: str) -> dict[str, Any]:
        return {"operation_id": ids.get(route), "summary": said.get(route, summary)}

    @api.get("", **named("storage", "What the app takes on the disk, how full it is, network shares (operator)"))
    def storage(_account: Operator) -> dict[str, Any]:
        return space.overview()

    @api.get("/backups", **named("backups", "The schedule, the last backup, a failure, and the list (operator)"))
    def backups(_account: Operator) -> dict[str, Any]:
        return {**plan.summary(), "backups": [entry_view(entry) for entry in archives.entries()]}

    @api.put("/backups/schedule", **named("schedule", "Automatic backups: off, daily, weekly, monthly; the time; how "
                                                      "many"))
    def schedule(body: Schedule, _account: Operator) -> dict[str, Any]:  # type: ignore[valid-type]
        try:
            saved = plan.save(plan.checked(body.every, body.time, body.keep))
        except BackupError as exc:
            raise kit.fail(exc) from exc
        return {"every": saved.every, "time": saved.time, "keep": saved.keep}

    @api.post("/backups", status_code=201, **named("make", "Make a backup now"))
    def make(account: Operator, body: Note = Body(default_factory=Note)) -> dict[str, Any]:  # type: ignore[valid-type]  # noqa: B008
        try:
            path = archives.create(note=body.note, wait=False)
        except BackupError as exc:
            raise kit.fail(exc) from exc
        found = next((entry for entry in archives.entries() if entry.name == path.name), None)
        return {"name": path.name, "entry": entry_view(found) if found else None}

    @api.delete("/backups/restore-failed", status_code=204, **named("dismiss", "The failed restore was seen"))
    def dismiss(_account: Operator) -> None:
        restore.forget_failed()

    @api.post("/backups/upload", status_code=201, **named("upload", "Bring in a backup from elsewhere (the body is "
                                                          "the archive); needs the password again, in the header"))
    async def upload(request: Request, account: Operator) -> dict[str, str]:
        return {"name": await kit.upload(request, account, password_header)}

    @api.post("/backups/{name}/check", **named("check", "The trial run: whole or not, what a restore would change"))
    def check(name: str, account: Operator,
              body: Check = Body(default_factory=Check)) -> dict[str, Any]:  # type: ignore[valid-type]  # noqa: B008
        try:
            return restore.check(name, viewer=kit.viewer(account), archive_password=body.archive_password).view()
        except BackupError as exc:
            raise kit.fail(exc) from exc

    @api.post("/backups/{name}/download", **named("download", "The archive itself; needs the password again"))
    def download(name: str, body: Download, request: Request, account: Operator) -> FileResponse:  # type: ignore[valid-type]
        kit.confirm(request, account, body.password)
        return kit.download(name, account, body.archive_password)

    @api.post("/backups/{name}/restore", **named("restore_route", "Keep the current state, then restore; needs the "
                                                                  "password again"))
    def restore_route(name: str, body: Restore, request: Request, account: Operator) -> Any:  # type: ignore[valid-type]
        brief, result, restarting = kit.restore(name, body, request, account)
        from fastapi.responses import JSONResponse

        return JSONResponse({**brief.view(), "result": result, "restarting": restarting},
                            status_code=202 if restarting else 200)

    @api.delete("/backups/{name}", status_code=204, **named("delete", "Delete a backup; needs the password again"))
    def delete(name: str, body: Password, request: Request, account: Operator) -> None:  # type: ignore[valid-type]
        kit.confirm(request, account, body.password)
        try:
            archives.remove(name)
        except BackupError as exc:
            raise kit.fail(exc) from exc

    return api


def legacy_router(*, prefix: str, password_header: str, operator: Any, confirm: Callable[[Request, Any, str], None],
                  error: ErrorMaker | None = None,
                  viewer: Callable[[Any], Any] = lambda account: getattr(account, "id", None),
                  check_raises_too_new: bool = False, tags: list[str] | None = None,
                  operation_ids: dict[str, str] | None = None, summaries: dict[str, str] | None = None,
                  schema_names: dict[str, str] | None = None) -> APIRouter:
    """The app's old ways (``/api/backups``, nexpaper ``/api/v1/backups``) with its old password header
    (``x-<app>-password``), in the old shapes: the list as an array of flat entries, ``{name}`` after making or
    bringing in, the check flat with ``usable``, the restore 202 with ``restarting``. ``check_raises_too_new``: the
    app's old check refused an archive of a newer version with 400 ``backup_too_new`` (nexnotes, nextime, nexfolk)
    instead of answering it. ``operation_ids``, ``summaries`` (by ``LEGACY_ROUTES``), ``schema_names`` (by
    ``SCHEMAS``): the names the app's routes had in its description (E53; ``**former_names(prefix)``)."""
    kit = _Kit(error, confirm, viewer)
    Operator = _operator(operator)
    api = APIRouter(prefix=prefix, tags=tags or ["backups"])
    ids = _checked(operation_ids, LEGACY_ROUTES, "route")
    said = _checked(summaries, LEGACY_ROUTES, "route")
    S = schemas(schema_names)
    Note, Password, Download, Restore = S["NoteIn"], S["PasswordIn"], S["DownloadIn"], S["RestoreIn"]

    def named(route: str) -> dict[str, Any]:
        return {"operation_id": ids.get(route), "summary": said.get(route)}

    @api.get("", **named("listing"))
    def listing(_account: Operator) -> list[dict[str, Any]]:
        return [entry.flat() for entry in archives.entries() if entry.readable]

    @api.post("", status_code=201, **named("create"))
    def create(_account: Operator, body: Note = Body(default_factory=Note)) -> dict[str, str]:  # type: ignore[valid-type]  # noqa: B008
        try:
            return {"name": archives.create(note=body.note, wait=False).name}
        except BackupError as exc:
            raise kit.fail(exc) from exc

    @api.post("/upload", status_code=201, **named("upload"))
    async def upload(request: Request, account: Operator) -> dict[str, str]:
        return {"name": await kit.upload(request, account, password_header)}

    @api.post("/{name}/check", **named("check"))
    def check(name: str, account: Operator) -> dict[str, Any]:
        try:
            brief = restore.check(name, viewer=kit.viewer(account))
        except BackupError as exc:
            raise kit.fail(exc) from exc
        if check_raises_too_new and brief.too_new:
            raise kit.fail(BackupError("backup_too_new", f"the archive comes from version {brief.version}, newer "
                                                         "than this one"))
        return brief.flat()

    @api.post("/{name}/restore", status_code=202, **named("restore_route"))
    def restore_route(name: str, body: Restore, request: Request, account: Operator) -> Any:  # type: ignore[valid-type]
        brief, result, restarting = kit.restore(name, body, request, account)
        from fastapi.responses import JSONResponse

        return JSONResponse({**brief.flat(), **result, "restarting": restarting},
                            status_code=202 if restarting else 200)

    @api.post("/{name}/download", **named("download"))
    def download(name: str, body: Download, request: Request, account: Operator) -> FileResponse:  # type: ignore[valid-type]
        kit.confirm(request, account, body.password)
        return kit.download(name, account, body.archive_password)

    @api.delete("/{name}", status_code=204, **named("delete"))
    def delete(name: str, body: Password, request: Request, account: Operator) -> None:  # type: ignore[valid-type]
        kit.confirm(request, account, body.password)
        try:
            archives.remove(name)
        except BackupError as exc:
            raise kit.fail(exc) from exc

    return api
