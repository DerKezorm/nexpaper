"""Rights of the search, the text and the text behind a link for every kind of caller; hostile input; the index."""

from __future__ import annotations

import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Account, ApiKey, utcnow
from app.services import apikeys

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import give_text


@pytest.fixture(autouse=True)
def no_brake(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests search far more often than a person can: the brake of the search (tested in ``test_search.py``)
    stays out of the way."""
    from app.services import brakes

    monkeypatch.setitem(brakes.LIMITS, "search", 100_000)

WORD = "geheimschluessel"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def program() -> TestClient:
    return TestClient(app, base_url="http://testserver")


def pair(client: TestClient) -> str:
    return str(client.post("/api/v1/devices", json={"name": "phone"}).json()["token"])


def raw_key(account: Account, scope: str) -> str:
    import secrets

    token = apikeys.KEY_PREFIX + secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.add(ApiKey(account_id=account.id, name="k", scope=scope, token_hash=apikeys.digest(token),
                      prefix=token[:8], created_at=utcnow(), expires_at=None))
        db.commit()
    return token


@pytest.fixture
def world(client: TestClient, operator: Account):
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    jule, tom, lea, out, share = (make_account(n) for n in ("jule", "tom", "lea", "outsider", "sharee"))
    vault = shared_vault("Haushalt", operator, (jule, "manage"), (tom, "edit"), (lea, "read"))
    mine = own_vault(jule)  # jule's personal vault, nobody else
    doc_shared = add_document(vault, jule, "Haus Vertrag", sender="Hansa", date=date(2026, 1, 2))
    doc_personal = add_document(mine, jule, "Persoenlich Arzt", sender="Praxis", date=date(2026, 2, 2))
    give_text(doc_shared, f"Vertrag {WORD} gemeinsam")
    give_text(doc_personal, f"Befund {WORD} persoenlich")
    # sharee: one document of the personal vault shared by hand
    with new_client(jule) as c:
        assert c.put(f"/api/v1/documents/{doc_personal}/shares/{share.id}", json={"right": "read"}).status_code == 200
        link_dl = c.post(f"/api/v1/documents/{doc_personal}/links", json={"recipient": "x", "days": 7, "allow_download": True}).json()["token"]
        link_nodl = c.post(f"/api/v1/documents/{doc_personal}/links", json={"recipient": "y", "days": 7, "allow_download": False}).json()["token"]
        dev_jule = pair(c)
    with new_client(out) as c:
        dev_out = pair(c)
    return {"operator": operator, "jule": jule, "tom": tom, "lea": lea, "out": out, "share": share, "vault": vault,
            "mine": mine, "doc_shared": doc_shared, "doc_personal": doc_personal, "link_dl": link_dl,
            "link_nodl": link_nodl, "dev_jule": dev_jule, "dev_out": dev_out}


def hits(client: TestClient, q: str = WORD, **kw):
    return client.get("/api/v1/search", params={"q": q, **kw})


def titles(r):
    return sorted(i["document"]["title"] for i in r.json()["items"])


def test_search_matrix(world) -> None:
    w = world
    # browser sessions
    exp = {"jule": ["Haus Vertrag", "Persoenlich Arzt"], "tom": ["Haus Vertrag"], "lea": ["Haus Vertrag"],
           "outsider": [], "sharee": ["Persoenlich Arzt"]}
    for who, want in exp.items():
        acc = {"jule": w["jule"], "tom": w["tom"], "lea": w["lea"], "outsider": w["out"], "sharee": w["share"]}[who]
        with new_client(acc) as c:
            r = c.get("/api/v1/search", params={"q": WORD})
            assert r.status_code == 200 and titles(r) == want, (who, r.text)
            assert r.json()["total"] == len(want)
            # understood must not echo anything of invisible docs; also trash search of others' docs
            r2 = c.get("/api/v1/search", params={"q": WORD, "trash": "true"})
            assert r2.json()["total"] == 0
    # device tokens
    with program() as p:
        r = p.get("/api/v1/search", params={"q": WORD}, headers=bearer(w["dev_jule"]))
        assert titles(r) == ["Haus Vertrag", "Persoenlich Arzt"]
        r = p.get("/api/v1/search", params={"q": WORD}, headers=bearer(w["dev_out"]))
        assert r.status_code == 200 and titles(r) == []
        # key scopes
        k_read = raw_key(w["out"], "read")
        kj_read = raw_key(w["jule"], "read")
        kj_up = raw_key(w["jule"], "upload")
        assert titles(p.get("/api/v1/search", params={"q": WORD}, headers=bearer(k_read))) == []
        assert titles(p.get("/api/v1/search", params={"q": WORD}, headers=bearer(kj_read))) == ["Haus Vertrag", "Persoenlich Arzt"]
        r = p.get("/api/v1/search", params={"q": WORD}, headers=bearer(kj_up))
        assert r.status_code == 403, r.text
        r = p.get(f"/api/v1/documents/{w['doc_personal']}/versions/1/text", headers=bearer(kj_up))
        assert r.status_code == 403, r.text
        r = p.get(f"/api/v1/documents/{w['doc_personal']}/versions/1/text", headers=bearer(k_read))
        assert r.status_code == 404, r.text
        r = p.get(f"/api/v1/documents/{w['doc_personal']}/versions/1/text", headers=bearer(kj_read))
        assert r.status_code == 200
        # anonymous
        assert p.get("/api/v1/search", params={"q": WORD}).status_code in (401, 403)
        assert p.get(f"/api/v1/documents/{w['doc_personal']}/versions/1/text").status_code in (401, 403)
        # link text
        assert p.get(f"/api/v1/l/{w['link_dl']}/text").status_code == 200
        r = p.get(f"/api/v1/l/{w['link_nodl']}/text")
        assert r.status_code == 403, r.text
        assert p.get("/api/v1/l/lnk_nonexistent/text").status_code == 404
        # a link is no way into the search or the other doc
        assert p.get("/api/v1/search", params={"q": WORD}, headers=bearer(w["link_dl"])).status_code in (401, 403)
        # text through the link is the link's doc only
        t = p.get(f"/api/v1/l/{w['link_dl']}/text").json()
        assert WORD in t["pages"][0] and "gemeinsam" not in t["pages"][0]
    # settings/ocr: operator in browser only
    with new_client(w["jule"]) as c:
        assert c.get("/api/v1/settings/ocr").status_code == 403
        assert c.put("/api/v1/settings/ocr", json={"jobs": 2}).status_code == 403
    with program() as p:
        assert p.get("/api/v1/settings/ocr", headers=bearer(w["dev_jule"])).status_code == 403
        assert p.get("/api/v1/settings/ocr").status_code in (401, 403)
    with new_client(w["operator"]) as c:
        assert c.get("/api/v1/settings/ocr").status_code == 200
        # a device of the operator may not reach it
        dev_op = pair(c)
    with program() as p:
        r = p.get("/api/v1/settings/ocr", headers=bearer(dev_op))
        assert r.status_code == 403, r.text
        r = p.put("/api/v1/settings/ocr", headers=bearer(dev_op), json={"jobs": 2})
        assert r.status_code == 403, r.text


def test_after_removing_rights_nothing_stays(world) -> None:
    w = world
    # take lea out of the vault: her search must show nothing at once
    with new_client(w["jule"]) as c:
        assert c.delete(f"/api/v1/vaults/{w['vault']}/members/{w['lea'].id}").status_code in (200, 204)
    with new_client(w["lea"]) as c:
        assert c.get("/api/v1/search", params={"q": WORD}).json()["total"] == 0
        assert c.get(f"/api/v1/documents/{w['doc_shared']}/versions/1/text").status_code == 404
    # remove share from sharee
    with new_client(w["jule"]) as c:
        assert c.delete(f"/api/v1/documents/{w['doc_personal']}/shares/{w['share'].id}").status_code in (200, 204)
    with new_client(w["share"]) as c:
        assert c.get("/api/v1/search", params={"q": WORD}).json()["total"] == 0


def test_trash_only_own(world) -> None:
    w = world
    # tom (edit) trashes the shared doc owned by jule; jule is manager: trash search shows only for the OWNER
    with new_client(w["tom"]) as c:
        assert c.delete(f"/api/v1/documents/{w['doc_shared']}").status_code in (200, 204)
        r = c.get("/api/v1/search", params={"q": WORD, "trash": "true"}).json()
        assert r["total"] == 0  # not his
        assert c.get("/api/v1/search", params={"q": WORD}).json()["total"] == 0
    with new_client(w["jule"]) as c:
        r = c.get("/api/v1/search", params={"q": WORD, "trash": "true"}).json()
        assert r["total"] == 1
        assert c.get("/api/v1/search", params={"q": WORD}).json()["total"] == 1  # the personal doc only
    with new_client(w["lea"]) as c:
        assert c.get("/api/v1/search", params={"q": WORD, "trash": "true"}).json()["total"] == 0
        assert c.get("/api/v1/search", params={"q": WORD}).json()["total"] == 0


HOSTILE = [
    "", " ", "\x00", "a\x00b", "NEAR(a b)", "NEAR/3", "a NEAR b", "*", "**", "^a", "a*", "-a", "a OR b", "a AND b",
    "(", ")", "((((", "))))", '"', '""', '"""', '"a', 'a"', 'a"b', "'", "''", "\\", "\\\\", "%", "_", "%_%", ";", "--",
    "'; DROP TABLE documents;--", "title:foo", "text:foo", "col:", ":", "::", "art:", "art:\"", 'art:"a b"', "tag:#",
    "betrag:", "betrag:abc", "betrag:>", "betrag:>1e999", "betrag:>99999999999999999999999", "betrag:<-1",
    "betrag:1,2,3", "betrag:1.2.3", "betrag:\u20ac", "betrag:=0,001", "betrag:>\u0661\u0662\u0663", "amount:>1 000 000",
    "a" * 400, "a" * 500, "a" * 501, "ab " * 12, "ab " * 13, "x:y " * 12, "\u00df", "\u1e9e", "\u017f", "\ufb03", "\u0130", "\u0131", "\u00c5", "\u00c5",
    "\u202e", "\u200b", "\ufeff", "a\u0301", "\U0001f600", "\U0001f600" * 50, "a\ud800b".encode("utf-8", "replace").decode(),
    "\u01c5", "\U0001d51e", "\u2460\u2461", "\uff41\uff42\uff43", "fi", "\u01c4", "\u01c6", "\x01\x02", "\t\n\r", "a\fb", "{{", "}}", "[", "]", "{", "$", "$(id)",
    "{{7*7}}", "<script>", "../../etc/passwd", "a:b:c", "art:art:art", "tag:tag:tag", ":::", '":"', "a OR", "OR",
    "AND", "NOT", "NOT a", "NEAR", "NEAR(", "w" * 64 + " " + "w" * 65,
    '"' + " ".join(["wort"] * 40) + '"', '"a b c d e f g h i j k l m n o p q r s t u v"',
    "e-mail", "R-2026-17", "12.30", "12:30", "re:anfrage", "http://x.example", "a@b.example.com", "a/b", "a.b.c.d.e.f",
    "ab", "a", "\u00df" * 100, "ss", "stra\u00dfe", "strasse", "STRASSE", "m\u00fcller", "mueller", "M\u00dcLLER", "\u00e4", "\u00f6", "\u00fc",
]


