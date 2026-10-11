"""nexpaper around the shared sign-in module: what only nexpaper can get right (the contract tests in ``tests/nexoidc``
check the module's part in every app).

The migration from 1.0.1's single provider (the operator's link survives, a backup first, the switch of 1.0.1 decides
whether the entry trusts the provider with the second factor), vaults per person (an identity with someone's address
never reaches their vault), the mail intake (an address from a provider is never one the person confirmed), the token
ways (pairing after a sign-in through a provider, nothing of the providers reachable with a device token), the stages
after the return (code, set-up, the mark on the session), the proxy's scheme, the brake, and the routes of the
authentik card beside an entry called ``authentik``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.middleware import ForwardedProtoMiddleware, forwarded_proto
from app.models import SIGN_IN_OIDC, Account, AuthSession, OidcLink, OidcProvider, Vault
from app.security import brake, encrypt_secret, hash_password, start_session
from app.services import backups, landing, mail_senders, oidc_store, settings_service, totp

from .conftest import PASSWORD, make_account, require_second_factor, sign_in
from .oidc_helpers import (
    FakeProvider,
    add_provider,
    come_back,
    configure,
    error_in,
    fresh_browser,
    link,
    location,
    sign_in_via_oidc,
    start,
)
from .papers import add_document, own_vault

#: A request of the phone app to be paired (OAuth 2 with PKCE), the page the sign-in through the provider started from.
ASKED = ("/oauth/authorize?response_type=code&client_id=nexpaper-mobile&redirect_uri=nexpaper%3A%2F%2Foauth%2Fcallback"
         "&code_challenge=" + "c" * 43 + "&code_challenge_method=S256&state=xyz")


def legacy(fake: FakeProvider, *, label: str = "authentik", switch: bool = False, auto_create: bool = False,
           **subjects: str) -> None:
    """nexpaper 1.0.1's single provider in the settings and the subjects at the accounts, as it stored them: a database
    of 1.0.1 (the start of the test client wrote the marks of 1.1.0 already; 1.0.1 never had them)."""
    from app.models import Setting

    with SessionLocal() as db:
        db.query(Setting).filter(Setting.key.in_([
            oidc_store.MIGRATED, oidc_store.FINGERPRINT, oidc_store.ANCHOR, oidc_store.WRITTEN_SECOND_FACTOR,
        ])).delete(synchronize_session=False)
        db.commit()
    with SessionLocal() as db:
        settings_service.save(db, {
            "oidc_issuer": fake.issuer, "oidc_client_id": fake.client_id,
            "oidc_client_secret_enc": encrypt_secret(fake.client_secret), "oidc_provider_name": label,
            "oidc_auto_create": auto_create, "oidc_second_factor_by_provider": switch,
        })
        for name, subject in subjects.items():
            row = db.scalar(select(Account).where(Account.name == name))
            assert row is not None
            row.oidc_subject = subject
        db.commit()


def entry(slug: str = "oidc") -> OidcProvider | None:
    with SessionLocal() as db:
        row = db.scalar(select(OidcProvider).where(OidcProvider.slug == slug))
        if row is not None:
            db.expunge(row)
        return row


def links() -> dict[str, str]:
    with SessionLocal() as db:
        rows = db.execute(select(Account.name, OidcLink.subject).join(OidcLink, OidcLink.account_id == Account.id))
        return {name: subject for name, subject in rows}


def who(browser: TestClient) -> str | None:
    answer = browser.get("/api/v1/auth/me")
    return answer.json()["name"] if answer.status_code == 200 and answer.json()["session_stage"] == "full" else None


# --- The migration from 1.0.1 -----------------------------------------------------------------------------------------


def test_the_operators_link_of_1_0_1_survives_the_migration_after_a_backup_and_signs_in_at_the_old_address(
    client: TestClient, operator: Account, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[str] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made.append(kwargs.get("note", "")))
    legacy(provider, label="authentik", auto_create=True, tester="person-1")
    oidc_store.migrate_settings()
    assert made == ["before the sign-in provider list"]
    found = entry()
    assert found is not None and (found.label, found.auto_create, found.enabled) == ("authentik", True, True)
    assert found.issuer == provider.issuer.rstrip("/") and found.redirect_path == ""
    assert links() == {"tester": "person-1"}
    # The provider knows only the address of 1.0.1: the sign-in there goes on, as the operator.
    browser = fresh_browser()
    target = location(start(browser, slug="oidc"))
    assert parse_qs(urlsplit(target).query)["redirect_uri"] == ["http://testserver/api/v1/oidc/callback"]
    assert location(come_back(browser, provider, target)) == "/"
    assert who(browser) == "tester"
    # A second start migrates nothing again and makes no backup.
    oidc_store.migrate_settings()
    assert made == ["before the sign-in provider list"]


@pytest.mark.parametrize("switch", [False, True])
def test_the_switch_of_1_0_1_decides_whether_the_migrated_entry_trusts_the_provider_with_the_second_factor(
    client: TestClient, operator: Account, provider: FakeProvider, switch: bool
) -> None:
    legacy(provider, switch=switch, tester="person-1")
    oidc_store.migrate_settings(backup=False)
    found = entry()
    assert found is not None and found.trusts_second_factor is switch
    # The operator with a second factor of nexpaper's own: asked for its code after the provider exactly when the
    # switch was off, as 1.0.1 did.
    secret = totp.generate_seed()
    with SessionLocal() as db:
        db.query(Account).filter(Account.name == "tester").update({"totp_secret_enc": totp.seal_seed(secret)})
        db.commit()
    browser = fresh_browser()
    answer = come_back(browser, provider, location(start(browser, slug="oidc")))
    assert location(answer).startswith("/login?step=code") is (not switch)
    assert (who(browser) == "tester") is switch


def test_a_new_entry_trusts_the_provider_from_the_start(client: TestClient, operator: Account,
                                                         provider: FakeProvider) -> None:
    assert configure(client, provider)["trusts_second_factor"] is True


def test_an_address_1_0_1_took_as_confirmed_from_the_provider_waits_for_its_owner_after_the_migration(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    with SessionLocal() as db:
        from app.models import utcnow

        db.add(Account(name="sam", sign_in=SIGN_IN_OIDC, oidc_subject="person-9", email="sam@example.com",
                       email_confirmed_at=utcnow(), email_from_provider=True))
        db.add(Account(name="kim", password_hash=hash_password(PASSWORD), email="kim@example.com",
                       email_confirmed_at=utcnow()))
        db.commit()
    legacy(provider)
    oidc_store.migrate_settings(backup=False)
    with SessionLocal() as db:
        sam = db.scalar(select(Account).where(Account.name == "sam"))
        kim = db.scalar(select(Account).where(Account.name == "kim"))
        assert sam is not None and kim is not None
        # The provider's word is not sam's: the address stays and waits for the link that confirms it.
        assert sam.email == "sam@example.com" and sam.email_confirmed_at is None
        # One the person confirmed by a link stays confirmed.
        assert kim.email_confirmed_at is not None
        assert mail_senders.owners(db, "sam@example.com") == set()
        assert mail_senders.owners(db, "kim@example.com") == {kim.id}


def test_without_a_provider_in_1_0_1_nothing_is_made_but_the_way_back_is_written(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[str] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made.append(kwargs.get("note", "")))
    oidc_store.migrate_settings()
    assert entry() is None and made == []
    with SessionLocal() as db:
        assert settings_service.get(db, oidc_store.MIGRATED) is True
        assert settings_service.get(db, oidc_store.FINGERPRINT)
        assert settings_service.get(db, oidc_store.ANCHOR) == "-"


# --- Vaults per person (Besonderheit 1) -------------------------------------------------------------------------------


@pytest.mark.parametrize("way", ["auto_create", "invitation", "invitation_to_the_address"])
def test_an_identity_with_the_address_of_an_account_never_comes_into_it_nor_into_its_vault(
    client: TestClient, operator: Account, provider: FakeProvider, way: str
) -> None:
    """nexpaper does not encrypt per person: a personal vault is kept apart by rights alone. So the one thing that must
    never happen is that a stranger at the provider becomes the account: not by the same address, confirmed by the
    provider or by the person, not with "new people get an account", not with an invitation sent to that address."""
    anna = make_account("anna")
    with SessionLocal() as db:
        from app.models import utcnow

        db.query(Account).filter(Account.id == anna.id).update(
            {"email": "anna@example.com", "email_confirmed_at": utcnow()})
        db.commit()
    secret_paper = add_document(own_vault(anna), anna, "Kontoauszug")
    configure(client, provider, auto_create=way == "auto_create")
    invite = None
    if way != "auto_create":
        answer = client.post("/api/v1/invites", json={
            "days": 7, "email": "anna@example.com" if way == "invitation_to_the_address" else "", "send": False})
        assert answer.status_code == 201, answer.text
        invite = answer.json()["link"].rsplit("/", 1)[1]
    browser = fresh_browser()
    answer = sign_in_via_oidc(browser, provider, invite=invite, sub="stranger-1", preferred_username="anna",
                              email="anna@example.com", email_verified=True)
    assert location(answer) == "/"
    newcomer = who(browser)
    assert newcomer is not None and newcomer != "anna"
    assert links() == {newcomer: "stranger-1"}
    # Its own empty vault, never anna's; anna's document is as if it were not there.
    vaults = browser.get("/api/v1/vaults").json()
    with SessionLocal() as db:
        mine = db.scalar(select(Vault.id).join(Account, Vault.personal_of == Account.id).where(Account.name == newcomer))
    assert [vault["id"] for vault in vaults] == [mine]
    assert vaults[0]["documents"] == 0
    assert browser.get(f"/api/v1/documents/{secret_paper}").status_code == 404
    with SessionLocal() as db:
        row = db.scalar(select(Account).where(Account.name == "anna"))
        assert row is not None and row.email == "anna@example.com"
        # Not even a copy of it: an invitation made for an address another account has gives the newcomer none.
        stranger = db.scalar(select(Account).where(Account.name == newcomer))
        assert stranger is not None and stranger.email.lower() != "anna@example.com"
        assert db.query(Account).filter(func.lower(Account.email) == "anna@example.com").count() == 1


def test_a_known_identity_through_an_invitation_keeps_the_address_it_has(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    """An invitation brings its address on top, never instead: an account that has one keeps it."""
    configure(client, provider, auto_create=True)
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider, sub="person-8", preferred_username="lea",
                                     email="lea@example.com")) == "/"
    with SessionLocal() as db:
        from app.models import utcnow

        db.query(Account).filter(Account.name == "lea").update(
            {"email": "lea@home.example.com", "email_confirmed_at": utcnow(), "email_from_provider": False})
        db.commit()
    answer = client.post("/api/v1/invites", json={"days": 7, "email": "invited@example.com", "send": False})
    assert answer.status_code == 201, answer.text
    invite = answer.json()["link"].rsplit("/", 1)[1]
    again = fresh_browser()
    assert location(sign_in_via_oidc(again, provider, invite=invite, sub="person-8", preferred_username="lea",
                                     email="lea@example.com")) == "/"
    assert who(again) == "lea"
    with SessionLocal() as db:
        row = db.scalar(select(Account).where(Account.name == "lea"))
        assert row is not None and row.email == "lea@home.example.com" and row.email_confirmed_at is not None


# --- The mail intake (Besonderheit 2) ---------------------------------------------------------------------------------


def test_an_address_from_a_provider_never_decides_whose_vault_a_mail_reaches(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    """The intake gives a mail to the account whose confirmed address sent it. An address only a provider names (even
    with ``email_verified``) is not confirmed: a new account through the provider, and a password account that takes
    the provider's address on its page, both wait for the link that confirms it."""
    configure(client, provider, auto_create=True)
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider, sub="person-5", preferred_username="lea",
                                     email="lea@example.com", email_verified=True)) == "/"
    me = browser.get("/api/v1/auth/me").json()
    assert me["email"] == "lea@example.com" and me["email_confirmed"] is False
    with SessionLocal() as db:
        assert mail_senders.owners(db, "lea@example.com") == set()
    # A password account takes the address its provider knows: its address now, still unconfirmed.
    tom = make_account("tom")
    member = fresh_browser()
    sign_in(member, tom)
    assert error_in(link(member, provider, PASSWORD, sub="person-6", email="tom@example.com",
                         email_verified=True)) is None
    offered = member.get("/api/v1/oidc/me").json()
    assert offered == [{"slug": "sso", "label": "SSO", "linked": True, "address": "tom@example.com"}]
    taken = member.post("/api/v1/oidc/me/address", json={"slug": "sso"})
    assert taken.status_code == 200 and taken.json() == {"email": "tom@example.com", "email_confirmed": False}
    with SessionLocal() as db:
        assert mail_senders.owners(db, "tom@example.com") == set()


