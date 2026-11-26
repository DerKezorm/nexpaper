"""nexsprachen contract tests: nexpaper's adapter (copied once from the module's template, now nexpaper's file).

nexpaper as in production: ``services/locales.py`` configures the module with ``NEXPAPER_LOCALES_DIR`` (in the tests
a fresh folder per test, set on the settings and put back afterwards), German, English and French built in, the routes
under ``/api/v1/locales`` readable without signing in, nexpaper's refusals (``{"detail": {"code", "message", …}}``),
the template made on the page (the server has none). The database is the one of the test session
(``tests/conftest.py`` empties it before every test).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sprachen_contract import StandardAdapter

OPERATOR_NAME = "sprachen-operator"


class Adapter(StandardAdapter):
    package = "app.vendor.nexsprachen"
    prefix = "/api/v1/locales"
    also: tuple[str, ...] = ()
    built_in = {"de": "Deutsch", "en": "English", "fr": "Français"}  # noqa: RUF012 (the contract's base declares it so)
    public_read = True
    has_template = False
    # The names the routes had in nexpaper's description before the module, as given to the router (step 9).
    openapi_path = "/api/v1/openapi.json"
    operation_ids = {  # noqa: RUF012 (the contract's base declares it so)
        "list": "list_locales_api_v1_locales_get",
        "read": "read_locale_api_v1_locales__code__get",
        "upload": "upload_locale_api_v1_locales__code__put",
        "remove": "delete_locale_api_v1_locales__code__delete",
    }
    summaries = {  # noqa: RUF012
        "list": "Languages the operator added",
        "read": "The texts of one added language",
        "upload": "Add or replace a language (operator)",
        "remove": "Remove an added language (operator)",
    }
    schema_names = {"LanguageEntry": "LocaleEntry"}  # noqa: RUF012

    def start(self) -> None:
        from app.config import get_settings
        from app.services import locales

        self._clients: list[Any] = []
        self._settings = get_settings()
        self._before = self._settings.locales_dir
        # A fresh folder, as on a new server; nexpaper's own folder of the test session stays as it was.
        self._folder = Path(tempfile.mkdtemp(prefix="nexpaper-locales-"))
        self._settings.locales_dir = self._folder
        locales.forget()

    def restart(self) -> None:
        """nexpaper again on the same folder, as at a start in production (``locales.start``: configure, then tidy)."""
        from app.services import locales

        locales.start()
        locales.forget()

    def offered_template(self) -> dict[str, Any]:
        """The template the card "Sprachen" offers (sprachen 1.0.2): nexpaper's English with the words of the account,
        post and sign-in modules, as ``frontend/src/i18n/index.ts`` puts them together, through ``texts_only``."""
        from app.vendor import nexsprachen

        source = Path(__file__).parents[2] / "frontend" / "src"
        english: dict[str, Any] = {}
        for part in ("i18n/en.json", "vendor/nexoidc/oidc.en.json", "vendor/nexkonten/konten.en.json",
                     "vendor/nexpost/post.en.json"):
            english.update(json.loads((source / part).read_text(encoding="utf-8")))
        return {"_meta": {"name": "Nederlands"}, **nexsprachen.texts_only(english)}

    def stop(self) -> None:
        from app.services import locales

        for client in self._clients:
            client.close()
        self._settings.locales_dir = self._before
        locales.forget()
        shutil.rmtree(self._folder, ignore_errors=True)

    def client(self, role: str) -> Any:
        from app.models import MEMBER, OPERATOR
        from tests.conftest import make_account, new_client

        if role == "anonymous":
            client = new_client()
        else:
            name = OPERATOR_NAME if role == "operator" else "sprachen-member"
            client = new_client(self._account(name, OPERATOR if role == "operator" else MEMBER, make_account))
        self._clients.append(client)
        return client

    @staticmethod
    def _account(name: str, role: str, make: Any) -> Any:
        from app.db import SessionLocal
        from app.models import Account

        with SessionLocal() as db:
            row = db.query(Account).filter_by(name=name).one_or_none()
            if row is not None:
                db.expunge(row)
                return row
        return make(name, role)
