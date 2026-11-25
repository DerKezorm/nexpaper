"""Read the log and set its level; operator only. The routes of the shared module ``log`` (``nexlog.api``), under the
same paths and in the same forms as before (``/api/v1/logs``, ``/level``, ``/download``)."""

from __future__ import annotations

from ..deps import require_operator
from ..errors import error
from ..services import logs  # noqa: F401  (configures the module before its routes are used)
from ..vendor.nexlog import api

router = api.router(operator=require_operator, prefix="/api/v1/logs", error=error, tags=["logs"])
