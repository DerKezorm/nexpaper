"""Profile pictures through the app's store: drawn anew as a square WebP, seen by every signed-in account and nobody
else, cached by version and ETag; what is no picture is refused; a picture of the older version stays."""

from __future__ import annotations

import io
from typing import Any

import pytest
from konten_contract import password, png
from PIL import Image


def _refused(konten: Any, call: Any, code: str) -> None:
    with pytest.raises(konten.AccountError) as caught:
        call()
    assert caught.value.code == code


def test_a_picture_is_kept_as_a_square_webp_and_every_signed_in_account_sees_it(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    with app.store() as store:
        at = konten.avatars.set_own(store, alex, png(600, 300))
        store.commit()
    with app.store() as store:
        data, stored_at = store.picture_of(alex)
        owner, viewer = store.get_account(alex), store.get_account(kim)
        assert owner.picture == konten.PICTURE_OWN
        assert konten.avatars.version(stored_at) == konten.avatars.version(at) != ""
        delivered = konten.avatars.deliver(store, viewer, owner)
        _refused(konten, lambda: konten.avatars.deliver(store, None, owner), "not_found")
        again = konten.avatars.deliver(store, viewer, owner, if_none_match=delivered.headers["ETag"])
    with Image.open(io.BytesIO(data)) as picture:
        assert (picture.format, picture.size) == ("WEBP", (256, 256))
    assert delivered.data == data and not delivered.not_modified
    assert delivered.headers["Content-Type"] == "image/webp" and "immutable" in delivered.headers["Cache-Control"]
    assert delivered.headers["X-Content-Type-Options"] == "nosniff"
    assert again.not_modified and again.data == b""


def test_the_picture_of_a_blocked_account_only_the_operator_sees(
    app: Any, konten: Any, operator: tuple[Any, str]
) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    boss, _ = operator
    gone = app.seed("gone", password=password(), blocked=True)
    kim = app.seed("kim", password=password())
    with app.store() as store:
        konten.avatars.set_own(store, gone, png())
        store.commit()
    with app.store() as store:
        owner = store.get_account(gone)
        _refused(konten, lambda: konten.avatars.deliver(store, store.get_account(kim), owner), "not_found")
        assert konten.avatars.deliver(store, store.get_account(boss), owner).data


def test_what_is_no_picture_or_too_large_is_refused_and_the_old_one_stays(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    with app.store() as store:
        konten.avatars.set_own(store, alex, png())
        store.commit()
        before = store.picture_of(alex)
        _refused(konten, lambda: konten.avatars.set_own(store, alex, b"%PDF-1.7 not a picture"), "avatar_not_a_picture")
        broken = png()[:40]
        _refused(konten, lambda: konten.avatars.set_own(store, alex, broken), "avatar_not_a_picture")
        large = png() + bytes(konten.avatars.MAX_BYTES)
        _refused(konten, lambda: konten.avatars.set_own(store, alex, large), "avatar_too_large")
        store.commit()
    with app.store() as store:
        assert store.picture_of(alex) == before


def test_a_removed_picture_is_gone(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    with app.store() as store:
        konten.avatars.set_own(store, alex, png())
        store.commit()
        konten.avatars.remove(store, alex)
        store.commit()
    with app.store() as store:
        assert store.picture_of(alex) is None and store.get_account(alex).picture == konten.PICTURE_NONE
        _refused(
            konten, lambda: konten.avatars.deliver(store, store.get_account(alex), store.get_account(alex)), "not_found"
        )


def test_a_picture_of_the_older_version_is_delivered_in_its_own_type(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password(), picture=True)
    with app.store() as store:
        found = store.picture_of(alex)
        assert found is not None
        delivered = konten.avatars.deliver(store, store.get_account(alex), store.get_account(alex))
    assert delivered.data == found[0] and delivered.headers["Content-Type"] == "image/png"