def test_taking_the_address_of_a_provider_needs_a_link_to_it(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider)
    member = fresh_browser()
    sign_in(member, make_account("anna"))
    for slug in ("sso", "nowhere"):
        answer = member.post("/api/v1/oidc/me/address", json={"slug": slug})
        assert answer.status_code == 404, (slug, answer.text)
    with SessionLocal() as db:
        row = db.scalar(select(Account).where(Account.name == "anna"))
        assert row is not None and row.email == ""


def test_an_address_the_person_confirmed_is_never_replaced_by_the_providers(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider, auto_create=True)
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider, sub="person-5", preferred_username="lea",
                                     email="lea@example.com")) == "/"
    with SessionLocal() as db:
        from app.models import utcnow

        db.query(Account).filter(Account.name == "lea").update(
            {"email": "lea@home.example.com", "email_confirmed_at": utcnow(), "email_from_provider": False})
        db.commit()
    again = fresh_browser()
    assert location(sign_in_via_oidc(again, provider, sub="person-5", preferred_username="lea",
                                     email="lea@example.com")) == "/"
    with SessionLocal() as db:
        row = db.scalar(select(Account).where(Account.name == "lea"))
        assert row is not None and row.email == "lea@home.example.com" and row.email_confirmed_at is not None


# --- Token ways (Besonderheit 3) --------------------------------------------------------------------------------------


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def test_pairing_an_app_after_a_sign_in_through_the_provider_comes_back_to_its_request_and_gives_a_device_token(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider)
    with SessionLocal() as db:
        db.query(Account).filter(Account.name == "tester").update({"oidc_subject": ""})
        tester = db.scalar(select(Account).where(Account.name == "tester"))
        assert tester is not None
        db.add(OidcLink(provider_id=entry("sso").id, subject="person-1", account_id=tester.id,  # type: ignore[union-attr]
                        issuer=provider.issuer))
        db.commit()
    verifier, challenge = _pkce()
    asked = ASKED.replace("c" * 43, challenge)
    browser = fresh_browser()
    answer = sign_in_via_oidc(browser, provider, next_page=asked)
    assert location(answer) == asked and who(browser) == "tester"
    # The page of the request allows it: the app trades its code and verifier for a device token.
    allowed = browser.post("/api/v1/oauth/authorize", json={
        "client_id": "nexpaper-mobile", "redirect_uri": "nexpaper://oauth/callback", "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "device_name": "Pixel"})
    assert allowed.status_code == 200, allowed.text
    code = parse_qs(urlsplit(allowed.json()["redirect"]).query)["code"][0]
    with TestClient(browser.app, base_url="http://testserver") as app_side:
        traded = app_side.post("/api/v1/oauth/token", data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": "nexpaper://oauth/callback",
            "client_id": "nexpaper-mobile", "code_verifier": verifier})
        assert traded.status_code == 200, traded.text
        token = traded.json()["access_token"]
        assert token.startswith("npd_")
        bearer = {"Authorization": f"Bearer {token}"}
        assert app_side.get("/api/v1/auth/me", headers=bearer).json()["name"] == "tester"
        # Linking, unlinking and everything of the operator's list stay with a browser the person sits at.
        for method, path in (("GET", "/api/v1/oidc/me"), ("POST", "/api/v1/oidc/sso/link"),
                             ("DELETE", "/api/v1/oidc/sso/link"), ("POST", "/api/v1/oidc/me/address"),
                             ("GET", "/api/v1/oidc/admin/providers"), ("POST", "/api/v1/oidc/authentik/setup")):
            refused = app_side.request(method, path, headers=bearer, json={})
            assert refused.status_code == 403 and refused.json()["detail"]["code"] == "browser_only", path


def test_a_sign_in_through_the_provider_keeps_its_page_through_the_code_and_the_set_up(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider, trusts_second_factor=False)
    anna = make_account("anna")
    member = fresh_browser()
    sign_in(member, anna)
    assert error_in(link(member, provider, PASSWORD, sub="person-7")) is None
    # A password account through a provider that does not check the second factor, one required: set it up first, then
    # on to the page.
    require_second_factor()
    browser = fresh_browser()
    first = location(sign_in_via_oidc(browser, provider, sub="person-7", next_page=ASKED))
    assert first.startswith("/login?") and parse_qs(urlsplit(first).query)["next"] == [ASKED]
    assert browser.get("/api/v1/auth/me").json()["session_stage"] == "setup"
    # The same account with a code of its own: asked after the provider (not trusted), the page goes along.
    secret = totp.generate_seed()
    with SessionLocal() as db:
        db.query(Account).filter(Account.name == "anna").update({"totp_secret_enc": totp.seal_seed(secret)})
        db.commit()
    again = fresh_browser()
    second = location(sign_in_via_oidc(again, provider, sub="person-7", next_page=ASKED))
    assert second == "/login?step=code&next=" + quote(ASKED, safe="")
    done = again.post("/api/v1/auth/login/totp", json={"code": totp.code_at(secret, time.time())})
    assert done.status_code == 200 and who(again) == "anna"


@pytest.mark.parametrize("hostile", [
    "//evil.example.org/x", "https://evil.example.org/", "/\\evil.example.org", "javascript:alert(1)",
    "/\t/evil.example.org", "/ok\r\nSet-Cookie: x=1", "/a b", "evil", "/" + "a" * 1200, "/\u0085x",
])
def test_anything_but_a_path_of_nexpaper_ends_on_the_start_page(
    client: TestClient, operator: Account, provider: FakeProvider, hostile: str
) -> None:
    configure(client, provider, auto_create=True)
    browser = fresh_browser()
    answer = start(browser, next_page=hostile)
    assert landing.COOKIE + "=" not in "".join(
        line for line in answer.headers.get_list("set-cookie") if "max-age=0" not in line.lower())
    assert location(come_back(browser, provider, location(answer))) == "/"


def test_a_page_cookie_nexpaper_did_not_sign_counts_for_nothing(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider, auto_create=True)
    browser = fresh_browser()
    target = location(start(browser))
    # A page of nexpaper's own, but signed by somebody else: no landing at all.
    forged = base64.urlsafe_b64encode(b"/schnell").decode().rstrip("=") + ".c2lnbmF0dXJl"
    browser.cookies.set(landing.COOKIE, forged, path="/api/v1/oidc")
    assert location(come_back(browser, provider, target)) == "/"
    assert landing.read(landing.pack("/schnell?x=1")) == "/schnell?x=1"
    assert landing.pack("//evil.example.org") is None


# --- The stages after the return (Besonderheit 4) ---------------------------------------------------------------------


def test_a_provider_that_checks_the_second_factor_spares_this_session_its_set_up_not_the_password_one(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    """Bauplan 01 (decided 10.10.2026): through an entry that trusts the provider, a password account without a second
    factor is not sent to set one up; its own sign-in with the password still is. Its device tokens and keys wait
    (they have no provider behind them), and the page says so."""
    configure(client, provider)
    anna = make_account("anna")
    member = fresh_browser()
    sign_in(member, anna)
    assert error_in(link(member, provider, PASSWORD, sub="person-7")) is None
    require_second_factor()
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider, sub="person-7")) == "/"
    me = browser.get("/api/v1/auth/me").json()
    assert me["session_stage"] == "full" and me["second_factor_setup_required"] is False
    assert me["keys_wait_for_second_factor"] is True
    assert browser.get("/api/v1/vaults").status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(AuthSession.second_factor_by_provider).where(
            AuthSession.account_id == anna.id).order_by(AuthSession.id.desc())).first() is True
    password = fresh_browser()
    answer = password.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    assert answer.status_code == 200 and answer.json()["session_stage"] == "setup"


