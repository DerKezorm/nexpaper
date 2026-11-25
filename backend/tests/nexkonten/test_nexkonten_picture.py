"""A provider's picture reaches an account without any picture through the app's store, never one with its own."""

from __future__ import annotations

import base64
from typing import Any

import httpx
from konten_contract import password, png

ISSUER = "https://sso.example.com/application/o/app"


def _serve(konten: Any, body: bytes) -> list[str]:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=body, headers={"content-type": "image/png"})

    konten.use_transport(httpx.MockTransport(answer))
    return asked


def test_an_account_without_a_picture_takes_the_providers(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=None)
    asked = _serve(konten, png(32, 32))
    with app.store() as store:
        assert konten.pictures.take_provider_picture(store, alex, "https://sso.example.com/media/a.png", ISSUER)
    assert asked == ["https://sso.example.com/media/a.png"]
    with app.store() as store:
        assert store.get_account(alex).picture == konten.PICTURE_PROVIDER


def test_a_picture_of_its_own_is_never_replaced_and_not_even_fetched(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password(), picture=True)
    asked = _serve(konten, png())
    with app.store() as store:
        assert not konten.pictures.take_provider_picture(store, alex, "https://sso.example.com/a.png", ISSUER)
        assert store.get_account(alex).picture == konten.PICTURE_OWN
    assert asked == []


def test_a_picture_that_does_not_pass_leaves_the_account_without_one(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=None)
    asked = _serve(konten, b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    with app.store() as store:
        assert not konten.pictures.take_provider_picture(store, alex, "https://sso.example.com/a.svg", ISSUER)
        assert not konten.pictures.take_provider_picture(store, alex, "https://elsewhere.example.org/a.png", ISSUER)
        assert store.get_account(alex).picture == konten.PICTURE_NONE
    assert asked == ["https://sso.example.com/a.svg"]


def test_a_picture_as_a_data_address_is_taken(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=None)
    url = "data:image/png;base64," + base64.b64encode(png()).decode("ascii")
    with app.store() as store:
        assert konten.pictures.take_provider_picture(store, alex, url, ISSUER)
        assert store.get_account(alex).picture == konten.PICTURE_PROVIDER
