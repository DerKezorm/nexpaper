"""The routes of the page "Über" (about) and its card "Aktualisierungen", in the form nexnotes has them:

``GET  <prefix>``                 version, licence, repository, releases, project page (anybody)
``GET  <prefix>/updates``         the state of the check (an account; a member gets the same form, all empty, U15)
``POST <prefix>/updates/check``   ask now, also with the daily check off (operator)
``PUT  <prefix>/updates``         switch the daily check (operator)

The app mounts them with ``app.include_router(nexupdates.api.router(account=…, operator=…, is_operator=…))``;
``account`` and ``operator`` are the app's dependencies (401 without a session, 403 for a member), ``is_operator``
tells an operator in what ``account`` gives. Since 0.1.1 (U15) a member learns nothing of the check, not even the
switch: ``GET <prefix>/updates`` answers a member 200 in the same form as before (nexnotes answered every account), but
with every field of the state and the switch empty, each in its old type (``update_check`` false), plus ``hidden`` true
(U21; an operator gets false), and never asks the network. Against the old description only ``hidden`` is new. Only an
operator's look may ask (when the state is a day old and the switch is on).

``operation_ids``, ``summaries`` (by ``ROUTES``) and ``schema_names`` (by ``SCHEMAS``; a name or a dotted place and
name) keep an app's old names in its description (E53); the module's own are nexnotes' (``about``,
``update_state``, ``check_now``, ``switch``; ``UpdatesOut``, ``UpdateSwitchIn``). The only part of the module that needs
FastAPI. No postponed annotations here: FastAPI reads the types of the local route functions."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, create_model

from . import check
from .config import current

ROUTES = ("about", "update_state", "check_now", "switch")
SCHEMAS = ("UpdatesOut", "UpdateSwitchIn")
SUMMARIES = {
    "about": "About the app",
    "update_state": "Whether a newer version is out (asked once a day)",
    "check_now": "Ask now, also with the daily check off",
    "switch": "Switch the daily check",
}


class UpdatesOut(BaseModel):
    #: The daily check; false for a member (U15, U21).
    update_check: bool
    checked: bool = False
    latest: str | None = None
    newer: bool = False
    checked_at: datetime | None = None
    #: The release page of the newest version, when there is one.
    release_url: str | None = None
    #: The state is not this account's to see: true for a member, every other field then empty (U21).
    hidden: bool = False


class UpdateSwitchIn(BaseModel):
    update_check: bool


_models: dict[str, type[BaseModel]] = {}


def _named(model: type[BaseModel], target: str | None) -> type[BaseModel]:
    if not target or target == model.__name__:
        return model
    if target not in _models:
        place, _, name = target.rpartition(".")
        fields = {key: (info.annotation, info) for key, info in model.model_fields.items()}
        _models[target] = create_model(name, __module__=place or __name__, **fields)  # type: ignore[call-overload]
    return _models[target]


def _checked(given: dict[str, str] | None, known: tuple[str, ...], what: str) -> dict[str, str]:
    given = dict(given or {})
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)} (known: {', '.join(known)})")
    return given


def view(known: check.State, on: bool) -> dict[str, Any]:
    """The state as the page reads it; a release link only for a tag of the fixed form (``check.parse``)."""
    latest = known.latest if check.parse(known.latest) is not None else None
    return {
        "update_check": on,
        "checked": known.checked_at is not None,
        "latest": latest,
        "newer": bool(latest) and known.newer,
        "checked_at": known.checked_at,
        "release_url": f"{current().releases_url}/tag/{latest}" if latest else None,
        "hidden": False,
    }


#: What a member gets from ``GET <prefix>/updates`` (U15, U21): the form of before, every field empty in its old type,
#: and ``hidden``.
EMPTY: dict[str, Any] = {"update_check": False, "checked": False, "latest": None, "newer": False, "checked_at": None,
                         "release_url": None, "hidden": True}


def router(
    *,
    account: Callable[..., Any],
    operator: Callable[..., Any],
    is_operator: Callable[[Any], bool],
    prefix: str = "/api/about",
    tags: list[str] | None = None,
    operation_ids: dict[str, str] | None = None,
    summaries: dict[str, str] | None = None,
    schema_names: dict[str, str] | None = None,
) -> APIRouter:
    """The routes. ``account``: the app's dependency for a signed-in account; ``operator``: for an operator (401
    without a session, 403 for a member); ``is_operator(account)``: whether what ``account`` gives is an operator."""
    ids = _checked(operation_ids, ROUTES, "route")
    said = SUMMARIES | _checked(summaries, ROUTES, "route")
    names = _checked(schema_names, SCHEMAS, "schema")
    out = _named(UpdatesOut, names.get("UpdatesOut"))
    switch_in = _named(UpdateSwitchIn, names.get("UpdateSwitchIn"))
    Signed = Annotated[Any, Depends(account)]
    Operator = Annotated[Any, Depends(operator)]
    routes = APIRouter(prefix=prefix, tags=tags or ["about"])

    @routes.get("", summary=said["about"], operation_id=ids.get("about"))
    def about() -> dict[str, Any]:
        config = current()
        return {
            "version": config.running(),
            "license": config.license,
            "repo_url": config.repo_url,
            "releases_url": config.releases_url,
            "project_url": config.project_url,
        }

    @routes.get("/updates", response_model=out, summary=said["update_state"], operation_id=ids.get("update_state"))
    def update_state(signed: Signed) -> dict[str, Any]:
        if not is_operator(signed):
            # U15: the same form as before for every account, but nothing of the check, and never a question.
            return dict(EMPTY)
        on = check.switch_on()
        return view(check.state(on=on), on)

    @routes.post("/updates/check", response_model=out, summary=said["check_now"], operation_id=ids.get("check_now"))
    def check_now(_operator: Operator) -> dict[str, Any]:
        """Off means "not by itself"; whoever clicks here has just decided."""
        return view(check.state(on=True, force=True), check.switch_on())

    @routes.put("/updates", response_model=out, summary=said["switch"], operation_id=ids.get("switch"))
    def switch(body: switch_in, _operator: Operator) -> dict[str, Any]:  # type: ignore[valid-type]
        on = check.set_switch(bool(body.update_check))  # type: ignore[attr-defined]
        return view(check.state(on=on), on)

    return routes