def test_a_provider_that_does_not_check_the_second_factor_frees_no_password_account(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider, trusts_second_factor=False)
    anna = make_account("anna")
    member = fresh_browser()
    sign_in(member, anna)
    assert error_in(link(member, provider, PASSWORD, sub="person-7")) is None
    require_second_factor()
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider, sub="person-7")) == "/login"
    assert browser.get("/api/v1/auth/me").json()["session_stage"] == "setup"


def test_an_account_through_a_provider_only_is_not_forced_to_set_up_one(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider, auto_create=True, trusts_second_factor=False)
    require_second_factor()
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider)) == "/"
    me = browser.get("/api/v1/auth/me").json()
    assert (me["name"], me["session_stage"], me["second_factor_required"]) == ("alex", "full", False)
    assert me["keys_wait_for_second_factor"] is False


def test_a_blocked_account_does_not_come_in_through_its_provider(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider, auto_create=True)
    assert location(sign_in_via_oidc(fresh_browser(), provider)) == "/"
    with SessionLocal() as db:
        from app.models import utcnow

        db.query(Account).filter(Account.name == "alex").update({"blocked_at": utcnow()})
        db.commit()
    browser = fresh_browser()
    assert error_in(sign_in_via_oidc(browser, provider)) == "account_blocked" and who(browser) is None


