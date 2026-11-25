"""An invitation: the operator gives no username; the person invited chooses one; the invitation's address counts as
confirmed while it is not changed; one invitation makes one account."""

from __future__ import annotations

from typing import Any

import pytest
from konten_contract import password


def _accept(konten: Any, store: Any, token: str, **changes: Any) -> Any:
    values: dict[str, Any] = {
        "display_name": "New Person",
        "username": "newbie",
        "email": "new@example.com",
        "password": password(),
    }
    values.update(changes)
    return konten.invites.accept_invite(store, token, **values)


def test_the_operator_cannot_invite_an_address_another_account_has(app: Any, konten: Any, operator: Any) -> None:
    with app.store() as store:
        with pytest.raises(konten.AccountError) as caught:
            konten.invites.invite_values(store, email="BOSS@example.com", display_name="x")
        assert caught.value.code == "email_taken"
        assert konten.invites.invite_values(store, email=" new@example.com ", display_name=" Neu ") == (
            "new@example.com",
            "Neu",
        )


def test_the_form_shows_display_name_address_and_a_free_username(app: Any, konten: Any, operator: Any) -> None:
    app.seed("max-mueller", password=password())
    token = app.make_invite(email="max@example.com", display_name="Max Müller")
    with app.store() as store:
        form = konten.invites.invite_form(store, token)
    assert (form.display_name, form.username, form.email) == ("Max Müller", "max-mueller-2", "max@example.com")


def test_an_invitation_of_the_older_version_keeps_its_username_in_the_form(
    app: Any, konten: Any, operator: Any
) -> None:
    token = app.make_invite(display_name="Kim", username="kim.lee")
    with app.store() as store:
        assert konten.invites.invite_form(store, token).username == "kim.lee"


def test_the_address_of_the_invitation_counts_as_confirmed(app: Any, konten: Any, operator: Any) -> None:
    secret = password()
    token = app.make_invite(email="new@example.com")
    with app.store() as store:
        accepted = _accept(konten, store, token, email="NEW@example.com", password=secret, mail=True)
    assert accepted.mail is None
    assert accepted.account.email_confirmed and accepted.account.email.lower() == "new@example.com"
    assert not accepted.account.operator
    assert app.sign_in("new@example.com", secret) == accepted.account.id
    assert app.sign_in("newbie", secret) == accepted.account.id


def test_another_address_waits_for_its_link_with_a_mail_server(app: Any, konten: Any, operator: Any) -> None:
    secret = password()
    token = app.make_invite(email="new@example.com")
    with app.store() as store:
        accepted = _accept(konten, store, token, email="other@example.com", password=secret, mail=True)
    assert accepted.account.email == "" and accepted.account.pending_email == "other@example.com"
    letter = accepted.mail
    assert letter.kind == konten.MAIL_CONFIRM_EMAIL and letter.to == "other@example.com" and letter.token
    assert app.sign_in("other@example.com", secret) is None
    with app.store() as store:
        konten.profiles.confirm_email(store, letter.token)
    assert app.sign_in("other@example.com", secret) == accepted.account.id


def test_another_address_counts_at_once_without_a_mail_server(app: Any, konten: Any, operator: Any) -> None:
    secret = password()
    token = app.make_invite(email="new@example.com")
    with app.store() as store:
        accepted = _accept(konten, store, token, email="other@example.com", password=secret)
    assert accepted.mail is None and accepted.account.email == "other@example.com"
    assert app.sign_in("other@example.com", secret) == accepted.account.id


