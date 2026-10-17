"""A floor under the search (a measurement at a size a test can afford): 5,000 made-up
documents of about 4 KB of text each, indexed by the real code, searched by the real code for three people with
different rights. The limits are generous on purpose (measured: tens of milliseconds a search, about 17 KB of index
per document), so that this only turns red when something got worse by a lot: a search that reads every text, an
index that doubled."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.services import search, search_index
from tools import search_bench

COUNT = 5000
#: Seconds one search may take here (measured: well under 0.2).
MOST_SECONDS = 2.0
#: Bytes of index per document (measured: about 17,000 with the trigram index over everything).
MOST_INDEX_BYTES = 40_000


@pytest.fixture(scope="module")
def bench(tmp_path_factory: pytest.TempPathFactory) -> tuple[object, dict]:
    folder: Path = tmp_path_factory.mktemp("floor")
    info = search_bench.build_base(folder / "base.db", COUNT)
    engine = search_bench.engine_for(folder / "base.db")
    search_bench.checkpoint(engine)
    before = search_bench.size_of(folder / "base.db")
    with sessionmaker(bind=engine)() as db:
        assert search_index.run_job(db) == COUNT
    search_bench.checkpoint(engine)
    info["index_bytes"] = search_bench.size_of(folder / "base.db") - before
    yield engine, info
    engine.dispose()


def test_the_index_of_5000_documents_stays_small(bench: tuple[object, dict]) -> None:
    _engine, info = bench
    assert info["index_bytes"] / COUNT < MOST_INDEX_BYTES, info["index_bytes"]


@pytest.mark.parametrize("label, query", search_bench.QUERIES)
def test_every_kind_of_search_answers_quickly_for_every_kind_of_person(bench: tuple[object, dict], label: str,
                                                                      query: str) -> None:
    engine, info = bench
    with sessionmaker(bind=engine)() as db:
        for who in ("anna", "ben", "carla"):
            search.find(db, info["ids"][who], query, search.Filters())  # warm
            began = time.perf_counter()
            result = search.find(db, info["ids"][who], query, search.Filters(), limit=50)
            took = time.perf_counter() - began
            assert took < MOST_SECONDS, (label, who, took)
            assert len(result.hits) == min(50, result.total)
    # The one who sees everything finds the common word nearly everywhere (the floor is not measured on nothing).
    with sessionmaker(bind=engine)() as db:
        assert search.find(db, info["ids"]["carla"], "rechnung", search.Filters()).total > COUNT * 0.9