# --- The brake, the proxy, the routes ---------------------------------------------------------------------------------


def test_a_return_without_an_attempt_of_this_server_never_feeds_the_brake(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider)
    stranger = fresh_browser()
    for _ in range(brake.FREE * 3):
        for query in ("error=access_denied", "code=x&state=y", "garbage=1"):
            answer = stranger.get(f"/api/v1/oidc/sso/callback?{query}")
            assert error_in(answer) != "too_many_attempts"
        assert error_in(stranger.get("/api/v1/oidc/nobody/callback?code=x&state=y")) == "oidc_not_configured"
    # The household behind the same address still signs in.
    with SessionLocal() as db:
        tester = db.scalar(select(Account).where(Account.name == "tester"))
        assert tester is not None
        db.add(OidcLink(provider_id=entry("sso").id, subject="person-1", account_id=tester.id,  # type: ignore[union-attr]
                        issuer=provider.issuer))
        db.commit()
    assert location(sign_in_via_oidc(fresh_browser(), provider)) == "/"


def test_the_routes_of_the_authentik_card_and_an_entry_called_authentik_both_arrive(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider, slug="authentik", label="authentik", auto_create=True)
    browser = fresh_browser()
    target = location(start(browser, slug="authentik"))
    assert urlsplit(parse_qs(urlsplit(target).query)["redirect_uri"][0]).path == "/api/v1/oidc/authentik/callback"
    assert location(come_back(browser, provider, target)) == "/" and who(browser) == "alex"
    assert client.get("/api/v1/oidc/authentik/address").status_code == 200
    assert client.get("/api/v1/oidc/providers").json() == [{"slug": "authentik", "label": "authentik"}]


