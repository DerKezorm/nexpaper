"""The AI over HTTP: what a person may know about it, and the operator's settings.

Nothing is sent anywhere from here: the state comes from the settings alone, and the operator's routes are the only way
to choose a service; they never show the key. The proposals for documents come with the block that sorts them.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from ..deps import Account, DbSession, OperatorAccount
from ..services import ai
from .auth import profile_of

router = APIRouter(prefix="/api/v1", tags=["ai"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AiSettingsIn(Strict):
    provider: Literal["none", "local", "openai", "messages"] | None = None
    url: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=200)
    #: Empty removes the key; left out keeps it (unless the address or the kind of service changes).
    key: str | None = Field(default=None, max_length=500)
    #: Documents in personal vaults never go to the AI (on from the start).
    skip_personal: StrictBool | None = None
    #: The most documents sent to the AI in one day, on the whole server; 0 is no limit.
    daily_limit: StrictInt | None = Field(default=None, ge=0, le=1_000_000)
    #: The operator's own wishes for the proposals, added to the fixed rules; empty removes them.
    instructions: str | None = Field(default=None, max_length=ai.INSTRUCTIONS_MAX)


class ModelsIn(Strict):
    provider: Literal["local", "openai", "messages"] | None = None
    url: str | None = Field(default=None, max_length=255)
    key: str | None = Field(default=None, max_length=500)


def own_switch(account: Any) -> bool:
    return bool(profile_of(account.profile)["ai"])


@router.get("/ai", summary="Whether this person can use the AI, by which kind of service, and where to")
def state(account: Account, db: DbSession) -> dict[str, Any]:
    return ai.state(db, own_switch(account), bool(account.ai_allowed))


# --- The operator ---------------------------------------------------------------------------------------------------


@router.get("/settings/ai", summary="The AI service of the server, without its key")
def settings(_operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    return ai.operator_view(db)


@router.put("/settings/ai", summary="Choose the AI service of the server; only the fields sent change")
def save(payload: AiSettingsIn, _operator: OperatorAccount, db: DbSession) -> dict[str, Any]:
    return ai.save(db, provider=payload.provider, url=payload.url, model=payload.model, key=payload.key,
                   skip_personal=payload.skip_personal, daily_limit=payload.daily_limit,
                   instructions=payload.instructions)


@router.post("/settings/ai/models", summary="The models a service offers, with the address typed or stored")
def models(payload: ModelsIn, operator: OperatorAccount, db: DbSession) -> list[dict[str, str]]:
    return ai.list_models(db, operator.id, provider=payload.provider, url=payload.url, key=payload.key)


@router.post("/settings/ai/probe", summary="One tiny question to the stored service, with nothing of a document in it")
def probe(operator: OperatorAccount, db: DbSession) -> dict[str, float]:
    return {"seconds": ai.probe(db, operator.id)}
