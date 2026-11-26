"""nexpaper's side of the shared AI module ``vendor/nexki`` (ki 0.1.0): its ``AppConfig`` and the parts of the ``Store``
over its settings and tables, under the names they had (Entwurf KI-Anbieter: "Kein Feld wandert").

* The operator's service stays in ``settings``: ``ai_provider`` (its old ``local`` reads as the OpenAI form, K9;
  ``none`` as no service), ``ai_url``, ``ai_model``, ``ai_key_enc`` sealed in its old context ``operator:ai-key``.
  ``ai_daily_limit`` is the module's limit of the server per day (200 from the start, K10), ``ai_day`` its count.
* New beside them: ``ai_enabled`` (the main switch, K3; never stored before: ``adopt`` switches it on where the
  operator's service was complete), ``ai_mode`` (K2: "Einer für alle" as before, or "Jedes Konto selbst"),
  ``ai_hosts`` (K4), ``ai_per_minute``/``ai_per_day``; an account's own service in ``ai_own_access``; "Was ging
  hinaus" in ``ai_events``.
* "KI erlaubt" of an account is ``users.ai_allowed`` (konten), "KI für mich" the profile's ``ai`` (on from the start).
* nexpaper's one task is ``propose`` (``services/ai_proposals.py``), automatic: the first two pages of a new document
  in the inbox and the names of the kinds; its own check (``app_ok``) is "personal vaults never to the AI".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from ..models import Account, Setting
from ..models_ki import AiEvent, AiOwnAccess
from ..security import decrypt_secret, encrypt_secret
from ..vendor import nexki
from ..vendor.nexki import Event, OwnAccess
from . import settings_service

#: nexpaper's AI: one automatic task, its brakes of before (K10: 200 requests a day on the server, four at once, the
#: operator's lists and probes ten a minute).
CONFIG = nexki.AppConfig(
    app_name="nexpaper",
    tasks=(nexki.Task("propose", manual=False, temperature=0.3, max_out=400, seconds=180.0),),
    modes=("shared", "own"),
    operator_key_context="operator:ai-key",
    account_key_context=lambda account_id: f"account:{account_id}:ai",
    server_day=200,
    at_once=4,
    operator_per_minute=10,
)

#: The module's names and nexpaper's settings behind them.
SETTINGS = {
    "enabled": "ai_enabled",
    "mode": "ai_mode",
    "api": "ai_provider",
    "url": "ai_url",
    "model": "ai_model",
    "key": "ai_key_enc",
    "hosts": "ai_hosts",
    "per_minute": "ai_per_minute",
    "per_day": "ai_per_day",
    "server_day": "ai_daily_limit",
    "day": "ai_day",
    "hosts_adopted": "ai_hosts_adopted",
}


class KiParts:
    """The ``nexki.Store`` calls, mixed into the request's store (``services/mcp_store.McpStore``), which serves the
    modules ``schluessel`` and ``mcp`` too."""

    db: Any

    # --- the operator's settings ------------------------------------------------------------------------------

    def ki_setting(self, name: str) -> Any:
        """The setting as stored, ``None`` when never stored (``adopt`` looks for that)."""
        row = self.db.get(Setting, SETTINGS[name])
        value = None if row is None else row.value
        if name == "api" and value in ("", "none"):
            # ``none`` was "no service" in nexpaper; the module knows only the two interfaces.
            return None
        return value

    def set_ki_setting(self, name: str, value: Any) -> None:
        settings_service.save(self.db, {SETTINGS[name]: value}, commit=False)

    # --- the account and the person ---------------------------------------------------------------------------

    def account_allowed(self, account_id: Any) -> bool:
        row = self.db.get(Account, account_id)
        return row is not None and bool(row.ai_allowed)

    def account_out(self, account_id: Any) -> bool:
        from .schluessel_store import out

        return out(self.db.get(Account, account_id))

    def person_on(self, account_id: Any) -> bool:
        from ..routers.auth import profile_of

        row = self.db.get(Account, account_id)
        return row is not None and bool(profile_of(row.profile)["ai"])

    def set_person_on(self, account_id: Any, on: bool) -> None:
        row = self.db.get(Account, account_id)
        if row is None:
            raise LookupError(account_id)
        profile = dict(row.profile) if isinstance(row.profile, dict) else {}
        profile["ai"] = bool(on)
        row.profile = profile
        self.db.flush()

    def own_access(self, account_id: Any) -> OwnAccess | None:
        row = self.db.get(AiOwnAccess, account_id)
        if row is None or not (row.url or row.model):
            return None
        return OwnAccess(api=row.api or "openai", url=row.url, model=row.model, key=row.key_enc or "")

    def set_own_access(self, account_id: Any, access: OwnAccess | None) -> None:
        row = self.db.get(AiOwnAccess, account_id)
        if access is None:
            if row is not None:
                self.db.delete(row)
                self.db.flush()
            return
        if row is None:
            row = AiOwnAccess(account_id=account_id)
            self.db.add(row)
        row.api, row.url, row.model, row.key_enc = access.api, access.url, access.model, access.key
        row.updated_at = nexki.client._now()
        self.db.flush()

    def own_access_urls(self) -> list[str]:
        return [url for url in self.db.scalars(select(AiOwnAccess.url).where(AiOwnAccess.url != "")) if url]

    # --- sealing --------------------------------------------------------------------------------------------------

    def seal(self, text: str, context: str) -> str:
        return encrypt_secret(text, context)

    def unseal(self, sealed: str, context: str) -> str:
        try:
            return decrypt_secret(sealed, context)
        except Exception:  # noqa: BLE001 - another secret or another context: nothing to read
            return ""

    # --- what went out ----------------------------------------------------------------------------------------

    def add_event(self, event: Event) -> None:
        self.db.add(AiEvent(account_id=event.account_id, at=event.at, task=event.task[:40], target=event.to[:255],
                            model=event.model[:200], manual=event.manual, chars=event.chars,
                            outcome=event.outcome[:40], sent=event.sent or ""))
        self.db.flush()

    def events(self, account_id: Any) -> list[Event]:
        rows = self.db.scalars(select(AiEvent).where(AiEvent.account_id == account_id)
                               .order_by(AiEvent.at.desc(), AiEvent.id.desc()))
        return [Event(account_id=row.account_id, at=row.at, task=row.task, to=row.target, model=row.model,
                      manual=bool(row.manual), chars=row.chars, outcome=row.outcome, sent=row.sent or "", id=row.id)
                for row in rows]

    def clear_events(self, account_id: Any) -> int:
        gone = self.db.query(AiEvent).filter(AiEvent.account_id == account_id).delete()
        self.db.flush()
        return int(gone)

    def drop_events(self, before: datetime, *, keep: int) -> int:
        gone = int(self.db.query(AiEvent).filter(AiEvent.at < before).delete())
        for (account_id,) in self.db.execute(select(AiEvent.account_id).group_by(AiEvent.account_id)
                                             .having(func.count() > keep)).all():
            kept = select(AiEvent.id).where(AiEvent.account_id == account_id).order_by(
                AiEvent.at.desc(), AiEvent.id.desc()).limit(keep)
            gone += int(self.db.query(AiEvent).filter(AiEvent.account_id == account_id,
                                                      AiEvent.id.not_in(kept)).delete(synchronize_session=False))
        self.db.flush()
        return gone


__all__ = ["CONFIG", "SETTINGS", "KiParts"]
