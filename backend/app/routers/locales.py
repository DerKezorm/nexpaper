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

#: The names these routes had in ``/api/v1/openapi.json`` before the module (sprachen step 9): a snapshot and a
#: generated client keep working; the module only adds the fields ``built_in``, ``own`` and the route ``/template``.
OPERATION_IDS = {
    "list": "list_locales_api_v1_locales_get",
    "read": "read_locale_api_v1_locales__code__get",
    "upload": "upload_locale_api_v1_locales__code__put",
    "remove": "delete_locale_api_v1_locales__code__delete",
}
SUMMARIES = {
    "list": "Languages the operator added",
    "read": "The texts of one added language",
    "upload": "Add or replace a language (operator)",
    "remove": "Remove an added language (operator)",
}
SCHEMA_NAMES = {"LanguageEntry": "LocaleEntry"}

router = api.router(operator=require_operator, prefix="/api/v1/locales", tags=["locales"], operation_ids=OPERATION_IDS,
                    summaries=SUMMARIES, schema_names=SCHEMA_NAMES)
