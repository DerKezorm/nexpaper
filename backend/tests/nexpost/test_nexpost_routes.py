"""Since 1.1.0: the routes of the page Server › Mail in the app: operators only; the view never shows the password and
names the last result and the mails waiting; saving keeps the stored password unless a new one is typed; the test
mail goes out at once in the page's language or says why not."""

from __future__ import annotations

import smtplib
from typing import Any

from post_contract import password


def _change(**values: Any) -> dict[str, Any]:
    change: dict[str, Any] = {
        "host": "mail.example.com",
        "port": 587,
        "security": "starttls",
        "user": "robot",
        "sender": "robot@example.com",
        "sender_name": "",
    }
    change.update(values)
    return change


def test_without_an_operator_every_mail_route_is_closed(app: Any, server: Any) -> None:
    base = app.mail_prefix
    for role, status in (("anonymous", 401), ("member", 403)):
        client = app.client(role)
        assert client.get(base).status_code == status, role
        assert client.put(base, json=_change(password=password())).status_code == status, role
        assert client.post(f"{base}/test", json={"to": "kim@example.org"}).status_code == status, role
    assert server.sent == []
    with app.store() as store:
        assert not store.mail_settings().configured


def test_the_page_saves_and_shows_the_mail_server_never_the_password(app: Any, post: Any) -> None:
    client = app.client("operator")
    secret = password()
    empty = client.get(app.mail_prefix).json()
    assert empty["configured"] is False and empty["password_set"] is False
    assert empty["sender_name_default"] == post.current().shown_name and empty["waiting"] == 0
    saved = client.put(app.mail_prefix, json=_change(password=secret))
    assert saved.status_code == 200, saved.text
    view = saved.json()
    assert view["configured"] is True and view["password_set"] is True and view["port"] == 587
    assert secret not in saved.text and secret not in client.get(app.mail_prefix).text
    again = client.put(app.mail_prefix, json=_change(sender_name="Robot", password=None)).json()
    assert again["sender_name"] == "Robot" and again["password_set"] is True
    with app.store() as store:
        assert store.mail_settings().password == secret
    removed = client.put(app.mail_prefix, json=_change(password="")).json()
    assert removed["password_set"] is False


def test_the_page_warns_without_encryption_and_refuses_what_does_not_fit(app: Any) -> None:
    client = app.client("operator")
    plain = client.put(app.mail_prefix, json=_change(security="none", port=25, password=password())).json()
    assert plain["warnings"] == ["unencrypted"] and plain["security"] == "none"
    for wrong in (_change(port=70000), _change(security="ssl3"), _change(sender="nobody"), _change(sender="")):
        answer = client.put(app.mail_prefix, json=wrong)
        assert answer.status_code == 422, wrong
    older = client.put(app.mail_prefix, json=_change(security="ssl", port=465)).json()
    assert older["security"] == "tls"


def test_the_test_mail_goes_out_in_the_pages_language_or_says_why_not(app: Any, post: Any, server: Any) -> None:
    client = app.client("operator")
    off = client.post(f"{app.mail_prefix}/test", json={"to": "kim@example.org", "language": "de"})
    assert off.status_code == 409 and post.MailError("mail_off", "").public_code in off.text
    assert client.put(app.mail_prefix, json=_change(password=password())).status_code == 200
    sent = client.post(f"{app.mail_prefix}/test", json={"to": "kim@example.org", "language": "de"})
    assert sent.status_code == 204, sent.text
    assert server.sent[-1]["Subject"] == f"Testmail von {post.current().shown_name}"
    assert client.get(app.mail_prefix).json()["last_ok_at"]
    server.fail.append(smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials"))
    refused = client.post(f"{app.mail_prefix}/test", json={"to": "kim@example.org", "language": "en"})
    assert refused.status_code == 502
    view = client.get(app.mail_prefix).json()
    assert view["last_error"] == "mail_auth_refused" and view["last_error_at"]
    wrong = client.post(f"{app.mail_prefix}/test", json={"to": "not an address"})
    assert wrong.status_code == 422
