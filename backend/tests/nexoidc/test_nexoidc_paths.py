"""Contract, the addresses: ``Secure`` behind HTTPS, the blueprint's callback entered by hand, old callbacks per
entry; an entry with a ``managed`` value the module no longer writes."""

from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

import oidc_fakes as fakes
from oidc_contract import (
    add_in_store,
    entry,
    form_of,
    link_person,
    location,
    oidc_package,
    round_trip,
    start,
)


def _cookies(response: Any) -> SimpleCookie:
    cookies = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    return cookies


def test_behind_https_the_attempt_cookie_is_secure(
    adapter: Any, oidc: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    name = oidc.current().cookie_name
    plain = _cookies(start(adapter, adapter.browser(), "sso"))[name]
    assert not plain["secure"]
    adapter.set_public_url("https://app.example.com")
    response = start(adapter, adapter.browser(), "sso")
    assert fakes.query_of(location(response))["redirect_uri"].startswith("https://app.example.com/")
    assert _cookies(response)[name]["secure"]


def test_the_blueprints_callback_entered_by_hand_signs_in_and_the_button_takes_the_entry_later(
    adapter: Any, oidc: Any, net: fakes.Network
) -> None:
    ak = net.add(fakes.FakeAuthentik())
    # The blueprint names a redirect address behind the public address only (1.0.10).
    adapter.set_public_url(adapter.origin)
    blueprint = adapter.blueprint()
    assert blueprint.status_code == 200
    app = oidc.current().app_name
    callback = f"/{adapter.api.strip('/')}/oidc/authentik/callback"
    assert callback in blueprint.text
    # As if the operator applied the blueprint: provider and application with the plain names.
    made = ak.add_provider(app, adapter.origin + callback, slug=app)
    issuer = f"{ak.base}/application/o/{app}/"
    signer = ak.sign_in_with(issuer, made["client_id"], made["client_secret"])
    if adapter.only_authentik:
        saved = add_in_store(adapter, signer, "authentik", label="authentik", issuer=issuer)
    else:
        response = adapter.add_provider(signer, slug="authentik", label="authentik", issuer=issuer)
        assert response.status_code in (200, 201), response.text
        saved = response.json()
        assert saved["redirect_uri"].endswith(callback)
    adapter.make_account("alex")
    link_person(adapter, "alex", "authentik", signer)
    browser, response = round_trip(adapter, signer, "authentik")
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    result = adapter.setup_authentik(ak.base, ak.token).json()
    assert result["ok"] and result["links_dropped"] == 0 and result["provider_id"] == saved["id"]
    item = entry(adapter, "authentik")
    assert item["managed"] == "authentik" and len(ak.providers) == 1
    assert ak.providers[0]["redirect_uris"][0]["url"].endswith(callback)
    assert adapter.who(round_trip(adapter, signer, "authentik")[0]) == "alex"


def test_an_entry_with_an_old_callback_signs_in_there(adapter: Any, oidc: Any, sso: fakes.FakeProvider) -> None:
    standard = add_in_store(adapter, sso, "plain")
    with adapter.store() as store:
        assert store.get_provider(standard["id"]).redirect_path == ""
    target = location(start(adapter, adapter.browser(), "plain"))
    assert fakes.query_of(target)["redirect_uri"].endswith(adapter.path("callback", slug="plain"))
    for number, template in enumerate(adapter.old_callback_paths):
        slug = f"old{number}"
        old = oidc.migrate.old_callback(template, slug)
        other = fakes.FakeProvider(f"https://old{number}.example.com")
        _network(adapter).add(other)
        made = add_in_store(adapter, other, slug)
        with adapter.store() as store:
            row = store.get_provider(made["id"])
            store.update_provider(row.id, oidc.providers.values_of(row, redirect_path=old))
            store.commit()
        assert entry(adapter, slug)["redirect_uri"].endswith(old)
        adapter.make_account(f"person{number}")
        link_person(adapter, f"person{number}", slug, other)
        browser, response = round_trip(adapter, other, slug)
        assert location(response) == adapter.home and adapter.who(browser) == f"person{number}"


def test_an_entry_with_a_managed_value_the_module_no_longer_writes_counts_as_one_by_hand(
    adapter: Any, oidc: Any, net: fakes.Network
) -> None:
    """An older installation may hold a ``managed`` value the module no longer writes (an entry of a coupling that was
    given up). Nothing breaks on it: the entry is read as one by hand, listed and editable, it signs in, it is saved
    with its value untouched, and it can be removed."""
    older = net.add(fakes.FakeProvider("https://older.example.com"))
    made = add_in_store(adapter, older, "older", label="Older", managed="nexsuite")
    item = entry(adapter, "older")
    assert item["editable"] and item["enabled"] and item["managed"] == "nexsuite"
    public = adapter.browser().get(adapter.path("public")).json()
    assert {"slug": "older", "label": "Older"} in public
    adapter.make_account("alex")
    link_person(adapter, "alex", "older", older)
    browser, response = round_trip(adapter, older, "older")
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    saved = adapter.save_provider(made["id"], form_of(item, label="Older, renamed"))
    assert saved.status_code == 200, saved.text
    with adapter.store() as store:
        row = store.get_provider(made["id"])
        assert (row.label, row.managed) == ("Older, renamed", "nexsuite") and oidc.by_hand(row.managed)
    assert adapter.remove_provider(made["id"]).status_code in (200, 204)
    assert all(item["slug"] != "older" for item in adapter.providers())


def _network(adapter: Any) -> fakes.Network:
    return oidc_package(adapter).config.transport().handler  # type: ignore[union-attr]
