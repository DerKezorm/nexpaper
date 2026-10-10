"""The inbox as a list (``GET /api/v1/inbox``), the numbers of the menu (``/counts``) and filing many at once.

What matters: the inbox holds only what the caller may change (a member with `read` sees no inbox of that vault), the
rights are in the queries (no count and no word search reaches into a vault the caller is not in), a page is at most
what was asked for, and filing in bulk checks every document on its own, as a single change would.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Share, Version, VersionText
from app.services import search_index

from .conftest import make_account, new_client
from .papers import add_document, document, own_vault, shared_vault


def inbox_doc(vault: int, owner: Account | None, title: str, **fields: object) -> int:
    fields.setdefault("status", "inbox")
    return add_document(vault, owner, title, content=None, **fields)  # type: ignore[arg-type]


def titles(page: dict) -> list[str]:
    return [item["title"] for item in page["items"]]


def get(session: TestClient, **params: object) -> dict:
    answer = session.get("/api/v1/inbox", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def world(operator: Account) -> tuple[Account, Account, int]:
    """A shared vault: the operator manages it, `editor` may change, `reader` only look."""
    editor = make_account("editor")
    reader = make_account("reader")
    vault = shared_vault("Household", operator, (operator, "manage"), (editor, "edit"), (reader, "read"))
    return editor, reader, vault


# --- Who sees what ------------------------------------------------------------------------------------------------------


def test_the_inbox_holds_what_the_caller_may_change_and_a_reader_sees_none_of_it(client: TestClient, operator: Account) -> None:
    editor, reader, vault = world(operator)
    inbox_doc(vault, operator, "Waiting")
    add_document(vault, operator, "Filed", content=None)
    with new_client(editor) as session:
        assert titles(get(session)) == ["Waiting"]
    with new_client(reader) as session:
        page = get(session)
        assert page["items"] == [] and page["total"] == 0 and page["counts"] == {} and page["all"] == 0
        assert session.get("/api/v1/counts").json() == {"inbox": 0, "reading": 0, "trash": 0}
        assert get(session, vault_id=vault) == page, "asking for the vault tells nothing more"
    assert titles(get(client)) == ["Waiting"]


def test_a_document_shared_to_edit_is_in_the_inbox_and_one_shared_to_read_is_not(client: TestClient, operator: Account) -> None:
    other = make_account("other")
    mine = inbox_doc(own_vault(other), other, "Shared to edit")
    only = inbox_doc(own_vault(other), other, "Shared to read")
    inbox_doc(own_vault(other), other, "Not shared")
    with new_client(other) as session:
        assert session.put(f"/api/v1/documents/{mine}/shares/{operator.id}", json={"right": "edit"}).status_code == 200
        assert session.put(f"/api/v1/documents/{only}/shares/{operator.id}", json={"right": "read"}).status_code == 200
    assert titles(get(client)) == ["Shared to edit"]


def test_a_document_reached_through_a_share_alone_is_counted_as_shared_without_naming_its_vault(
        client: TestClient, operator: Account) -> None:
    other = make_account("other")
    theirs = own_vault(other)
    shared = inbox_doc(theirs, other, "Shared to edit")
    inbox_doc(theirs, other, "Not shared")
    mine = own_vault(operator)
    inbox_doc(mine, operator, "Mine")
    with new_client(other) as session:
        assert session.put(f"/api/v1/documents/{shared}/shares/{operator.id}", json={"right": "edit"}).status_code == 200
    page = get(client)
    assert page["counts"] == {str(mine): 1} and page["shared"] == 1 and page["all"] == 2 and page["total"] == 2
    assert str(theirs) not in page["counts"]
    only = get(client, shared="true")
    assert titles(only) == ["Shared to edit"] and only["total"] == 1 and only["shared"] == 1
    # A narrower search counts them too, and a word that does not fit leaves no group at all.
    assert get(client, q="nothing fits")["shared"] == 0
    # A read right in the vault does not make it one of the caller's vaults.
    reader_vault = shared_vault("Read only", other, (other, "manage"), (operator, "read"))
    seen_by_edit_share = inbox_doc(reader_vault, other, "Shared inside a vault read-only")
    with SessionLocal() as db:  # a share that outlived a change of the person's right in the vault
        db.add(Share(document_id=seen_by_edit_share, user_id=operator.id, right="edit"))
        db.commit()
    again = get(client)
    assert again["shared"] == 2 and str(reader_vault) not in again["counts"]
    assert get(client, shared="true", vault_id=mine)["total"] == 0


def test_nothing_of_another_vault_is_listed_counted_or_found_by_words(client: TestClient, operator: Account) -> None:
    other = make_account("other")
    their = own_vault(other)
    inbox_doc(their, other, "Secret Arztbrief", sender="Their Doctor")
    inbox_doc(own_vault(operator), operator, "My letter")
    page = get(client)
    assert titles(page) == ["My letter"] and page["all"] == 1
    assert get(client, q="arztbrief") == get(client, q="nothing like it")
    assert get(client, q="doctor") == get(client, q="nothing like it")
    assert get(client, vault_id=their) == get(client, vault_id=2**31 - 5)
    assert get(client, sender="Their Doctor")["items"] == []


# --- Pages, sorting, filters ----------------------------------------------------------------------------------------------


def test_a_page_is_as_long_as_asked_and_the_total_and_the_counts_follow_the_filters(client: TestClient, operator: Account) -> None:
    _, _, vault = world(operator)
    mine = own_vault(operator)
    for n in range(130):
        inbox_doc(vault, operator, f"Haushalt {n:03d}")
    for n in range(7):
        inbox_doc(mine, operator, f"Eigen {n}")
    first = get(client, limit=50)
    assert len(first["items"]) == 50 and first["total"] == 137 and first["all"] == 137
    assert first["counts"] == {str(vault): 130, str(mine): 7}
    third = get(client, limit=50, offset=100)
    assert len(third["items"]) == 37
    seen = {i["id"] for p in (get(client, limit=50, offset=o) for o in (0, 50, 100)) for i in p["items"]}
    assert len(seen) == 137, "the pages do not overlap and miss none"
    # One vault: the total follows, the counts of the chips do not (they say what each would show).
    one = get(client, vault_id=mine)
    assert one["total"] == 7 and one["counts"] == {str(vault): 130, str(mine): 7}
    # Another filter changes the counts too.
    narrowed = get(client, q="Eigen 3")
    assert narrowed["counts"] == {str(mine): 1} and narrowed["total"] == 1
    assert client.get("/api/v1/inbox", params={"limit": 201}).status_code == 422
    assert client.get("/api/v1/inbox", params={"sort": "sideways"}).status_code == 422


def test_sorting_by_arrival_and_by_date_and_what_is_being_read_comes_first(client: TestClient, operator: Account) -> None:
    from datetime import date

    vault = own_vault(operator)
    old = inbox_doc(vault, operator, "Old arrival", date=date(2026, 9, 30))
    mid = inbox_doc(vault, operator, "Middle arrival", date=date(2026, 1, 5))
    new = inbox_doc(vault, operator, "New arrival")
    reading = inbox_doc(vault, operator, "Being read", status="processing")
    by = {d: n for d, n in ((old, "old"), (mid, "mid"), (new, "new"), (reading, "reading"))}
    order = lambda **p: [by[i["id"]] for i in get(client, **p)["items"]]
    assert order() == ["reading", "new", "mid", "old"]
    assert order(sort="old") == ["reading", "old", "mid", "new"]
    # By the date on the document, else the day it came in (today for these): the dated ones are older than today.
    assert order(sort="date") == ["reading", "new", "old", "mid"]
    assert get(client)["reading"] == 1



def with_text(made: int, words: str) -> None:
    """The text a document was read as, in the search index as after reading."""
    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == made))
        assert version is not None
        db.add(VersionText(version_id=version.id, document_id=made, text=words, pages=1,
                           digest=search_index.text_digest(words)))
        db.flush()
        search_index.refresh(db, [made])
        db.commit()


def test_words_find_the_text_too_parts_of_words_included_and_nothing_of_another_vault(
        client: TestClient, operator: Account) -> None:
    """A word found only inside a word of the text: "Balkon" in an imported bill that says "Balkonstrom"."""
    mine = add_document(own_vault(operator), operator, "Fwd: Rechnung 2026-0815", status="inbox")
    with_text(mine, "Rechnung Balkonstrom Set mit Wechselrichter")
    other = make_account("other")
    theirs = add_document(own_vault(other), other, "Their bill", status="inbox")
    with_text(theirs, "Balkonstrom Angebot")
    assert titles(get(client, q="Balkon")) == ["Fwd: Rechnung 2026-0815"]
    assert titles(get(client, q="wechselrichter")) == ["Fwd: Rechnung 2026-0815"]
    assert get(client, q="Angebot") == get(client, q="nothing like it")

def test_words_find_a_title_or_a_sender_whatever_the_case_and_accents(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    inbox_doc(vault, operator, "Rechnung Bäckerei", sender="Müller & Söhne")
    inbox_doc(vault, operator, "Strom Oktober", sender="Stadtwerke")
    assert titles(get(client, q="BÄCKEREI")) == ["Rechnung Bäckerei"]
    assert titles(get(client, q="backerei")) == ["Rechnung Bäckerei"]
    assert titles(get(client, q="MÜLLER")) == ["Rechnung Bäckerei"]
    assert titles(get(client, q="stadtw")) == ["Strom Oktober"]
    assert get(client, q="%")["total"] == 0 and get(client, q="_")["total"] == 0
    assert titles(get(client, sender="müller & söhne")) == ["Rechnung Bäckerei"]


def test_kind_source_and_who_brought_it_in_narrow_the_list(client: TestClient, operator: Account) -> None:
    editor, _, vault = world(operator)
    invoice = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    a = inbox_doc(vault, operator, "A", kind_id=invoice["id"], source="mail")
    b = inbox_doc(vault, editor, "B", source="upload")
    c = inbox_doc(vault, editor, "C", source="mail")
    ids = lambda **p: sorted(i["id"] for i in get(client, **p)["items"])
    assert ids(kind_id=invoice["id"]) == [a]
    assert ids(source="mail") == sorted([a, c])
    assert ids(owner_id=editor.id) == sorted([b, c])
    assert ids(owner_id=editor.id, source="mail") == [c]
    assert client.get("/api/v1/inbox", params={"source": "pigeon"}).status_code == 422


def test_the_numbers_of_the_menu_count_the_inbox_the_reading_and_the_trash(client: TestClient, operator: Account) -> None:
    editor, reader, vault = world(operator)
    inbox_doc(vault, operator, "One")
    inbox_doc(vault, operator, "Two")
    inbox_doc(vault, operator, "Three", status="processing")
    gone = inbox_doc(vault, operator, "Gone")
    assert client.delete(f"/api/v1/documents/{gone}").status_code == 200
    assert client.get("/api/v1/counts").json() == {"inbox": 2, "reading": 1, "trash": 1}
    with new_client(editor) as session:
        assert session.get("/api/v1/counts").json() == {"inbox": 2, "reading": 1, "trash": 1}
    with new_client(reader) as session:
        assert session.get("/api/v1/counts").json() == {"inbox": 0, "reading": 0, "trash": 1}
        quick = session.get("/api/v1/quick").json()
        assert (quick["inbox"], quick["processing"]) == (0, 0), "the phone's numbers follow the same rule"


# --- Filing many ------------------------------------------------------------------------------------------------------------


def test_many_are_filed_with_a_kind_and_tags_for_all_and_each_is_checked_on_its_own(client: TestClient, operator: Account) -> None:
    _, _, vault = world(operator)
    invoice = next(k for k in client.get("/api/v1/kinds").json() if k["key"] == "invoice")
    a = inbox_doc(vault, operator, "A", tags=["strom"])
    b = inbox_doc(vault, operator, "B")
    reading = inbox_doc(vault, operator, "Reading", status="processing")
    done = add_document(vault, operator, "Done", content=None)
    foreign = inbox_doc(own_vault(make_account("other")), None, "Foreign")
    answer = client.post("/api/v1/inbox/file", json={"ids": [a, b, reading, done, foreign, a], "kind_id": invoice["id"],
                                                      "add_tags": ["Steuer", "STROM"]})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["filed"] == [a, b]
    assert {f["id"]: f["code"] for f in body["failed"]} == {reading: "still_processing", done: "not_in_inbox", foreign: "not_found"}
    for doc in (a, b):
        row = client.get(f"/api/v1/documents/{doc}").json()
        assert row["status"] == "filed" and row["kind"]["id"] == invoice["id"]
    assert sorted(client.get(f"/api/v1/documents/{a}").json()["tags"]) == ["Steuer", "strom"]
    assert sorted(client.get(f"/api/v1/documents/{b}").json()["tags"]) == ["Steuer", "strom"]
    assert document(reading).status == "processing"
    # What was filed leaves the inbox; the history says it was filed.
    assert get(client)["all"] == 1, "only the one being read is left"
    events = client.get(f"/api/v1/documents/{a}/events").json()
    assert events[0]["detail"]["fields"] == ["kind", "status", "tags"]


def test_a_reader_files_nothing_and_a_stranger_learns_nothing(client: TestClient, operator: Account) -> None:
    _, reader, vault = world(operator)
    doc = inbox_doc(vault, operator, "A")
    with new_client(reader) as session:
        body = session.post("/api/v1/inbox/file", json={"ids": [doc]}).json()
    assert body == {"filed": [], "failed": [{"id": doc, "code": "forbidden"}]}
    with new_client(make_account("stranger")) as session:
        body = session.post("/api/v1/inbox/file", json={"ids": [doc, 2**31 - 5]}).json()
    # Exactly the answer for a document that does not exist.
    assert body == {"filed": [], "failed": [{"id": doc, "code": "not_found"}, {"id": 2**31 - 5, "code": "not_found"}]}
    assert document(doc).status == "inbox"


def test_filing_into_another_vault_needs_the_right_in_both(client: TestClient, operator: Account) -> None:
    editor, _, vault = world(operator)
    mine = own_vault(editor)
    a = inbox_doc(mine, editor, "From the editor")
    with new_client(editor) as session:
        ok = session.post("/api/v1/inbox/file", json={"ids": [a], "vault_id": vault}).json()
        assert ok["filed"] == [a] and document(a).vault_id == vault
        b = inbox_doc(vault, editor, "Another")
        # `reader` has only read in the household's vault, so a move there is no way in; the editor's vault is theirs.
        stranger_vault = own_vault(operator)
        refused = session.post("/api/v1/inbox/file", json={"ids": [b], "vault_id": stranger_vault}).json()
    assert refused["filed"] == [] and refused["failed"][0]["code"] == "not_found"
    assert document(b).vault_id == vault and document(b).status == "inbox"


def test_a_kind_the_document_may_not_have_is_named_and_the_document_stays(client: TestClient, operator: Account) -> None:
    _, _, vault = world(operator)
    other = make_account("other")
    theirs = shared_vault("Theirs", other, (other, "manage"))
    with new_client(other) as session:
        foreign = session.post("/api/v1/kinds", json={"name": "Hidden", "vault_id": theirs}).json()
    doc = inbox_doc(vault, operator, "A")
    body = client.post("/api/v1/inbox/file", json={"ids": [doc], "kind_id": foreign["id"]}).json()
    assert body == {"filed": [], "failed": [{"id": doc, "code": "kind_unknown"}]}
    assert document(doc).status == "inbox"
    missing = client.post("/api/v1/inbox/file", json={"ids": [doc], "kind_id": 2**31 - 5}).json()
    assert missing == body, "a kind of another vault answers like one that does not exist"


def test_the_most_that_can_be_filed_at_once_is_capped(client: TestClient, operator: Account) -> None:
    answer = client.post("/api/v1/inbox/file", json={"ids": list(range(1, 202))})
    assert answer.status_code == 422
    assert client.post("/api/v1/inbox/file", json={"ids": []}).status_code == 422
    assert client.post("/api/v1/inbox/file", json={"ids": [1], "add_tags": ["x"] * 11}).status_code == 422
    assert client.post("/api/v1/inbox/file", json={"ids": [1], "extra": 1}).status_code == 422


def test_filing_twice_at_once_files_once(client: TestClient, operator: Account) -> None:
    vault = own_vault(operator)
    doc = inbox_doc(vault, operator, "Once")
    first = client.post("/api/v1/inbox/file", json={"ids": [doc]}).json()
    second = client.post("/api/v1/inbox/file", json={"ids": [doc]}).json()
    assert first["filed"] == [doc]
    assert second == {"filed": [], "failed": [{"id": doc, "code": "not_in_inbox"}]}
    filed_events = [e for e in client.get(f"/api/v1/documents/{doc}/events").json() if e["action"] == "changed"]
    assert len(filed_events) == 1


def test_a_refusal_after_the_move_would_come_leaves_the_document_untouched_in_its_old_vault(
        client: TestClient, operator: Account) -> None:
    one = shared_vault("One", operator, (operator, "manage"))
    two = shared_vault("Two", operator, (operator, "manage"))
    only_one = client.post("/api/v1/kinds", json={"name": "Only here", "vault_id": one}).json()
    full = [f"t{n}" for n in range(30)]
    cases = [
        ({"kind_id": only_one["id"]}, "kind_unknown", ["t"]),
        ({"kind_id": 2**31 - 5}, "kind_unknown", ["t"]),
        ({"add_tags": ["extra"]}, "too_many_tags", full),
        ({"add_tags": ["badtag"]}, "invalid_tag", ["t"]),
    ]
    for extra, code, tags in cases:
        doc = inbox_doc(one, operator, "Case", sender="Foo", tags=tags)
        body = client.post("/api/v1/inbox/file", json={"ids": [doc], "vault_id": two, **extra}).json()
        assert body == {"filed": [], "failed": [{"id": doc, "code": code}]}, extra
        after = document(doc)
        assert (after.vault_id, after.status, after.kind_id) == (one, "inbox", None), extra
        events = [e["action"] for e in client.get(f"/api/v1/documents/{doc}/events").json()]
        assert "moved" not in events, extra
    # The same kind into its own vault goes through, so the refusal above was about the target.
    ok = inbox_doc(one, operator, "Fine")
    assert client.post("/api/v1/inbox/file", json={"ids": [ok], "kind_id": only_one["id"]}).json()["filed"] == [ok]


def test_the_trash_count_of_the_menu_is_the_callers_own(client: TestClient, operator: Account) -> None:
    other = make_account("other")
    theirs = inbox_doc(own_vault(other), other, "Gone")
    with new_client(other) as session:
        assert session.delete(f"/api/v1/documents/{theirs}").status_code == 200
        assert session.get("/api/v1/counts").json()["trash"] == 1
    assert client.get("/api/v1/counts").json()["trash"] == 0
