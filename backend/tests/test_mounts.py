"""Where the data folder lies: a network share is found from the mount table or the drive type, and said in the log at
the start. The machine is stood in for by a table and a drive type given by the test."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.services import mounts

TABLE = r"""overlay / overlay rw,relatime 0 0
proc /proc proc rw,nosuid 0 0
/dev/sda1 /data ext4 rw,relatime 0 0
nas.example.com:/volume1/paper /data/dokumente nfs4 rw,vers=4.1 0 0
//nas.example.com/paper /mnt/with\040space cifs rw,vers=3.0 0 0
/dev/sdb1 /mnt/with\040space/local ext4 rw 0 0
"""


@pytest.mark.parametrize(("path", "kind", "fstype"), [
    ("/data", "local", "ext4"),
    ("/data/nexpaper.db", "local", "ext4"),
    ("/data/dokumente", "network", "nfs4"),
    ("/data/dokumente/Haushalt/2026/x.pdf", "network", "nfs4"),
    # A mount point is a whole name, not a prefix: /data2 is not under /data.
    ("/data2/x", "local", "overlay"),
    ("/mnt/with space/x", "network", "cifs"),
    # A nested mount wins over the one around it.
    ("/mnt/with space/local/x", "local", "ext4"),
    ("/elsewhere", "local", "overlay"),
])
def test_the_mount_that_holds_a_path_decides(path: str, kind: str, fstype: str) -> None:
    found = mounts.in_table(path, TABLE)
    assert (found.kind, found.fstype) == (kind, fstype)
    assert found.network is (kind == "network")


@pytest.mark.parametrize("fstype", ["nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "NFS4"])
def test_every_network_file_system_is_one(fstype: str) -> None:
    assert mounts.in_table("/data", f"x:/y /data {fstype} rw 0 0\n").network


@pytest.mark.parametrize("fstype", ["ext4", "xfs", "btrfs", "zfs", "tmpfs", "overlay", "fuseblk", "fuse.mergerfs"])
def test_a_local_file_system_is_none(fstype: str) -> None:
    assert not mounts.in_table("/data", f"x /data {fstype} rw 0 0\n").network


def test_a_table_that_says_nothing_is_unknown_and_never_a_guess() -> None:
    assert mounts.in_table("/data", "").kind == "unknown"
    assert mounts.in_table("/data", "garbage\nmore garbage\n").kind == "unknown"
    assert not mounts.in_table("/data", "").network


def test_the_mount_table_is_asked_when_none_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    table = tmp_path / "mounts"
    table.write_text("nas:/x /srv/paper nfs rw 0 0\n", encoding="utf-8")
    monkeypatch.setattr(mounts, "MOUNT_TABLE", table)
    # The machine may be a Windows one: the path is the Linux one the table talks about.
    monkeypatch.setattr(mounts, "_resolve", lambda path: "/srv/paper/data")
    assert mounts.locate(tmp_path / "data", windows=False).network
    monkeypatch.setattr(mounts, "MOUNT_TABLE", tmp_path / "nothing-here")
    assert mounts.locate(tmp_path, windows=False).kind == "unknown"


@pytest.mark.parametrize(("path", "drive", "kind"), [
    (r"\\nas\paper\data", None, "network"),
    (r"\\?\UNC\nas\paper\data", None, "network"),
    (r"Z:\data", mounts.DRIVE_REMOTE, "network"),
    (r"C:\data", 3, "local"),
    (r"C:\data", None, "unknown"),
])
def test_windows_tells_a_share_by_its_path_or_its_drive(path: str, drive: int | None, kind: str) -> None:
    assert mounts.on_windows(path, drive).kind == kind


def test_the_start_warns_once_when_the_database_lies_on_a_share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(mounts, "locate", lambda path, **_kw: mounts.Where("network", "nfs4"))
    with caplog.at_level(logging.WARNING, logger="nexpaper.mounts"):
        where = mounts.warn_at_start(tmp_path, tmp_path / "nexpaper.db")
    assert where.network
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1 and "network share" in warnings[0].getMessage()
    assert "nfs4" in warnings[0].getMessage()


def test_the_start_says_nothing_for_a_local_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                 caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(mounts, "locate", lambda path, **_kw: mounts.Where("local", "ext4"))
    with caplog.at_level(logging.INFO, logger="nexpaper.mounts"):
        mounts.warn_at_start(tmp_path, tmp_path / "nexpaper.db")
    assert not caplog.records