@pytest.mark.parametrize(("peer", "headers", "scheme"), [
    ("10.0.0.2", [(b"x-forwarded-proto", b"https")], "https"),
    # The rightmost value is the proxy's own; what a sender wrote left of it does not count.
    ("10.0.0.2", [(b"x-forwarded-proto", b"https, http")], "http"),
    ("10.0.0.2", [(b"x-forwarded-proto", b"http"), (b"x-forwarded-proto", b"HTTPS")], "https"),
    ("10.0.0.2", [(b"x-forwarded-proto", b"gopher")], "http"),
    # A sender that is no trusted proxy is not believed.
    ("203.0.113.9", [(b"x-forwarded-proto", b"https")], "http"),
])
def test_only_a_trusted_proxy_hands_on_the_scheme_its_rightmost_value(
    monkeypatch: pytest.MonkeyPatch, peer: str, headers: list[tuple[bytes, bytes]], scheme: str
) -> None:
    import asyncio

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "trusted_proxies", "10.0.0.0/8")
    seen: list[str] = []

    async def inner(scope: dict[str, Any], _receive: Any, _send: Any) -> None:
        seen.append(scope["scheme"])

    asyncio.run(ForwardedProtoMiddleware(inner)(
        {"type": "http", "scheme": "http", "client": (peer, 1234), "headers": headers}, None, None))
    assert seen == [scheme]
    assert forwarded_proto([(b"x-forwarded-proto", b"wss")], "websocket") == "wss"
    assert forwarded_proto([(b"x-forwarded-proto", b"https")], "websocket") is None


