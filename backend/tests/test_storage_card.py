"""The storage card: sizes of what the data folder holds, where the database lies, the free room."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import Account
from app.services import backups, mounts, pages, space, storage

from .conftest import make_account, new_client
from .papers import PDF, add_document, own_vault


@pytest.fixture(autouse=True)
def fresh_counts() -> None:
    space.forget()


def test_the_card_counts_what_lies_in_each_folder(client: TestClient, operator: Account) -> None:
    jule = make_account("jule")
    add_document(own_vault(jule), jule, "Rechnung", content=PDF)
    add_document(own_vault(jule), jule, "Mahnung", content=PDF + b"a second one")
    pages.cache_root().mkdir(parents=True, exist_ok=True)
    (pages.cache_root() / "a.webp").write_bytes(b"x" * 1000)
    backups.create(kind=backups.MANUAL)
    card = client.get("/api/v1/storage").json()
    on_disk = sum(path.stat().st_size for path in storage.root().rglob("*") if path.is_file())
    assert card["documents"]["bytes"] == on_disk and card["documents"]["files"] == 2
    assert card["documents"]["complete"] is True
    assert card["cache"]["bytes"] == 1000
    assert card["backups"]["bytes"] > 0 and card["exports"]["bytes"] == 0
    assert card["database"]["bytes"] >= get_settings().database_path.stat().st_size
    assert isinstance(card["database"]["index_bytes"], int) and card["database"]["index_bytes"] > 0
    assert card["free_bytes"] > 0 and card["total_bytes"] >= card["free_bytes"]
    assert card["files"]["running"] is False and card["files"]["last_finished_at"] is None


def test_a_database_on_a_network_share_is_said_so(client: TestClient, operator: Account,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    where = {"/db": mounts.Where("network", "nfs4")}
    monkeypatch.setattr(mounts, "locate", lambda path, **_kw: where.get("/db", mounts.Where("local", "ext4")))
    card = client.get("/api/v1/storage").json()
    assert card["database"]["where"] == {"kind": "network", "fstype": "nfs4", "network": True}
    assert card["data"]["where"]["network"] is True
    monkeypatch.setattr(mounts, "locate", lambda path, **_kw: mounts.Where("local", "ext4"))
    card = client.get("/api/v1/storage").json()
    assert card["database"]["where"]["network"] is False and card["documents"]["where"]["network"] is False


def test_documents_may_lie_on_a_share_while_the_database_does_not(client: TestClient, operator: Account,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    storage.root().mkdir(parents=True, exist_ok=True)

    def locate(path: Path, **_kw: Any) -> mounts.Where:
        return mounts.Where("network", "cifs") if Path(path).name == storage.FOLDER else mounts.Where("local", "ext4")

    monkeypatch.setattr(mounts, "locate", locate)
    card = client.get("/api/v1/storage").json()
    assert card["documents"]["where"]["network"] is True and card["database"]["where"]["network"] is False


def test_a_count_is_kept_for_a_while_and_a_slow_one_says_it_did_not_finish(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    jule = make_account("jule")
    add_document(own_vault(jule), jule, "Rechnung", content=PDF)
    calls = []
    real = space.count_folder

    def counting(path: Path, **kwargs: Any) -> tuple[int, int, bool]:
        calls.append(path)
        return real(path, **kwargs)

    monkeypatch.setattr(space, "count_folder", counting)
    space.folder_size(storage.root(), now=1000.0)
    space.folder_size(storage.root(), now=1000.0 + 299)
    assert len(calls) == 1
    space.folder_size(storage.root(), now=1000.0 + 301)
    assert len(calls) == 2
    assert space.count_folder(storage.root(), limit_seconds=-1.0)[2] is False


def test_a_link_in_a_folder_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 5000)
    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "small.bin").write_bytes(b"y" * 10)
    try:
        (inside / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows without the right to make symbolic links: a junction does the same without it.
        import subprocess

        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(inside / "link"), str(outside)], capture_output=True,
                              check=False) if os.name == "nt" else None
        if made is None or made.returncode != 0:
            pytest.skip("neither symbolic links nor junctions are possible here")
    assert space.count_folder(inside) == (10, 1, True)


def test_the_card_is_for_the_operator_in_a_browser_only(client: TestClient, operator: Account) -> None:
    with new_client(make_account("tom")) as member:
        assert member.get("/api/v1/storage").status_code == 403
    with new_client() as stranger:
        assert stranger.get("/api/v1/storage").status_code == 401
