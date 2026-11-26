"""The account functions of konten 1.1.0 in nexpaper: deleting with 30 days to bring back (the documents' handover
checked at the deletion and done when the account goes for good), several operators, the storage limit per account
at every upload through the browser and ``/api/v1``, "AI allowed", the theme at the account, the page Server, Sign-in
and "Ready for the internet?" in the module's form beside the old routes."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Document, Vault, VaultMember
from app.models_accounts import FormerName
from app.security import brake
from app.services import apikeys, totp
from app.services.konten_store import KontenStore
from app.services.post_store import PostStore
from app.vendor.nexkonten import manage

from .conftest import PASSWORD, make_account, new_client
from .oidc_helpers import FakeProvider, configure, fresh_browser, location, sign_in_via_oidc
from .papers import PDF, add_document, own_vault, shared_vault

#: A file of its own for an upload (the checksum must not match a document the account has).
FILE = PDF + b"%" + b"x" * 2000 + b"\n"


def delete(client: TestClient, account: Account, **body: object) -> object:
    payload = {"current_password": PASSWORD, "confirm_name": account.name, **body}
    return client.request("DELETE", f"/api/v1/accounts/{account.id}", json=payload)


def listed(client: TestClient, name: str) -> dict:
    return next(row for row in client.get("/api/v1/accounts").json() if row["name"] == name)


def age(account: Account, days: int) -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None and row.deleted_at is not None
        moved = row.deleted_at - timedelta(days=days)
        if row.blocked_at == row.deleted_at:
            row.blocked_at = moved
        row.deleted_at = moved
        db.commit()


def purge() -> list:
    with SessionLocal() as db:
        return manage.purge_due(KontenStore(db))


def can_sign_in(name: str) -> bool:
    brake.forget()
    with new_client() as browser:
        return browser.post("/api/v1/auth/login", json={"name": name, "password": PASSWORD}).status_code == 200


def test_a_deleted_account_waits_thirty_days_with_its_documents_and_comes_back(client: TestClient,
                                                                               operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    mine = own_vault(jule)
    kept = add_document(mine, jule, "Strom")
    assert delete(client, jule, documents="transfer_to_user", target_user_id=tom.id).status_code == 204  # type: ignore[attr-defined]
    row = listed(client, "jule")
    assert row["deleted_at"] is not None and row["purge_at"] is not None and row["blocked"] is False
    assert can_sign_in("jule") is False
    with SessionLocal() as db:
        # Nothing moved yet; 1.12.0, which does not know ``deleted_at``, sees the account blocked.
        assert db.scalar(select(Document.vault_id).where(Document.id == kept)) == mine
        stored = db.get(Account, jule.id)
        assert stored is not None and stored.blocked_at is not None and stored.blocked_at == stored.deleted_at
    # Again: nothing happens.
    assert delete(client, jule, documents="delete_documents").status_code == 204  # type: ignore[attr-defined]
    back = client.post(f"/api/v1/accounts/{jule.id}/restore", json={"current_password": PASSWORD})
    assert back.status_code == 200, back.text
    assert back.json()["deleted_at"] is None and back.json()["blocked"] is False
    assert can_sign_in("jule") is True
    with SessionLocal() as db:
        stored = db.get(Account, jule.id)
        assert stored is not None and stored.blocked_at is None and stored.leaving is None
    assert purge() == []


def test_blocked_before_the_deletion_it_comes_back_blocked(client: TestClient, operator: Account) -> None:
    lea = make_account("lea")
    assert client.post(f"/api/v1/accounts/{lea.id}/block", json={"current_password": PASSWORD}).status_code == 204
    assert delete(client, lea).status_code == 204  # type: ignore[attr-defined]
    assert listed(client, "lea")["blocked"] is True
    back = client.post(f"/api/v1/accounts/{lea.id}/restore", json={"current_password": PASSWORD}).json()
    assert back["deleted_at"] is None and back["blocked"] is True


def test_after_thirty_days_the_documents_go_where_the_operator_chose_and_the_name_stays_reserved(
        client: TestClient, operator: Account) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    kept = add_document(own_vault(jule), jule, "Strom")
    assert delete(client, jule, documents="transfer_to_user", target_user_id=tom.id).status_code == 204  # type: ignore[attr-defined]
    assert purge() == [], "the 30 days are not over"
    age(jule, manage.DELETE_DAYS + 1)
    refused = client.post(f"/api/v1/accounts/{jule.id}/restore", json={"current_password": PASSWORD})
    assert refused.status_code == 404
    assert purge() == [jule.id]
    with SessionLocal() as db:
        assert db.get(Account, jule.id) is None
        found = db.get(Document, kept)
        assert found is not None and found.vault_id == own_vault(tom) and found.owner_id == tom.id
        assert db.scalar(select(Vault.id).where(Vault.personal_of == jule.id)) is None
        assert db.scalar(select(FormerName.id).where(FormerName.name == "jule")) is not None
    assert [row["name"] for row in client.get("/api/v1/accounts").json()] == ["tester", "tom"]


def test_the_choice_is_checked_at_the_deletion_and_a_refusal_changes_nothing(client: TestClient,
                                                                            operator: Account) -> None:
    jule = make_account("jule")
    add_document(own_vault(jule), jule, "Strom")
    answer = delete(client, jule)
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "personal_vault_not_empty"  # type: ignore[attr-defined]
    stranger = delete(client, jule, documents="transfer_to_user", target_user_id=jule.id)
    assert stranger.status_code == 422 and stranger.json()["detail"]["code"] == "invalid_target"  # type: ignore[attr-defined]
    wrong = delete(client, jule, documents="delete_documents", confirm_name="julia")
    assert wrong.status_code == 422  # type: ignore[attr-defined]
    assert listed(client, "jule")["deleted_at"] is None and can_sign_in("jule")


def test_a_deleted_account_s_keys_rest_and_work_again_when_it_comes_back(client: TestClient,
                                                                        operator: Account) -> None:
    client.put("/api/v1/settings", json={"api_keys_allowed": True})
    jule = make_account("jule")
    with SessionLocal() as db:
        row = db.get(Account, jule.id)
        assert row is not None
        _key, token = apikeys.make(db, row, "script", "read")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    delete(client, jule)
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    client.post(f"/api/v1/accounts/{jule.id}/restore", json={"current_password": PASSWORD})
    apikeys.forget()
    assert client.get("/api/v1/me", headers=headers).status_code == 200


def test_a_deleted_account_keeps_its_places_in_shared_vaults_unseen_and_unchosen_until_it_goes(
        client: TestClient, operator: Account) -> None:
    """Bauplan E33: for 30 days a deleted account keeps its memberships, so that bringing it back makes it whole; until
    then nobody sees it in a vault's list, nobody chooses it, saving the list does not throw it out, it is no manager
    anybody can rely on, and no mail goes to it. At the end of the 30 days its places go with it."""
    tom, jule, kim = make_account("tom"), make_account("jule"), make_account("kim")
    with SessionLocal() as db:
        row = db.get(Account, jule.id)
        assert row is not None
        row.email, row.email_confirmed_at = "jule@example.com", row.created_at
        db.commit()
    vault = shared_vault("Haus", tom, (jule, "edit"), (kim, "manage"))
    path = f"/api/v1/vaults/{vault}"

    def members(browser: TestClient) -> dict[int, str]:
        return {entry["user_id"]: entry["right"] for entry in browser.get(path).json()["members"]}

    def mail_to(account: Account) -> object:
        with SessionLocal() as db:
            return PostStore(db).recipient(account.id)

    assert mail_to(jule) is not None
    assert delete(client, jule).status_code == 204  # type: ignore[attr-defined]
    assert delete(client, kim).status_code == 204  # type: ignore[attr-defined]
    with new_client(tom) as browser:
        assert members(browser) == {tom.id: "manage"}
        assert jule.id not in [entry["id"] for entry in browser.get("/api/v1/people").json()]
        # Saving the list the page shows keeps the ones it does not show.
        saved = browser.put(f"{path}/members", json={"members": [{"user_id": tom.id, "right": "manage"}]})
        assert saved.status_code == 200, saved.text
        # Nobody chooses, changes or removes a deleted account.
        for answer in (
            browser.put(f"{path}/members/{jule.id}", json={"right": "read"}),
            browser.delete(f"{path}/members/{jule.id}"),
            browser.put(f"{path}/members", json={"members": [{"user_id": tom.id, "right": "manage"},
                                                             {"user_id": jule.id, "right": "read"}]}),
        ):
            assert answer.status_code == 404
        # A deleted manager is none to rely on: tom stays the manager.
        down = browser.put(f"{path}/members/{tom.id}", json={"right": "edit"})
        assert down.status_code == 409 and down.json()["detail"]["code"] == "last_manager"
        assert browser.post(f"{path}/leave").status_code == 409
    with SessionLocal() as db:
        kept = dict(db.execute(select(VaultMember.user_id, VaultMember.right)
                               .where(VaultMember.vault_id == vault)).all())
    assert kept == {tom.id: "manage", jule.id: "edit", kim.id: "manage"}
    # The operator's dialog: tom is the only manager that stays, so tom's deletion is refused.
    assert delete(client, tom).json()["detail"]["code"] == "last_manager"  # type: ignore[attr-defined]
    assert mail_to(jule) is None
    assert client.post(f"/api/v1/accounts/{jule.id}/restore", json={"current_password": PASSWORD}).status_code == 200
    assert mail_to(jule) is not None
    with new_client(tom) as browser:
        assert members(browser) == {tom.id: "manage", jule.id: "edit"}
    age(kim, manage.DELETE_DAYS + 1)
    assert purge() == [kim.id]
    with SessionLocal() as db:
        assert db.get(VaultMember, (vault, kim.id)) is None
        assert db.get(VaultMember, (vault, jule.id)) is not None


def test_several_operators_and_never_the_own_account(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    made = client.put(f"/api/v1/accounts/{anna.id}/role", json={"role": "operator", "current_password": PASSWORD})
    assert made.status_code == 200 and made.json()["role"] == "operator"
    # Making oneself operator again changes nothing; taking it away is refused.
    assert client.put(f"/api/v1/accounts/{operator.id}/role",
                      json={"role": "operator", "current_password": PASSWORD}).status_code == 200
    own = client.put(f"/api/v1/accounts/{operator.id}/role", json={"role": "member", "current_password": PASSWORD})
    assert own.status_code == 409 and own.json()["detail"]["code"] == "cannot_demote_self"
    back = client.put(f"/api/v1/accounts/{anna.id}/role", json={"role": "member", "current_password": PASSWORD})
    assert back.json()["role"] == "member"
    wrong = client.put(f"/api/v1/accounts/{anna.id}/role", json={"role": "operator", "current_password": "nope"})
    assert wrong.status_code in (401, 403) and listed(client, "anna")["role"] == "member"


def test_ai_allowed_through_the_module_in_the_old_shape(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    assert listed(client, "anna")["rights"] == ["ai"]
    answer = client.put(f"/api/v1/accounts/{anna.id}/permissions", json={"ai_allowed": False})
    assert answer.status_code == 200 and answer.json() == {"ai_allowed": False}
    assert listed(client, "anna")["rights"] == []
    with SessionLocal() as db:
        assert db.get(Account, anna.id).ai_allowed is False  # type: ignore[union-attr]


def _upload(browser: TestClient, content: bytes = FILE) -> object:
    return browser.post("/api/v1/documents", files={"file": ("brief.pdf", content, "application/pdf")})


def test_the_storage_limit_refuses_uploads_past_it_and_keeps_what_is_there(client: TestClient,
                                                                          operator: Account) -> None:
    anna = make_account("anna")
    add_document(own_vault(anna), anna, "Strom")
    used = listed(client, "anna")["storage_used"]
    assert used > 0 and listed(client, "anna")["storage_limit"] is None
    set_limit = client.put(f"/api/v1/accounts/{anna.id}/storage-limit",
                           json={"limit": used + len(FILE) - 1, "current_password": PASSWORD})
    assert set_limit.status_code == 200 and set_limit.json()["storage_limit"] == used + len(FILE) - 1
    with new_client(anna) as browser:
        full = _upload(browser)
        assert full.status_code == 507  # type: ignore[attr-defined]
        assert full.json()["detail"]["code"] == "storage_limit_reached"  # type: ignore[attr-defined]
        # The big upload in pieces is refused when it is announced.
        announced = browser.post("/api/v1/uploads", json={"filename": "brief.pdf", "size": len(FILE),
                                                          "sha256": hashlib.sha256(FILE).hexdigest()})
        assert announced.status_code == 507 and announced.json()["detail"]["code"] == "storage_limit_reached"
        client.put(f"/api/v1/accounts/{anna.id}/storage-limit",
                   json={"limit": used + len(FILE), "current_password": PASSWORD})
        assert _upload(browser).status_code == 201  # type: ignore[attr-defined]
        client.put(f"/api/v1/accounts/{anna.id}/storage-limit", json={"limit": None, "current_password": PASSWORD})
        assert _upload(browser, FILE + b"more").status_code == 201  # type: ignore[attr-defined]
        assert browser.put(f"/api/v1/accounts/{anna.id}/storage-limit",
                           json={"limit": 1, "current_password": PASSWORD}).status_code == 403
    assert client.put(f"/api/v1/accounts/{anna.id}/storage-limit",
                      json={"limit": 5, "current_password": "nope"}).status_code in (401, 403)


def test_an_upload_key_meets_the_limit_too(client: TestClient, operator: Account) -> None:
    client.put("/api/v1/settings", json={"api_keys_allowed": True})
    client.put(f"/api/v1/accounts/{operator.id}/storage-limit", json={"limit": 10, "current_password": PASSWORD})
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        _key, token = apikeys.make(db, row, "scanner", "upload")
    with TestClient(client.app, base_url="http://testserver") as program:
        answer = program.post("/api/v1/documents", headers={"Authorization": f"Bearer {token}"},
                              files={"file": ("scan.pdf", FILE, "application/pdf")})
    assert answer.status_code == 507 and answer.json()["detail"]["code"] == "storage_limit_reached"


def test_the_theme_is_kept_at_the_account_beside_profile_mode(client: TestClient, operator: Account) -> None:
    me = client.get("/api/v1/auth/me").json()
    assert me["theme"] == "" and me["email_needs_proof"] is False
    assert client.post("/api/v1/me/theme/adopt", json={"theme": "dark"}).json() == {"theme": "dark"}
    assert client.post("/api/v1/me/theme/adopt", json={"theme": "light"}).json() == {"theme": "dark"}
    assert client.put("/api/v1/me/theme", json={"theme": "light"}).json() == {"theme": "light"}
    assert client.get("/api/v1/auth/me").json()["profile"]["mode"] == "light"
    refused = client.put("/api/v1/me/theme", json={"theme": "sepia"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "theme_invalid"
    assert client.put("/api/v1/me/preferences", json={"mode": "system"}).status_code == 200
    assert client.get("/api/v1/auth/me").json()["theme"] == "system"


def test_the_page_sign_in_with_the_module_s_rules(client: TestClient, operator: Account) -> None:
    view = client.get("/api/v1/server/sign-in").json()
    assert view["password_login"] is True and view["factor_required"] is False and view["passkeys_allowed"] is True
    assert view["factor_may_go_on"] is False and view["operator_has_password"] is True
    assert set(view) >= {"password_may_go_off", "second_factor_off", "public_url"}
    first = client.put("/api/v1/server/sign-in", json={"factor_required": True})
    assert first.status_code == 409 and first.json()["detail"]["code"] == "own_second_factor_first"
    alone = client.put("/api/v1/server/sign-in", json={"password_login": False})
    assert alone.status_code == 409 and alone.json()["detail"]["code"] == "provider_first"
    assert client.put("/api/v1/server/sign-in", json={"passkeys_allowed": False}).json()["passkeys_allowed"] is False
    assert client.get("/api/v1/settings").json()["passkeys_allowed"] is False
    # With a factor of the operator's own it goes on; off again only with the password.
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.totp_secret_enc = totp.seal_seed(totp.generate_seed())
        db.commit()
    assert client.get("/api/v1/server/sign-in").json()["factor_may_go_on"] is True
    assert client.put("/api/v1/server/sign-in", json={"factor_required": True}).json()["factor_required"] is True
    wrong = client.put("/api/v1/server/sign-in", json={"factor_required": False, "password": "nope"})
    assert wrong.status_code in (401, 403) and client.get("/api/v1/settings").json()["two_factor_required"] is True
    off = client.put("/api/v1/server/sign-in", json={"factor_required": False, "password": PASSWORD})
    assert off.status_code == 200 and off.json()["factor_required"] is False
    with new_client(make_account("mika")) as member:
        assert member.get("/api/v1/server/sign-in").status_code == 403


def test_ready_for_the_internet_in_the_module_s_form_and_the_old_route_as_before(client: TestClient,
                                                                                operator: Account) -> None:
    found = client.get("/api/v1/server/readiness").json()
    keys = [point["key"] for point in found["points"]]
    assert keys == ["address", "factorForAll", "ownAccount", "brake", "secrets", "cookies", "proxy", "backups",
                    "upload_requests"]
    secrets = next(point for point in found["points"] if point["key"] == "secrets")
    assert secrets["title"] == "ready.secrets.title" and secrets["text"].startswith("ready.secrets.")
    assert found["open"] == sum(point["state"] != "ok" for point in found["points"])
    old = client.get("/api/v1/settings/readiness").json()
    assert [point["key"] for point in old["points"]] == ["https", "two_factor", "own_account", "brake", "secrets",
                                                          "cookies", "proxy", "backups", "upload_requests"]
    with new_client(make_account("mika")) as member:
        assert member.get("/api/v1/server/readiness").status_code == 403


def test_new_accounts_start_with_the_storage_for_new_accounts_the_ones_there_keep_theirs(
        client: TestClient, operator: Account, provider: FakeProvider) -> None:
    """Bauplan E44: "Speicher für neue Konten" under Server › General › Limits; empty means no limit. An invitation, a
    provider and nexpaper's own way all give a new account that limit; an account that is there keeps its own."""
    from app.services import accounts as account_service

    before = make_account("before")
    assert client.get("/api/v1/settings").json()["new_account_storage_limit"] is None
    five = 5 * 1024**3
    saved = client.put("/api/v1/settings", json={"new_account_storage_limit": five})
    assert saved.status_code == 200 and saved.json()["new_account_storage_limit"] == five
    # Other settings sent alone leave it as it is.
    assert client.put("/api/v1/settings", json={"links_allowed": True}).json()["new_account_storage_limit"] == five

    token = client.post("/api/v1/invites", json={"days": 7}).json()["link"].rsplit("/", 1)[1]
    with new_client() as visitor:
        joined = visitor.post(f"/api/v1/invite/{token}", json={"name": "nina", "password": PASSWORD})
        assert joined.status_code in (200, 201), joined.text
    configure(client, provider, auto_create=True)
    assert location(sign_in_via_oidc(fresh_browser(), provider, sub="person-9", preferred_username="lea")) == "/"
    with SessionLocal() as db:
        made = account_service.create_with_password(db, "otto", PASSWORD)
        assert made.storage_limit == five
        for name in ("nina", "lea"):
            row = db.scalar(select(Account).where(Account.name == name))
            assert row is not None and row.storage_limit == five, name
        assert db.get(Account, before.id).storage_limit is None, "an account that is there keeps its limit"  # type: ignore[union-attr]
    assert listed(client, "nina")["storage_limit"] == five

    # Emptied: new accounts start without a limit again; nothing below one byte, no text.
    assert client.put("/api/v1/settings", json={"new_account_storage_limit": None}).json()[
        "new_account_storage_limit"] is None
    for wrong in (0, -1, "5", 11 * 1024**4):
        assert client.put("/api/v1/settings", json={"new_account_storage_limit": wrong}).status_code == 422, wrong
    with SessionLocal() as db:
        assert account_service.create_with_password(db, "paul", PASSWORD).storage_limit is None
    with SessionLocal() as db:
        assert db.scalar(select(Account).where(Account.name == "nina")).storage_limit == five  # type: ignore[union-attr]