def test_an_invitation_makes_one_account(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite()
    with app.store() as store:
        _accept(konten, store, token)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        _accept(konten, store, token, username="second", display_name="Second", email="")
    assert caught.value.code == "invite_invalid"


def test_two_people_with_one_link_at_the_same_moment_make_one_account(
    app: Any, konten: Any, operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = app.make_invite()
    with app.store() as one, app.store() as other:
        # The second request found the invitation open before the first used it up.
        found = other.find_invite(token)
        monkeypatch.setattr(other, "find_invite", lambda key: found)
        _accept(konten, one, token, username="first", display_name="First", email="")
        with pytest.raises(konten.AccountError) as caught:
            _accept(konten, other, token, username="second", display_name="Second", email="")
    assert caught.value.code == "invite_invalid"
    with app.store() as store:
        assert store.find_by_username("second") == []
        assert store.count_accounts() == 2


def test_a_taken_username_keeps_the_invitation_open(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite()
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        _accept(konten, store, token, username="BOSS", email="")
    assert caught.value.code == "username_taken"
    with app.store() as store:
        assert _accept(konten, store, token, email="").account.username == "newbie"


def test_an_address_of_another_account_is_refused(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite()
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        _accept(konten, store, token, email="boss@EXAMPLE.com")
    assert caught.value.code == "email_taken"


def test_an_expired_invitation_says_so(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite(expired=True)
    for call in (
        lambda store: konten.invites.invite_form(store, token),
        lambda store: _accept(konten, store, token),
    ):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            call(store)
        assert caught.value.code == "invite_expired"
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.invites.invite_form(store, "unknown-" + password())
    assert caught.value.code == "invite_invalid"


def test_the_person_invited_needs_a_display_name_and_a_long_password(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite()
    for changes, code in (({"display_name": " "}, "display_name_empty"), ({"password": "short"}, "password_too_short")):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            _accept(konten, store, token, **changes)
        assert caught.value.code == code


def test_an_invitation_holds_one_seven_or_thirty_days(app: Any, konten: Any) -> None:
    now = konten.common.utcnow()
    assert abs((konten.invites.invite_expires_at() - now).days - 7) <= 1
    for days in (1, 30):
        assert abs((konten.invites.invite_expires_at(days) - now).days - days) <= 1
    with pytest.raises(konten.AccountError) as caught:
        konten.invites.invite_expires_at(14)
    assert caught.value.code == "invalid_days"


def test_a_display_name_another_account_shows_is_refused_and_not_offered(app: Any, konten: Any, operator: Any) -> None:
    app.seed("kim", display_name="Kim Lee", password=password())
    token = app.make_invite(display_name="kim lee")
    with app.store() as store:
        assert konten.invites.invite_form(store, token).display_name == ""
    for shown in ("KIM LEE", "kim"):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            _accept(konten, store, token, display_name=shown)
        assert caught.value.code == "display_name_taken", shown


def test_an_older_request_without_a_display_name_takes_the_username(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite()
    with app.store() as store:
        accepted = _accept(konten, store, token, display_name="", older_request=True)
    assert accepted.account.display_name == "newbie"
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        _accept(konten, store, app.make_invite(), username="another", display_name="", email="")
    assert caught.value.code == "display_name_empty"


def test_an_existing_account_joins_with_an_invitation_once(app: Any, konten: Any, operator: Any) -> None:
    alex = app.seed("alex", password=password())
    token = app.make_invite(email="alex@example.com")
    with app.store() as store:
        assert konten.invites.join_invite(store, token, alex).id == alex
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.invites.join_invite(store, token, alex)
    assert caught.value.code == "invite_invalid"


def test_the_operator_may_invite_an_address_that_has_an_account_into_a_space(
    app: Any, konten: Any, operator: Any
) -> None:
    with app.store() as store:
        address, _ = konten.invites.invite_values(store, email="boss@example.com", display_name="", existing_ok=True)
    assert address == "boss@example.com"


def test_after_an_invitation_the_app_learns_the_next_step(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite()
    with app.store() as store:
        accepted = _accept(konten, store, token)
        assert accepted.next == konten.common.next_step(store, accepted.account)


def test_the_address_of_an_invitation_several_may_follow_does_not_count_without_a_link(
    app: Any, konten: Any, operator: Any
) -> None:
    if not app.reusable_invites:
        return  # the app has no invitations several may follow
    token = app.make_invite(email="team@example.com", reusable=True)
    with app.store() as store:
        accepted = _accept(konten, store, token, email="team@example.com", mail=True)
    assert accepted.account.email == "" and accepted.mail is not None and accepted.mail.to == "team@example.com"


def test_an_invitation_mailed_by_the_app_proves_its_address(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite(email="new@example.com")
    with app.store() as store:
        accepted = _accept(konten, store, token, proven=True)
    assert accepted.account.email_proven and accepted.account.email_confirmed
    other = app.make_invite(email="other@example.com")
    with app.store() as store:
        changed = _accept(
            konten, store, other, username="second", display_name="Second", email="x@example.com", proven=True
        )
    assert not changed.account.email_proven


def test_a_name_an_older_invitation_fixed_is_kept_as_it_was(app: Any, konten: Any, operator: Any) -> None:
    token = app.make_invite(display_name="Kim", username="_Kim.Old")
    with app.store() as store:
        form = konten.invites.invite_form(store, token)
        assert form.username == "_Kim.Old"
        accepted = _accept(konten, store, token, username=form.username, display_name="Kim", email="")
    assert accepted.account.username == "_Kim.Old"
    other = app.make_invite()
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        _accept(konten, store, other, username="_free", display_name="Free", email="")
    assert caught.value.code == "username_invalid"


def test_without_a_public_address_there_is_no_invitation(app: Any, konten: Any, operator: Any) -> None:
    """The link would lead nowhere: refused with a hint where the address is entered."""
    with app.store() as store:
        for public_url in ("", "   ", "notes.example.com"):
            with pytest.raises(konten.AccountError) as caught:
                konten.invites.invite_values(store, email="", display_name="Kim", public_url=public_url)
            assert caught.value.code == "public_url_needed" and caught.value.status == 409
        assert konten.invites.invite_values(
            store, email="kim@example.com", display_name="Kim", public_url="https://notes.example.com"
        ) == ("kim@example.com", "Kim")
    with pytest.raises(konten.AccountError):
        konten.invites.invite_link("", "invite", "abc")
    link = konten.invites.invite_link("https://notes.example.com/", "/invite/", "a/b")
    assert link == "https://notes.example.com/invite/a%2Fb"


def test_without_a_public_address_the_link_takes_the_address_the_operator_opened(
    app: Any, konten: Any, operator: Any
) -> None:
    """Decided 25.11.2026 (0.3.5, replaces "refused" of 0.3.2): an installation without an entered public address
    still invites; the link leads to the address of the operator's request (scheme, host, port, base path), as
    nexnotes always did. Only without both there is ``public_url_needed``; an entered address always wins."""
    seen = "http://box.example.net:8080/notes/"
    with app.store() as store:
        for public_url in ("", "   ", "notes.example.com"):
            assert konten.invites.invite_values(
                store, email="kim@example.com", display_name="Kim", public_url=public_url, request_base=seen
            ) == ("kim@example.com", "Kim")
            link = konten.invites.invite_link(public_url, "/invite/", "a/b", request_base=seen)
            assert link == "http://box.example.net:8080/notes/invite/a%2Fb"
        for request_base in ("", None, "box.example.net:8080", "ftp://host/"):
            with pytest.raises(konten.AccountError) as caught:
                konten.invites.invite_values(
                    store, email="", display_name="Kim", public_url="", request_base=request_base
                )
            assert caught.value.code == "public_url_needed" and caught.value.status == 409
    assert (
        konten.invites.invite_link("https://notes.example.com", "invite", "t", request_base=seen)
        == "https://notes.example.com/invite/t"
    )
    assert konten.invites.invite_link("", "invite", "t", request_base="https://h.example/?x=1#y") == (
        "https://h.example/invite/t"
    )


def test_the_list_route_keeps_expired_invitations(app: Any, operator: Any) -> None:
    """Since 0.3.10 said plainly (decided after nextime's rebuild): the operator's list of open invitations, as the
    app's route answers it, holds an expired invitation too, marked ``expired``, until the operator withdraws it; a
    valid one is not marked."""
    app.make_invite(email="late@example.com", display_name="Late", expired=True)
    app.make_invite(email="soon@example.com", display_name="Soon")
    listed = {entry["email"]: entry for entry in app.listed_invites()}
    assert listed["late@example.com"]["expired"] is True
    assert listed["soon@example.com"]["expired"] is False
