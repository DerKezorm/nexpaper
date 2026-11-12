"""The floor of the proposals of "goes with": measured on made-up papers (``numbers_corpus.py``: at least 60 pairs that
go together and 200 papers that go with nothing), through the database as the app proposes them.

Measured on 12.11.2026 (six seeds of the corpus, 359 to 368 papers, 80 to 98 pairs each): 93 to 100 % of the pairs
found; without the rule about senders, 2.4 to 9.0 % of the proposals were wrong (small invoice numbers of different
senders alike), with it none. With the sender unknown on a quarter of the papers, 0 to 2.6 % wrong. The
floors below hold the result: a change that finds fewer pairs or proposes more wrong ones fails here. More than 5 %
wrong makes the rule narrower, never this floor softer.
"""

from __future__ import annotations

import random

import pytest

from app import clock
from app.db import SessionLocal
from app.models import FILED, Document, Version, VersionText
from app.services import catalog, changes, numbers, related, search_index

from .conftest import make_account
from .numbers_corpus import Corpus, corpus
from .papers import own_vault

#: At least this share of the pairs that go together is proposed.
FOUND_FLOOR = 0.90
#: At most this share of the proposals is wrong.
WRONG_CEILING = 0.05


def _store(corpus_: Corpus, *, unknown_sender: float, seed: int) -> tuple[int, list[int]]:
    """Every paper as a filed document with its text in one vault; the sender known for most of them."""
    jule = make_account("jule")
    vault = own_vault(jule)
    rng = random.Random(seed)
    ids: list[int] = []
    with SessionLocal() as db:
        changes.write_lock(db)
        for index, paper in enumerate(corpus_.papers):
            document = Document(vault_id=vault, owner_id=jule.id, title=f"Beleg {index}", status=FILED, source="upload",
                                added_at=clock.now(), pages=1, change_seq=changes.next_seq(db))
            if rng.random() >= unknown_sender:
                document.sender_id = catalog.sender_named(db, vault, jule.id, paper.sender).id
            db.add(document)
            db.flush()
            version = Version(document_id=document.id, n=1, original_path=f"x/{document.id}.pdf", sha256="0" * 64,
                              size=1, pages=1, created_by=jule.id, created_at=clock.now(), note="upload")
            db.add(version)
            db.flush()
            db.add(VersionText(version_id=version.id, document_id=document.id, text=paper.text, pages=1, ocr_pages=0,
                               languages="deu", digest=search_index.text_digest(paper.text), created_at=clock.now()))
            ids.append(document.id)
        db.commit()
    with SessionLocal() as db:
        changes.write_lock(db)
        numbers.refresh(db, ids)
        db.commit()
    return jule.id, ids


def measure(seed: int, unknown_sender: float = 0.0) -> tuple[int, int, int]:
    """(pairs that go together, of them proposed, proposals that are wrong)."""
    papers = corpus(seed)
    uid, ids = _store(papers, unknown_sender=unknown_sender, seed=seed)
    index_of = {document_id: index for index, document_id in enumerate(ids)}
    with SessionLocal() as db:
        found = related.suggestions(db, uid, ids)
    proposed = {tuple(sorted((index_of[a], index_of[s.document.id]))) for a, items in found.items() for s in items}
    truth = papers.true_pairs()
    return len(truth), len(proposed & truth), len(proposed - truth)


@pytest.mark.parametrize("seed", [15, 1, 2])
def test_the_proposals_find_the_pairs_and_hardly_anything_else(client: object, seed: int) -> None:
    truth, found, wrong = measure(seed)
    assert truth >= 60
    assert found / truth >= FOUND_FLOOR, (seed, truth, found, wrong)
    assert wrong / max(1, found + wrong) <= WRONG_CEILING, (seed, truth, found, wrong)


def test_with_senders_unknown_the_wrong_ones_stay_under_the_ceiling(client: object) -> None:
    truth, found, wrong = measure(15, unknown_sender=0.25)
    assert found / truth >= FOUND_FLOOR - 0.05, (truth, found, wrong)
    assert wrong / max(1, found + wrong) <= WRONG_CEILING, (truth, found, wrong)


def test_the_corpus_is_what_the_measurement_needs() -> None:
    made = corpus(15)
    assert len(made.true_pairs()) >= 60
    assert sum(1 for paper in made.papers if paper.group is None) >= 200
    # German and English, and papers written as a scan reads them.
    texts = "\n".join(paper.text for paper in made.papers)
    assert "Rechnungsnummer" in texts and "Invoice" in texts and "Lieferschein" in texts and "Delivery note" in texts
    assert "O" in "".join(line.split()[-1] for line in texts.split("\n") if line.startswith("Rechnungsnummer"))
