"""The small pictures of a long document, drawn in the background after it was read: behind every document that waits to
be read, in batches, up to the operator's limit, and for the version the document stands at."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Document, Job
from app.services import jobs, pages

from . import files
from .intake import limit, process_all, upload_one

# Pages that carry text of their own: no recognition needed, the worker only counts and draws.
LONG = files.make_pdf([f"Seite {n} der langen Abrechnung mit genug Text darauf" for n in range(1, 46)])
SHORT = files.make_pdf(["Ein kurzer Brief mit genug Text darauf, eine Seite"])


def drawn(document_id: int, version: int = 1) -> list[int]:
    """The small pages in the cache, by number."""
    folder = pages.document_dir(document_id)
    if not folder.is_dir():
        return []
    found = []
    for path in folder.glob(f"v{version}-p*-small.webp"):
        found.append(int(path.name.split("-p")[1].split("-")[0]))
    return sorted(found)


def page_jobs(document_id: int) -> list[Job]:
    with SessionLocal() as db:
        return list(db.scalars(select(Job).where(Job.kind == jobs.PAGES, Job.ref == document_id).order_by(Job.id)))


def test_a_long_document_has_its_small_pages_drawn_after_it_was_read_in_batches(
        client: TestClient, operator: object) -> None:
    made = upload_one(client, "Abrechnung.pdf", LONG)
    process_all(rounds=20)
    with SessionLocal() as db:
        assert db.get(Document, made["id"]).pages == 45  # type: ignore[union-attr]
    assert drawn(made["id"]) == list(range(1, 46))
    # 20, 20 and 5: three runs of the worker, each a job of its own, so a new document can go between them.
    assert [job.state for job in page_jobs(made["id"])] == ["done", "done", "done"]
    assert [(job.payload or {}).get("next") for job in page_jobs(made["id"])] == [1, 21, 41]


def test_a_short_document_needs_no_job_the_worker_drew_its_pages_while_reading(
        client: TestClient, operator: object) -> None:
    made = upload_one(client, "Brief.pdf", SHORT)
    process_all()
    assert drawn(made["id"]) == [1]
    assert page_jobs(made["id"]) == []


def test_documents_that_wait_to_be_read_go_before_the_pictures_of_another(
        client: TestClient, operator: object) -> None:
    first = upload_one(client, "Abrechnung.pdf", LONG)
    assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1  # the long one is read; its pictures wait
    assert drawn(first["id"]) == []
    second = upload_one(client, "Brief.pdf", SHORT)
    # One more run of the slow loop: the new document, although the job for the pictures is older.
    assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1
    with SessionLocal() as db:
        assert db.get(Document, second["id"]).status == "inbox"  # type: ignore[union-attr]
    assert drawn(first["id"]) == []
    assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1
    assert drawn(first["id"]) == list(range(1, 21))
    # A third document arrives between two batches: it goes first again.
    third = upload_one(client, "Noch ein Brief.pdf", SHORT)
    assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1
    with SessionLocal() as db:
        assert db.get(Document, third["id"]).status == "inbox"  # type: ignore[union-attr]
    assert drawn(first["id"]) == list(range(1, 21))


def test_the_operator_limits_how_many_pages_are_drawn_ahead(client: TestClient, operator: object) -> None:
    limit(prerender_max_pages=25)
    made = upload_one(client, "Abrechnung.pdf", LONG)
    process_all(rounds=20)
    assert drawn(made["id"]) == list(range(1, 26))
    # The others are drawn when somebody asks for them.
    assert client.get(f"/api/v1/documents/{made['id']}/versions/1/pages/40").status_code == 200
    assert drawn(made["id"]) == [*range(1, 26), 40]


def test_no_pages_drawn_ahead_when_the_operator_says_none(client: TestClient, operator: object) -> None:
    limit(prerender_max_pages=0)
    made = upload_one(client, "Abrechnung.pdf", LONG)
    process_all(rounds=20)
    assert drawn(made["id"]) == []
    assert all(job.state == "done" for job in page_jobs(made["id"]))


def test_the_limit_is_part_of_the_storage_settings(client: TestClient, operator: object) -> None:
    assert client.get("/api/v1/settings").json()["prerender_max_pages"] == 500
    answer = client.put("/api/v1/settings", json={"prerender_max_pages": 120})
    assert answer.status_code == 200 and answer.json()["prerender_max_pages"] == 120
    assert client.put("/api/v1/settings", json={"prerender_max_pages": 20001}).status_code == 422
    assert client.put("/api/v1/settings", json={"prerender_max_pages": -1}).status_code == 422


def test_a_job_of_an_earlier_version_draws_the_current_one_from_its_first_page(
        client: TestClient, operator: object) -> None:
    limit(prerender_max_pages=30)
    made = upload_one(client, "Abrechnung.pdf", LONG)
    process_all(rounds=20)
    for path in pages.document_dir(made["id"]).glob("v1-p*-small.webp"):
        path.unlink()
    with SessionLocal() as db:
        # Queued for version 0 (an older one) at page 21: the current version is drawn from page 1.
        jobs.enqueue(db, jobs.PAGES, made["id"], {"version": 0, "next": 21})
        db.commit()
    process_all(rounds=20)
    assert drawn(made["id"]) == list(range(1, 31))


def test_nothing_is_drawn_for_a_document_in_the_trash_or_gone(client: TestClient, operator: object) -> None:
    made = upload_one(client, "Abrechnung.pdf", LONG)
    assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1
    assert client.delete(f"/api/v1/documents/{made['id']}").status_code == 200
    process_all(rounds=20)
    assert drawn(made["id"]) == []
    with SessionLocal() as db:
        jobs.enqueue(db, jobs.PAGES, 999_999, {"version": 1, "next": 1})
        db.commit()
    process_all()


def test_pages_already_in_the_cache_are_not_drawn_again(client: TestClient, operator: object,
                                                         monkeypatch: Any) -> None:
    made = upload_one(client, "Abrechnung.pdf", LONG)
    assert jobs.run_pending(limit=1, kinds=jobs.SLOW) == 1
    # Somebody looked at page 3 before the background got to it.
    assert client.get(f"/api/v1/documents/{made['id']}/versions/1/pages/3").status_code == 200
    before = pages.page_path(made["id"], 1, 3, "small").stat().st_mtime_ns
    process_all(rounds=20)
    assert pages.page_path(made["id"], 1, 3, "small").stat().st_mtime_ns == before
    assert drawn(made["id"]) == list(range(1, 46))