def test_hostile_inputs(world) -> None:
    w = world
    slow = []
    with new_client(w["jule"]) as c:
        for q in HOSTILE:
            began = time.perf_counter()
            r = c.get("/api/v1/search", params={"q": q})
            took = time.perf_counter() - began
            assert r.status_code in (200, 422), (repr(q)[:60], r.status_code, r.text[:200])
            if r.status_code == 422:
                assert "detail" in r.json()
            # A query that is slow by its form is slow every time; a machine under load is slow now and then. The
            # fastest of three counts (asked again only when the first was over the line), against the same 0.5 s.
            for _again in range(2):
                if took <= 0.5:
                    break
                began = time.perf_counter()
                c.get("/api/v1/search", params={"q": q})
                took = min(took, time.perf_counter() - began)
            if took > 0.5:
                slow.append((repr(q)[:40], took))
    assert not slow, slow
    # parameters hostile too
    with new_client(w["jule"]) as c:
        for params in [
            {"cursor": "!!!"}, {"cursor": "MTIz"}, {"cursor": "MjAyNi0wMS0wMXwx"}, {"cursor": "MjAyNi0wMS0wMXw5OTk5OTk5OTk5OTk5OTk5OTk5"},
            {"cursor": "x" * 200}, {"cursor": "MjAyNi0wMS0wMXwtMQ"}, {"limit": 0}, {"limit": 101}, {"limit": -1}, {"limit": "abc"},
            {"vault_id": 0}, {"vault_id": 99999999999}, {"vault_id": "x"}, {"date_from": "nope"}, {"date_from": "2026-13-45"},
            {"status": "trash"}, {"status": "bogus"}, {"sender": ""}, {"tag": "x" * 41}, {"owner_id": -1},
            {"date_from": "9999-12-31", "date_to": "0001-01-01"},
        ]:
            r = c.get("/api/v1/search", params={"q": "vertrag", **params})
            assert r.status_code in (200, 422), (params, r.status_code, r.text[:200])
        # very long q beyond max_length
        r = c.get("/api/v1/search", params={"q": "a" * 5000})
        assert r.status_code == 422
        # a forged cursor shows nothing it should not: same total, items only visible
        import base64
        forged = base64.urlsafe_b64encode(b"2030-01-01|99999").decode().rstrip("=")
        r = c.get("/api/v1/search", params={"q": WORD, "cursor": forged}).json()
        assert r["total"] == 2 and r["next"] is None
