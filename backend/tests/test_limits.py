"""Limits a person cannot pass: the places for unpacking pictures (taken before a body is read). The limits for
documents (size, pages, time) come with the block that takes uploads."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.models import Account
from app.services import pictures


def png(seed: int = 0, size: int = 200) -> bytes:
    image = Image.effect_noise((size, size), 40 + seed).convert("RGB")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_pictures_are_unpacked_one_at_a_time_by_default_and_never_larger_than_36_mp() -> None:
    assert get_settings().decode_slots == 1 and pictures.slots() == 1
    assert pictures.MAX_PIXELS <= 36_000_000


def test_when_every_place_is_taken_an_upload_is_turned_away_before_its_body_is_read(
        client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pictures, "WAITING", 0)
    read: list[int] = []
    original = pictures.read_body

    async def counting(request: object) -> bytes:
        read.append(1)
        return await original(request)

    monkeypatch.setattr(pictures, "read_body", counting)
    with pictures.admitted():
        busy = client.put("/api/v1/auth/avatar", content=png(9))
        assert busy.status_code == 503 and busy.json()["detail"]["code"] == "busy"
        assert busy.headers["retry-after"] == "5"
    assert read == []
    assert client.put("/api/v1/auth/avatar", content=png(8)).status_code == 200 and read == [1]
