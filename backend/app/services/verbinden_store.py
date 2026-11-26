"""nexpaper's side of the shared module ``vendor/nexverbinden`` (verbinden 0.1.1): its ``AppConfig`` and the ``Store``
over the module's tables (``models_verbinden.py``).

nexpaper's pairs in the catalog: nextime reads its deadlines (``deadlines.read``), nexmail adds documents
(``documents.add``), and nexpaper uses tasks of nextasks (``tasks.read``, ``tasks.write``). A connection's token
(``npv_``, refresh ``npvr_``) opens ``GET /api/v1/deadlines`` and the upload of documents like an API key of that right,
limited to the vaults given at the consent (``deps.py``). nexpaper had no connections of its own before, so nothing is
"verbunden über API-Schlüssel" here: the older ways in are API keys (``npk_``) a partner holds, and they keep working.
The partner's own side (nextime ``PUT /api/nexpaper``) is the partner's.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from .. import __version__
from ..db import SessionLocal
from ..models import Account, ApiKey
from ..models_verbinden import VbCode, VbConnection, VbPending, VbSpent, VbWaiting
from ..security import decrypt_secret, encrypt_secret
from ..vendor import nexverbinden
from ..vendor.nexverbinden.model import Area
from . import settings_service

#: The partners nexpaper has a use with (V20: no card without one): it hosts nextime (deadlines) and nexmail
#: (documents), and it is the guest of nextasks (a task from a document, ``services/task_from_document.py``).
CONFIG = nexverbinden.AppConfig(
    app_name="nexpaper", version=__version__, access_prefix="npv_", refresh_prefix="npvr_", code_prefix="npvc_",
    in_use=("nextime", "nexmail", "nextasks"),
)

#: The module's settings and nexpaper's names for them; the context of sealed tokens.
SETTINGS = {"connections": "connections_enabled", "addresses": "connections_addresses",
            "connections_local_network": "connections_local_network"}
SEAL_CONTEXT = "connections:token"


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _list(text: str | None) -> Any:
    return json.loads(text) if text else None


class VerbindenStore:
    """The module's ``Store`` inside one SQLAlchemy session (one request)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    # --- connections ---------------------------------------------------------------------------------------------

    @staticmethod
    def _connection(row: VbConnection | None) -> Any:
        if row is None:
            return None
        return nexverbinden.Connection(
            id=row.id, account_id=row.account_id, partner=row.partner, partner_base=row.partner_base,
            partner_account=row.partner_account, uses=tuple(json.loads(row.uses)), grants=tuple(json.loads(row.grants)),
            areas_granted=_list(row.areas_granted), areas_used=_list(row.areas_used), held=row.held,
            issued_access_hash=row.issued_access_hash, issued_refresh_hash=row.issued_refresh_hash,
            issued_access_expires=_when(row.issued_access_expires), created_at=_when(row.created_at),
            used_at=_when(row.used_at), ok_at=_when(row.ok_at), state=row.state, stale_since=_when(row.stale_since),
            problem=row.problem, partner_version=row.partner_version or "",
        )

    def connections(self, account_id: Any) -> list[Any]:
        rows = self.db.scalars(select(VbConnection).where(VbConnection.account_id == account_id)
                               .order_by(VbConnection.partner))
        return [self._connection(row) for row in rows]

    def connection(self, account_id: Any, partner: str) -> Any:
        return self._connection(self.db.scalar(select(VbConnection).where(
            VbConnection.account_id == account_id, VbConnection.partner == partner)))

    def by_issued_access(self, token_hash: str) -> Any:
        return self._connection(self.db.scalar(select(VbConnection).where(
            VbConnection.issued_access_hash == token_hash)))

    def by_issued_refresh(self, token_hash: str) -> Any:
        return self._connection(self.db.scalar(select(VbConnection).where(
            VbConnection.issued_refresh_hash == token_hash)))

    def save(self, c: Any) -> None:
        self.db.merge(VbConnection(
            id=c.id, account_id=c.account_id, partner=c.partner, partner_base=c.partner_base,
            partner_account=c.partner_account, uses=json.dumps(list(c.uses)), grants=json.dumps(list(c.grants)),
            areas_granted=json.dumps(c.areas_granted) if c.areas_granted is not None else None,
            areas_used=json.dumps(c.areas_used) if c.areas_used is not None else None, held=c.held,
            issued_access_hash=c.issued_access_hash, issued_refresh_hash=c.issued_refresh_hash,
            issued_access_expires=_iso(c.issued_access_expires), created_at=_iso(c.created_at),
            used_at=_iso(c.used_at), ok_at=_iso(c.ok_at), state=c.state, stale_since=_iso(c.stale_since),
            problem=c.problem, partner_version=c.partner_version or "",
        ))
        self.db.flush()

    def remove(self, connection_id: str) -> None:
        self.db.query(VbConnection).filter(VbConnection.id == connection_id).delete()
        self.db.query(VbSpent).filter(VbSpent.connection_id == connection_id).delete()
        self.db.flush()

    # --- started connections and codes -----------------------------------------------------------------------------

    def add_pending(self, p: Any) -> None:
        self.db.add(VbPending(state_hash=p.state_hash, account_id=p.account_id, partner=p.partner,
                              partner_base=p.partner_base, verifier=p.verifier,
                              areas_granted=json.dumps(p.areas_granted) if p.areas_granted is not None else None,
                              created_at=_iso(p.created_at)))
        self.db.flush()

    def take_pending(self, state_hash: str) -> Any:
        row = self.db.get(VbPending, state_hash)
        if row is None:
            return None
        found = nexverbinden.Pending(state_hash=row.state_hash, account_id=row.account_id, partner=row.partner,
                                     partner_base=row.partner_base, verifier=row.verifier,
                                     areas_granted=_list(row.areas_granted), created_at=_when(row.created_at))
        self.db.delete(row)
        self.db.flush()
        return found

    def add_code(self, c: Any) -> None:
        self.db.add(VbCode(code_hash=c.code_hash, account_id=c.account_id, partner=c.partner,
                           partner_base=c.partner_base, redirect_uri=c.redirect_uri, challenge=c.challenge,
                           areas_granted=json.dumps(c.areas_granted) if c.areas_granted is not None else None,
                           expires_at=_iso(c.expires_at)))
        self.db.flush()

    def take_code(self, code_hash: str) -> Any:
        row = self.db.get(VbCode, code_hash)
        if row is None:
            return None
        found = nexverbinden.Code(code_hash=row.code_hash, account_id=row.account_id, partner=row.partner,
                                  partner_base=row.partner_base, redirect_uri=row.redirect_uri,
                                  challenge=row.challenge, areas_granted=_list(row.areas_granted),
                                  expires_at=_when(row.expires_at))
        self.db.delete(row)
        self.db.flush()
        return found

    # --- spent -------------------------------------------------------------------------------------------------------

    def spend(self, connection_id: str, token_hash: str, keep: int) -> None:
        at = int(self.db.scalar(select(func.coalesce(func.max(VbSpent.at), 0))) or 0) + 1
        self.db.merge(VbSpent(token_hash=token_hash, connection_id=connection_id, at=at))
        self.db.flush()
        kept = list(self.db.scalars(select(VbSpent.at).where(VbSpent.connection_id == connection_id)
                                    .order_by(VbSpent.at.desc()).limit(keep)))
        self.db.query(VbSpent).filter(VbSpent.connection_id == connection_id, VbSpent.at.not_in(kept)).delete(
            synchronize_session=False)
        self.db.flush()

    def spent_by(self, token_hash: str) -> str | None:
        row = self.db.get(VbSpent, token_hash)
        return None if row is None else row.connection_id

    # --- waiting revocations -------------------------------------------------------------------------------------

    def revoke_later(self, account_id: Any, partner_base: str, sealed_token: str, now: datetime) -> None:
        self.db.add(VbWaiting(account_id=account_id, partner_base=partner_base, token=sealed_token, since=_iso(now)))
        self.db.flush()

    def waiting(self) -> list[Any]:
        rows = self.db.scalars(select(VbWaiting).order_by(VbWaiting.id))
        return [nexverbinden.Waiting(row.id, row.partner_base, row.token, _when(row.since)) for row in rows]

    def done_waiting(self, waiting_id: Any) -> None:
        self.db.query(VbWaiting).filter(VbWaiting.id == waiting_id).delete()
        self.db.flush()

    # --- the account and the app ---------------------------------------------------------------------------------

    def account_may(self, account_id: Any) -> bool:
        from .schluessel_store import out

        return not out(self.db.get(Account, account_id))

    def account_name(self, account_id: Any) -> str:
        row = self.db.get(Account, account_id)
        return row.name if row is not None else "?"

    def areas(self, account_id: Any) -> list[Area]:
        """The vaults of the account: what a partner that reads nexpaper may be limited to."""
        from . import vaults

        return [Area(id=view.vault.id, name=view.name) for view in vaults.listing(self.db, int(str(account_id)))]

    def legacy(self, account_id: Any) -> list[Any]:
        # nexpaper connected to no other app before: nothing typed in by hand to show.
        return []

    def retire_key(self, token: str) -> bool:
        """An API key of nexpaper that a partner held before "Neu verbinden" ends itself."""
        from ..vendor.nexschluessel import digest

        row = self.db.scalar(select(ApiKey).where(ApiKey.token_hash == digest(token)))
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    def setting(self, name: str) -> Any:
        from ..models import Setting

        row = self.db.get(Setting, SETTINGS[name])
        return None if row is None else row.value

    def set_setting(self, name: str, value: Any) -> None:
        settings_service.save(self.db, {SETTINGS[name]: value}, commit=False)

    def local_allowed(self) -> bool:
        return bool(self.setting("connections_local_network"))

    def set_local_allowed(self, on: bool) -> None:
        """verbinden 0.1.4: the operator's box "Verbindungen ins eigene Netz" in "Andere nex-Apps"."""
        self.set_setting("connections_local_network", bool(on))

    def seal(self, text: str) -> str:
        return encrypt_secret(text, SEAL_CONTEXT)

    def unseal(self, sealed: str) -> str:
        return decrypt_secret(sealed, SEAL_CONTEXT)

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def on_disconnected(store: VerbindenStore, account_id: Any, partner: str) -> None:
    """verbinden 0.1.4: a connection ended, by "Trennen" here or by the partner's revocation. nexpaper's own row of it
    goes: the list of nextasks used last (``services/task_from_document.py``)."""
    from ..models_verbinden import NextasksListUsed

    if partner == "nextasks":
        store.db.query(NextasksListUsed).filter(NextasksListUsed.account_id == int(str(account_id))).delete()
        store.commit()


def store() -> Iterator[VerbindenStore]:
    """The dependency of the module's routes: one session per request."""
    with SessionLocal() as db:
        yield VerbindenStore(db)


__all__ = ["CONFIG", "VerbindenStore", "on_disconnected", "store"]
