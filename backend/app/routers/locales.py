"""The operator's own languages, for the language menus and the card Server › Allgemein › Sprachen: the routes of the
shared module sprachen 1.0.0 (E51) under ``/api/v1/locales``, where nexpaper's own ones were.

``GET`` the list, ``GET /{code}`` the texts of one file, ``PUT /{code}`` and ``DELETE /{code}`` for the operator,
``GET /template`` (404: the page makes the template). Readable without signing in: the sign-in page is shown in the
chosen language too, and the texts are the same for everybody. The refusals keep nexpaper's form
(``{"detail": {"code", "message", …}}``) and their codes of before.
"""

from __future__ import annotations

from ..deps import require_operator
from ..services import locales as _configured  # noqa: F401 (configures the module with nexpaper's folder first)
from ..vendor.nexsprachen import api

router = api.router(operator=require_operator, prefix="/api/v1/locales", tags=["locales"])
