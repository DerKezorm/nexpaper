"""The way back to nexpaper 1.0.1, where nexpaper differs from most apps: 1.0.1 asked the code of its own second factor
after the provider (its switch "the provider checks a second factor" off, the default), so the switch is part of what
1.0.1 must find. The migrated entry trusts the provider as the switch says; ``migrate.way_back`` shows 1.0.1 an entry
that trusts it in full (rule 1) with the switch on, one that does not without a client (rule 2: 1.0.1 lets nobody in
through it, never with less than the entry asks), the switch then off. A switch 1.0.1 turns is taken over.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Setting
from app.security import encrypt_secret
from app.services import backups, oidc_store, settings_service
from app.vendor.nexoidc import providers

from .conftest import make_account
from .oidc_helpers import FakeProvider


def older(fake: FakeProvider, *, switch: bool | None = None, **subjects: str) -> None:
    """1.0.1 at work: its settings and the subjects at the accounts (the switch only when named)."""
    with SessionLocal() as db:
        values: dict[str, Any] = {
            "oidc_issuer": fake.issuer, "oidc_client_id": fake.client_id,
            "oidc_client_secret_enc": encrypt_secret(fake.client_secret), "oidc_provider_name": "Company",
        }
        if switch is not None:
            values["oidc_second_factor_by_provider"] = switch
        settings_service.save(db, values)
        for name, subject in subjects.items():
            row = db.scalar(select(Account).where(Account.name == name))
            assert row is not None
            row.oidc_subject = subject
        db.commit()


def fresh_1_0_1(fake: FakeProvider, *, switch: bool = False) -> None:
    """A database of 1.0.1 with its provider and alex linked, then the first start of 1.1.0."""
    with SessionLocal() as db:
        db.query(Setting).filter(Setting.key.in_([oidc_store.MIGRATED, oidc_store.FINGERPRINT, oidc_store.ANCHOR,
                                                  oidc_store.WRITTEN_SECOND_FACTOR])).delete(synchronize_session=False)
        db.commit()
    make_account("alex")
    older(fake, switch=switch, alex="person-1")
    oidc_store.migrate_settings(backup=False)


def found() -> dict[str, Any]:
    """What 1.0.1 finds now: its settings (the secret opened), the switch, and the subjects."""
    with SessionLocal() as db:
        legacy, subjects = oidc_store.read_legacy(db)
        names = {row.id: row.name for row in db.scalars(select(Account))}
        switch = bool(settings_service.get(db, "oidc_second_factor_by_provider"))
    return {"issuer": legacy.issuer, "client_id": legacy.client_id, "client_secret": legacy.client_secret,
            "label": legacy.label, "switch": switch, "subjects": {names[a]: s for a, s in subjects}}


def change(**values: Any) -> None:
    """1.1.0 changes the entry ``oidc`` (through the store, as every route does; the commit writes the way back)."""
    with SessionLocal() as db:
        store = oidc_store.SqlStore(db)
        entry = store.provider_by_slug("oidc")
        assert entry is not None
        store.update_provider(entry.id, providers.values_of(entry, **values))
        store.commit()


def entry_trusts() -> bool:
    with SessionLocal() as db:
        entry = oidc_store.SqlStore(db).provider_by_slug("oidc")
        assert entry is not None
        return entry.trusts_second_factor


def test_1_0_1_finds_the_entry_in_full_with_its_switch_on_only_while_the_entry_trusts_the_provider(
    client: TestClient, provider: FakeProvider
) -> None:
    fresh_1_0_1(provider, switch=False)
    assert entry_trusts() is False
    full = {"issuer": provider.issuer, "client_id": provider.client_id, "client_secret": provider.client_secret,
            "label": "Company", "subjects": {"alex": "person-1"}}
    without = {**full, "client_id": "", "client_secret": "", "switch": False}
    # Not trusted (1.0.1's switch was off): rule 2, no client, the switch off; issuer, name and subjects wait.
    assert found() == without
    oidc_store.migrate_settings(backup=False)
    assert found() == without
    # Trusted here: 1.0.1 finds the entry in full and its switch on, and asks no code either.
    change(trusts_second_factor=True)
    assert found() == {**full, "switch": True}
    # Off here (whatever the second factor), or not trusted: no client, the switch off, through starts.
    for values in ({"enabled": False}, {"enabled": False, "trusts_second_factor": False}, {"trusts_second_factor": False}):
        change(**values)
        for _ in range(2):
            assert found() == without, values
            oidc_store.migrate_settings(backup=False)
        change(enabled=True, trusts_second_factor=True)
        assert found() == {**full, "switch": True}


def test_the_switch_on_in_1_0_1_comes_with_the_migration_and_back(client: TestClient, provider: FakeProvider) -> None:
    fresh_1_0_1(provider, switch=True)
    assert entry_trusts() is True
    assert found()["switch"] is True and found()["client_id"] == provider.client_id


@pytest.mark.parametrize(("before", "after"), [(False, True), (True, False)])
def test_a_switch_1_0_1_turned_since_is_taken_over_at_the_next_start_after_a_backup(
    client: TestClient, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch, before: bool, after: bool
) -> None:
    fresh_1_0_1(provider, switch=before)
    made: list[str] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made.append(kwargs.get("note", "")))
    oidc_store.migrate_settings()
    assert made == [] and entry_trusts() is before
    older(provider, switch=after, alex="person-1")
    oidc_store.migrate_settings()
    assert made == ["before taking over what 1.0.1 changed"]
    assert entry_trusts() is after and found()["switch"] is after
    # Taken over once: the next start changes nothing and backs nothing up.
    oidc_store.migrate_settings()
    assert made == ["before taking over what 1.0.1 changed"] and entry_trusts() is after


def test_while_the_way_back_is_closed_the_switch_stays_off_and_nothing_of_it_is_taken_over(
    client: TestClient, provider: FakeProvider
) -> None:
    fresh_1_0_1(provider, switch=True)
    with SessionLocal() as db:
        store = oidc_store.SqlStore(db)
        entry = store.provider_by_slug("oidc")
        assert entry is not None
        store.delete_provider(entry.id)
        store.commit()
    shown = found()
    assert (shown["issuer"], shown["client_id"], shown["switch"], shown["subjects"]) == ("", "", False, {})
    # A switch 1.0.1 turns while it has no provider changes nothing here.
    with SessionLocal() as db:
        settings_service.save(db, {"oidc_second_factor_by_provider": True})
    oidc_store.migrate_settings(backup=False)
    with SessionLocal() as db:
        assert oidc_store.SqlStore(db).provider_by_slug("oidc") is None


def test_a_provider_1_0_1_sets_up_later_trusts_as_its_switch_says(client: TestClient, provider: FakeProvider) -> None:
    with SessionLocal() as db:
        db.query(Setting).filter(Setting.key == oidc_store.MIGRATED).delete()
        db.commit()
    make_account("alex")
    oidc_store.migrate_settings(backup=False)
    older(provider, switch=True, alex="person-1")
    oidc_store.migrate_settings(backup=False)
    assert entry_trusts() is True and found()["client_id"] == provider.client_id
