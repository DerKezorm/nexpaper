"""Version and license (open to anybody), and whether a newer nexpaper is out: the routes of the shared module
``nexupdates`` (updates 0.1.1) under ``/api/v1/about``, where they were.

Only an operator sees the state of the check, switches it and asks now (U2, U15): the question goes out for the whole
installation. A member's ``GET /api/v1/about/updates`` answers 200 in the form of before with every field empty and
``hidden`` true (U21), and never asks. The routes keep their operationIds, summaries and schema names (Bauplan E53).
"""

from __future__ import annotations

from typing import Any

from ..deps import require_account, require_operator
from ..models import OPERATOR
from ..services import updates
from ..vendor.nexupdates import api

#: The summaries of before (E53); the operationIds come out the same from the routes' names and paths.
SUMMARIES = {
    "about": "About nexpaper",
    "update_state": "Whether a newer nexpaper is out (asked once a day)",
}

REPO_URL = updates.REPO_URL


def _is_operator(account: Any) -> bool:
    return getattr(account, "role", None) == OPERATOR


router = api.router(
    account=require_account, operator=require_operator, is_operator=_is_operator, prefix="/api/v1/about",
    tags=["about"], summaries=SUMMARIES,
)