def test_new_accounts_start_with_system_accounts_of_before_take_the_kept_value_or_the_default_once(
        client: TestClient, operator: Account, provider: FakeProvider) -> None:
    """Bauplan E45: an account made now (invitation, provider, nexpaper's own way) has the theme system from the start,
    kept where nexpaper keeps it (``profile.mode``), whatever the browser holds. An account of before without a choice
    takes, once, the value its browser really kept, else nexpaper's default of before (system), and keeps it."""
    from app.services import accounts as account_service

    token = client.post("/api/v1/invites", json={"days": 7}).json()["link"].rsplit("/", 1)[1]
    with new_client() as visitor:
        joined = visitor.post(f"/api/v1/invite/{token}", json={"name": "nina", "password": PASSWORD})
        assert joined.status_code in (200, 201), joined.text
        assert visitor.get("/api/v1/auth/me").json()["theme"] == "system"
        # A value this browser kept for somebody else is no choice of the new account.
        assert visitor.post("/api/v1/me/theme/adopt", json={"theme": "dark"}).json() == {"theme": "system"}
    configure(client, provider, auto_create=True)
    assert location(sign_in_via_oidc(fresh_browser(), provider, sub="person-7", preferred_username="lea")) == "/"
    with SessionLocal() as db:
        assert account_service.create_with_password(db, "otto", PASSWORD).profile == {"mode": "system"}
        for name in ("nina", "lea"):
            row = db.scalar(select(Account).where(Account.name == name))
            assert row is not None and row.profile == {"mode": "system"}, name

    # Accounts of before: profile.mode empty, as 1.12.0 left an account that never chose.
    for name, kept, taken in (("kim", "dark", "dark"), ("ole", "", "system"), ("uwe", '"light"', "light")):
        make_account(name)
        with new_client() as browser:
            assert browser.post("/api/v1/auth/login", json={"name": name, "password": PASSWORD}).status_code == 200
            assert browser.get("/api/v1/auth/me").json()["theme"] == ""
            assert browser.post("/api/v1/me/theme/adopt", json={"theme": kept}).json() == {"theme": taken}, name
            # Once: what a browser kept later changes nothing any more.
            assert browser.post("/api/v1/me/theme/adopt", json={"theme": "light" if taken != "light" else "dark"}).json() == {
                "theme": taken}
            me = browser.get("/api/v1/auth/me").json()
            assert me["theme"] == taken and me["profile"]["mode"] == taken, name
