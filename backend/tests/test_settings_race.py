"""A setting written by two starts of nexpaper at once (found in nexdiary, same ground: four test clients started
together, each took the AI settings over at its start, ``adopt``, and one broke on ``UNIQUE constraint failed:
settings.key``). ``settings_service.save`` puts its value onto the row the other start wrote meanwhile instead of
failing, with ``commit`` and without."""

from __future__ import annotations

from typing import Any

import pytest

from app.db import SessionLocal
from app.models import Setting
from app.services import settings_service


@pytest.mark.parametrize("commit", [True, False])
def test_a_setting_written_meanwhile_by_another_start_takes_the_value(
    monkeypatch: pytest.MonkeyPatch, commit: bool
) -> None:
    with SessionLocal() as other:
        settings_service.save(other, {"log_mode": "trace"})
    with SessionLocal() as db:
        real_get = db.get
        seen: list[Any] = []

        def late_get(model: Any, key: Any, **kwargs: Any) -> Any:
            # The first look happens before the other start wrote its row.
            if model is Setting and not seen:
                seen.append(key)
                return None
            return real_get(model, key, **kwargs)

        monkeypatch.setattr(db, "get", late_get)
        settings_service.save(db, {"log_mode": "debug"}, commit=commit)
        if not commit:
            db.commit()
    with SessionLocal() as db:
        assert settings_service.get(db, "log_mode") == "debug"
        assert db.query(Setting).filter_by(key="log_mode").count() == 1
