"""Web Push over HTTP (``services/push.py``): the own devices, a probe, and the operator's card.

Every route of a person reaches only that person's devices: the ids are random and looked up together with the
account of the session, so a device of somebody else answers exactly like one that does not exist. The operator sees
how many devices there are on the server, never whose or which.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..deps import Account, DbSession, OperatorAccount, confirm_operator
from ..services import brakes, notices, push, webpush
from .auth import interface_language

router = APIRouter(prefix="/api/v1", tags=["push"])
logger = logging.getLogger("nexpaper.push")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceIn(Strict):
    endpoint: str = Field(max_length=push.ENDPOINT_MAX)
    p256dh: str = Field(max_length=push.KEY_MAX)
    auth: str = Field(max_length=push.KEY_MAX)
    #: Opened from the home screen: the name says so.
    installed: bool = False


class LookupIn(Strict):
    endpoint: str = Field(max_length=push.ENDPOINT_MAX)


class NameIn(Strict):
    name: str = Field(max_length=push.NAME_MAX * 4)


class OperatorIn(Strict):
    contact: str | None = Field(default=None, max_length=push.CONTACT_MAX * 2)
    hosts: list[Annotated[str, Field(max_length=push.HOST_MAX + 10)]] | None = Field(default=None,
                                                                                    max_length=push.HOSTS_MAX * 2)


class ConfirmIn(Strict):
    current_password: str = Field(default="", max_length=200)


@router.get("/push", summary="The key a browser signs up with, and the own devices")
def state(account: Account, db: DbSession) -> dict[str, Any]:
    return {"key": webpush.public_key(db),
            "devices": push.list_devices(db, account.id)}


@router.post("/push/devices", summary="Sign this browser up for notices; the same browser twice stays one")
def add(payload: DeviceIn, request: Request, response: Response, account: Account, db: DbSession) -> dict[str, Any]:
    brakes.take("push", account.id)
    lang = account.language or interface_language(request)
    agent = request.headers.get("user-agent", "")
    device, new = push.add_device(
        db, account.id, endpoint=payload.endpoint, p256dh=payload.p256dh,
        auth=payload.auth, name=notices.device_name(agent, lang, payload.installed), lang=lang,
        phone=notices.system_of(agent) in ("iPhone", "iPad", "Android"),
    )
    response.status_code = 201 if new else 200
    return device


@router.post("/push/devices/lookup", summary="Whether this browser is signed up: the id of the own device, or none")
def lookup(payload: LookupIn, account: Account, db: DbSession) -> dict[str, Any]:
    return {"id": push.lookup(db, account.id, payload.endpoint)}


@router.put("/push/devices/{device_id}", summary="Give an own device another name")
def rename(device_id: str, payload: NameIn, account: Account, db: DbSession) -> dict[str, Any]:
    return push.rename(db, account.id, device_id[:64], payload.name)


@router.delete("/push/devices/{device_id}", status_code=204, summary="Remove an own device")
def remove(device_id: str, account: Account, db: DbSession) -> None:
    push.remove(db, account.id, device_id[:64])


@router.post("/push/test", summary="A probe to every own device")
def probe(account: Account, db: DbSession) -> dict[str, int]:
    brakes.take("push_test", account.id)
    if not push.has_devices(db, account.id):
        raise push.fail("push_no_devices", 409)
    return notices.probe(account).as_dict()


# --- The operator ---------------------------------------------------------------------------------------------------


@router.get("/settings/push", summary="Web Push on this server: ready, how many devices, the key, the contact")
def operator_view(_operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    return push.operator_view(db)


@router.put("/settings/push", summary="Who the push services may contact, and push services beyond the known ones")
def operator_save(payload: OperatorIn, _operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    return push.operator_save(db, contact=payload.contact, hosts=payload.hosts)


@router.post("/settings/push/renew", summary="A new key pair; every device has to sign up again")
def renew(payload: ConfirmIn, request: Request, operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    confirm_operator(request, db, operator, payload.current_password)
    push.renew_keys(db)
    logger.warning("Web Push keys renewed, every device signed off by=%s", operator.name)
    return push.operator_view(db)