def test_without_trusted_proxies_nothing_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "trusted_proxies", "")
    seen: list[str] = []

    async def inner(scope: dict[str, Any], _receive: Any, _send: Any) -> None:
        seen.append(scope["scheme"])

    asyncio.run(ForwardedProtoMiddleware(inner)(
        {"type": "http", "scheme": "http", "client": ("127.0.0.1", 1), "headers": [(b"x-forwarded-proto", b"https")]},
        None, None))
    assert seen == ["http"]


# --- Card 1 and the account list --------------------------------------------------------------------------------------


def test_password_sign_in_goes_off_only_with_an_active_provider_and_the_sign_in_page_learns_the_buttons(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    refused = client.put("/api/v1/settings", json={"password_login": False})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "provider_first"
    made = configure(client, provider)
    second = FakeProvider("https://other.example.com")
    provider.network.add(second)  # type: ignore[attr-defined]
    add_provider(client, second, slug="other", label="Other")
    assert client.get("/api/v1/auth/methods").json()["providers"] == [
        {"slug": "sso", "label": "SSO"}, {"slug": "other", "label": "Other"}]
    assert client.put("/api/v1/settings", json={"password_login": False}).status_code == 200
    # Switched off, an entry has no button any more.
    body = {key: made[key] for key in ("label", "issuer", "client_id", "scopes", "auto_create", "trusts_second_factor")}
    assert client.put(f"/api/v1/oidc/admin/providers/{made['id']}", json={**body, "enabled": False}).status_code == 200
    assert client.get("/api/v1/auth/methods").json()["providers"] == [{"slug": "other", "label": "Other"}]
    # The page before the sign-in asks the same list: nobody sees an entry that is off.
    assert fresh_browser().get("/api/v1/oidc/providers").json() == [{"slug": "other", "label": "Other"}]


def test_emptying_the_public_address_asks_first_while_a_provider_by_hand_is_on(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    assert client.put("/api/v1/settings", json={"public_url": "https://paper.example.com"}).status_code == 200
    configure(client, provider)
    asked = client.put("/api/v1/settings", json={"public_url": ""})
    assert asked.status_code == 409 and asked.json()["detail"]["code"] == "public_url_change"
    assert asked.json()["detail"]["hand"] == 1
    with SessionLocal() as db:
        assert settings_service.public_url(db) == "https://paper.example.com"
    assert client.put("/api/v1/settings", json={"public_url": "", "confirm_address": True}).status_code == 200
    with SessionLocal() as db:
        assert settings_service.public_url(db) == ""


def test_the_operator_sees_who_is_linked_and_the_account_hears_when_the_operator_unlinks_it(
    client: TestClient, operator: Account, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import tell

    told: list[tuple[int, str]] = []
    monkeypatch.setattr(tell, "person", lambda account_id, notice: told.append((account_id, notice.tag)))
    configure(client, provider)
    anna = make_account("anna")
    member = fresh_browser()
    sign_in(member, anna)
    assert error_in(link(member, provider, PASSWORD, sub="person-7")) is None
    marks = client.get("/api/v1/oidc/admin/links").json()
    sso = entry("sso")
    assert sso is not None
    assert marks == [{"account_id": anna.id, "provider_id": sso.id, "slug": "sso", "label": "SSO"}]
    wrong = client.request("DELETE", f"/api/v1/oidc/admin/accounts/{anna.id}/links/{sso.id}",
                           json={"current_password": "not the password"})
    assert wrong.status_code == 401 and links() == {"anna": "person-7"}
    done = client.request("DELETE", f"/api/v1/oidc/admin/accounts/{anna.id}/links/{sso.id}",
                          json={"current_password": PASSWORD})
    assert done.status_code == 204 and links() == {}
    assert told == [(anna.id, "oidc-unlinked")]


def test_the_list_of_links_and_providers_is_the_operators_only(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    configure(client, provider)
    member = fresh_browser()
    sign_in(member, make_account("anna"))
    for path in ("/api/v1/oidc/admin/links", "/api/v1/oidc/admin/providers"):
        assert member.get(path).status_code == 403, path
        assert client.get(path).status_code == 200, path
    # Never with a device token either, not even the operator's own.
    paired = client.post("/api/v1/devices", json={"name": "phone"})
    assert paired.status_code == 201, paired.text
    device = TestClient(app, base_url="http://testserver")
    answer = device.get("/api/v1/oidc/admin/links", headers={"Authorization": "Bearer " + paired.json()["token"]})
    assert answer.status_code in (401, 403), answer.text


def test_the_session_of_1_0_1_and_an_account_made_without_the_new_column_get_their_default(
    client: TestClient, operator: Account
) -> None:
    """1.0.1 inserts sessions without naming ``second_factor_by_provider``: the database fills it in."""
    with SessionLocal() as db:
        db.connection().exec_driver_sql(
            "INSERT INTO auth_sessions (token_hash, account_id, created_at, expires_at, last_seen_at, ip, user_agent, "
            "uid, remember, stage) VALUES ('h-1', ?, '2026-10-11 08:00:00', '2026-10-12 08:00:00', "
            "'2026-10-11 08:00:00', '', '', 'u-1', 1, 'full')", (operator.id,))
        db.commit()
        row = db.scalar(select(AuthSession).where(AuthSession.token_hash == "h-1"))
        assert row is not None and row.second_factor_by_provider is False
    with SessionLocal() as db:
        token = start_session(db, db.get(Account, operator.id), "127.0.0.1", "tests")  # type: ignore[arg-type]
        assert token
