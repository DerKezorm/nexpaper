"""The routes of the page Server › Log, for operators only, in the form nexnotes has them:

``GET    <prefix>``           the newest lines (``level``, ``search``, ``limit``, ``offset``), newest first
``GET    <prefix>/level``     the level in force, its end, whether the environment fixes it (and its name), the levels
                             and durations
``PUT    <prefix>/level``     change the level (``{"mode": …, "minutes": …}``), effective at once
``GET    <prefix>/download``  every file as one text
``DELETE <prefix>``           clear the log

The app mounts them with ``app.include_router(nexlog.api.router(operator=<its dependency>))``. ``operator`` is the
app's own check (a FastAPI dependency that refuses with 401 without a session and 403 for a member), so the app keeps
its own rules (networks for operators, no device tokens). ``prefix`` is ``/api/logs`` (nexpaper ``/api/v1/logs``).

The only part of the module that needs FastAPI; the rest is the standard library."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import files, handlers, modes
from .config import current

Level = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Mode = Literal["quiet", "normal", "detailed", "trace"]


class LogEntry(BaseModel):
    time: str
    level: str
    logger: str
    message: str
    request_id: str | None = None
    user: str | None = None
    #: The moment with its offset, for the reader's own time.
    at: str | None = None


class LogMode(BaseModel):
    mode: str
    until: str | None = None
    fixed_by_env: bool = False
    #: The name of the environment variable that can fix the level (the page names it when it does).
    variable: str = Field(default_factory=lambda: current().variable)
    modes: list[str] = Field(default_factory=lambda: list(handlers.MODES))
    durations: list[int] = Field(default_factory=lambda: list(modes.ALLOWED_MINUTES))


class LogModeChange(BaseModel):
    mode: Mode
    minutes: int = 0


def _refuse(code: str, message: str, status: int) -> Exception:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _shown(state: modes.ModeState) -> LogMode:
    return LogMode(mode=state.mode, until=state.until, fixed_by_env=state.fixed_by_env)


def router(
    *,
    operator: Callable[..., Any],
    prefix: str = "/api/logs",
    error: Callable[[str, str, int], Exception] | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """The routes. ``operator``: the app's dependency for operators. ``error(code, message, status)``: the app's own
    form of a refusal (default ``HTTPException`` with ``{"code", "message"}`` as ``detail``)."""
    refuse = error or _refuse
    routes = APIRouter(prefix=prefix, tags=tags or ["logs"], dependencies=[Depends(operator)])

    @routes.get("", response_model=list[LogEntry], summary="The newest lines")
    def read_logs(
        level: Annotated[Level | None, Query()] = None,
        search: Annotated[str | None, Query(max_length=120)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 300,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> list[files.LogLine]:
        return files.read(limit=limit, level=level, search=search, offset=offset)

    @routes.get("/level", response_model=LogMode, summary="Which level applies")
    def read_level() -> LogMode:
        return _shown(modes.state())

    @routes.put("/level", response_model=LogMode, summary="Change the level, effective at once")
    def set_level(change: LogModeChange) -> LogMode:
        if modes.env_mode():
            raise refuse(
                "log_level_from_environment", f"The log level is fixed by {current().variable}.", 409
            )
        deep = change.mode in handlers.DEEP_MODES
        if change.minutes not in (modes.ALLOWED_MINUTES if deep else (0, *modes.ALLOWED_MINUTES)):
            raise refuse("duration_not_allowed", "This duration is not offered.", 422)
        return _shown(modes.set_mode(change.mode, change.minutes))

    @routes.get("/download", include_in_schema=False)
    def download_logs() -> Response:
        text = files.download_text()
        handlers.app_logger().info("Log downloaded by operator")
        return Response(
            content=text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{files.download_name()}"'},
        )

    @routes.delete("", status_code=204, summary="Clear the log")
    def clear_logs() -> None:
        handlers.clear()

    return routes
