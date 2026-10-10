"""The measurement behind the search: how large the database grows and how fast a search answers, with many documents.

Made-up documents only (invoices, letters, contracts of invented senders, about 4 KB of German text each, with numbers
as a scan has them), written into the real tables, indexed by the real code (``services/search_index.run_job``) and
searched by the real code (``services/search.find``), for three people with different rights. Nothing is read from or
written to a real nexpaper.

    python tools/search_bench.py --documents 200000 --folder <empty folder>
    python tools/search_bench.py --documents 5000 --folder <folder> --keep

Earlier versions of this script compared ways of finding a part of a word (word index only, trigrams over the metadata
only, trigrams without positions); ``docs/search.md`` keeps those numbers. It now measures what nexpaper does: word
index and trigram index over everything, each entry with its scope.

The base database (documents without index) is made once and kept in the folder (``base.db``); the measurement works
on a copy (``indexed.db``, kept with ``--keep``). Run it from ``backend/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
# The app's own data folder is never touched: the bench opens engines of its own.
os.environ.setdefault("NEXPAPER_DATA_DIR", tempfile.mkdtemp(prefix="nexpaper-bench-"))
os.environ.setdefault("NEXPAPER_DISABLE_BACKGROUND", "1")

from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app import models  # noqa: E402
from app.models import Account, Base, Vault, VaultMember  # noqa: E402
from app.services import changes, search, search_index, searchtext  # noqa: E402

# --- Made-up words ----------------------------------------------------------------------------------------------------

SENDERS = [
    "Stadtwerke Lindenau", "Hansa Versicherung", "Autohaus Kessler", "Praxis am Markt", "Finanzamt Lindenau",
    "Telekabel Nord", "Wohnbau Lindenau eG", "Elektro Brandt", "Bäckerei Sonnenschein", "Zahnarztpraxis Weißdorn",
    "Gemeindewerke Birkenfeld", "Nordlicht Energie", "Kreissparkasse Lindenau", "Volksbank Mühlental",
    "Optik Klarblick", "Fahrradladen Speiche", "Gartenbau Grünzweig", "Musikschule Taktvoll", "Grundschule am Weiher",
    "Kita Sonnenblume",
    "Tierarztpraxis Pfote", "Physiotherapie Bewegt", "Apotheke am Rathaus", "Möbelhaus Eiche", "Baumarkt Hammerschmidt",
    "Reisebüro Fernweh", "Landratsamt Birkenfeld", "Bürgeramt Lindenau", "Rundfunkbeitrag Service",
    "Krankenkasse Aurora",
    "Rentenkasse Mitte", "Familienkasse Nord", "Steuerbüro Zahlenwerk", "Hausverwaltung Ziegel", "Schornsteinfeger Ruß",
    "Abfallwirtschaft Lindenau", "Wasserverband Mühlbach", "Mobilfunk Welle", "Versandhaus Paketfix", "Kaufhaus Mitte",
]
STREETS = ["Lindenallee", "Am Mühlbach", "Birkenweg", "Marktplatz", "Weiherstraße", "Eichenring", "Rosengasse",
           "Am Rathaus", "Bahnhofstraße", "Hauptstraße", "Schulweg", "Gartenstraße"]
TOWNS = ["Lindenau", "Birkenfeld", "Mühlental", "Weiherdorf", "Eichstein"]
PREFIXES = ["Strom", "Gas", "Wasser", "Heiz", "Miet", "Kranken", "Haftpflicht", "Hausrat", "Kfz", "Lohn", "Einkommen",
            "Umsatz", "Jahres", "Monats", "Abschlags", "Zahlungs", "Vertrags", "Kunden", "Rechnungs", "Versicherungs",
            "Steuer", "Konto", "Zähler", "Grund", "Arbeits", "Netz", "Telefon", "Internet", "Garantie", "Wartungs",
            "Reparatur", "Liefer", "Bestell", "Rück", "Mahn", "Neben", "Betriebs", "Beitrags", "Schaden", "Kinder",
            "Schul", "Bau", "Energie", "Müll", "Abwasser"]
SUFFIXES = ["abschlag", "rechnung", "vertrag", "nummer", "stand", "preis", "kosten", "gebühr", "beitrag", "bescheid",
            "erstattung", "zeitraum", "konto", "termin", "frist", "betrag", "übersicht", "abrechnung", "versicherung",
            "leistung", "anschluss", "tarif", "bedingungen", "kündigung", "schein", "meldung", "auftrag", "bestätigung",
            "verbrauch", "zuschlag"]
COMMON = [
    "der", "die", "das", "und", "in", "zu", "den", "von", "mit", "ist", "im", "für", "auf", "dem", "nicht", "ein",
    "eine", "als", "auch", "es", "an", "werden", "aus", "er", "hat", "dass", "sie", "nach", "wird", "bei",
    "einer", "um", "am", "sind", "noch", "wie", "einem", "über", "einen", "so", "zum", "war", "haben", "nur",
    "oder", "aber", "vor", "zur", "bis", "mehr", "durch", "man", "sein", "wurde", "sei", "ihre", "ihr", "ihnen",
    "wir", "bitte", "uns", "unser", "unsere", "sehr", "geehrte", "damen", "herren", "mit", "freundlichen",
    "grüßen", "hiermit", "erhalten", "sie", "folgende", "angaben", "gemäß", "vereinbarung", "zahlung", "fällig",
    "innerhalb", "tagen", "überweisen", "betrag", "konto", "verwendungszweck", "angeben", "rückfragen",
    "erreichen", "montag", "freitag", "uhr", "telefon", "fragen", "gern", "weiterhin", "vielen", "dank",
    "vertrauen", "ihr", "team", "anlage", "seite", "von", "bis", "zeitraum", "monat", "januar", "februar", "märz",
    "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember", "euro", "netto",
    "brutto", "mehrwertsteuer", "summe", "gesamt", "position", "menge", "einzelpreis", "kunde", "kundin",
    "vertragsnummer", "zählernummer", "verbrauchsstelle", "lieferadresse", "rechnungsadresse", "frist",
    "kündigung", "laufzeit", "verlängert", "automatisch", "schriftlich", "änderungen", "vorbehalten",
]
SYLLABLES = ["ka", "lo", "mi", "ber", "an", "tro", "sel", "wen", "dor", "fu", "gra", "hel", "is", "jo", "kre", "lun",
             "mar", "nes", "or", "pla", "quin", "ros", "sta", "tem", "ul", "vok", "wis", "zel", "ech", "uft", "ing",
             "ert", "ach", "ö", "ü", "ä", "ß", "sch", "pf", "nk"]


def vocabulary(rng: random.Random) -> tuple[list[str], list[float]]:
    """About 25,000 words with a long tail, weighted like a language (Zipf): common words first, compounds, rare
    words that stand for names and misread letters."""
    compounds = [p + s for p in PREFIXES for s in SUFFIXES]
    rare = set()
    while len(rare) < 22_000:
        rare.add("".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 5))))
    words = COMMON + compounds + sorted(rare)
    weights = [1.0 / (rank + 8) ** 1.05 for rank in range(len(words))]
    total = 0.0
    cumulative = []
    for weight in weights:
        total += weight
        cumulative.append(total)
    return words, cumulative


def made_up_text(rng: random.Random, words: list[str], cumulative: list[float], sender: str, number: int,
                 size: int = 4000) -> str:
    """One document of about ``size`` characters, in pages of about 2,000."""
    street = rng.choice(STREETS)
    town = rng.choice(TOWNS)
    head = (f"{sender}\n{street} {rng.randint(1, 120)}, {rng.randint(10000, 99999)} {town}\n"
            f"Kundennummer K-{rng.randint(10**7, 10**8 - 1)} Rechnungsnummer R-{2020 + number % 7}-{number:06d}\n"
            f"Datum {rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.{2020 + number % 7} "
            f"IBAN DE{rng.randint(10, 99)} {rng.randint(1000, 9999)} {rng.randint(1000, 9999)} "
            f"{rng.randint(1000, 9999)} {rng.randint(1000, 9999)} {rng.randint(10, 99)}\n"
            f"Betrag {rng.randint(1, 2000)},{rng.randint(0, 99):02d} EUR. Bitte überweisen Sie den Betrag bis zum "
            f"{rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.\n")
    parts = [head]
    length = len(head)
    while length < size:
        sentence = rng.choices(words, cum_weights=cumulative, k=rng.randint(6, 16))
        if rng.random() < 0.3:
            sentence.append(f"{rng.randint(1, 9999)},{rng.randint(0, 99):02d}")
        line = " ".join(sentence).capitalize() + ". "
        parts.append(line)
        length += len(line)
    body = "".join(parts)
    middle = len(body) // 2
    cut = body.find(" ", middle)
    return body[:cut] + "\f" + body[cut + 1 :] if cut > 0 else body


# --- The base database ------------------------------------------------------------------------------------------------

PEOPLE = 20
VAULTS = 200
#: The three people the searches are made for: a member of 40 vaults, of one vault with 50 documents shared with them,
#: and of all of them.
ANNA_VAULTS, BEN_SHARES = 40, 50


def engine_for(path: Path) -> Any:
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool, connect_args={"timeout": 60})

    @event.listens_for(engine, "connect")
    def _pragmas(connection: Any, _record: Any) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def build_base(path: Path, count: int, seed: int = 7) -> dict[str, Any]:
    rng = random.Random(seed)
    words, cumulative = vocabulary(rng)
    engine = engine_for(path)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    with maker() as db:
        people = [Account(name=f"person{n:02d}", role="member") for n in range(PEOPLE)]
        db.add_all(people)
        db.flush()
        vaults = [Vault(name=f"Vault {n:03d}", folder=f"vault-{n:03d}", icon="folder") for n in range(VAULTS)]
        db.add_all(vaults)
        db.flush()
        anna, ben, carla = people[0], people[1], people[2]
        for index, vault in enumerate(vaults):
            members = {carla.id: "read"}
            if index < ANNA_VAULTS:
                members[anna.id] = "edit"
            if index == 0:
                members[ben.id] = "read"
            members[people[3 + index % (PEOPLE - 3)].id] = "manage"
            for uid, right in members.items():
                db.add(VaultMember(vault_id=vault.id, user_id=uid, right=right))
        db.commit()
        vault_ids = [v.id for v in vaults]
        ids = {"anna": anna.id, "ben": ben.id, "carla": carla.id, "owners": [p.id for p in people]}
    raw = engine.raw_connection()
    cursor = raw.cursor()
    cursor.execute("BEGIN")
    sender_ids: dict[tuple[int, str], int] = {}
    tag_names = ["auto", "haus", "steuer2025", "steuer2026", "garantie", "wichtig", "kinder", "arzt", "strom", "bank"]
    tag_ids: dict[tuple[int, str], int] = {}
    for vault_id in vault_ids:
        for name in rng.sample(SENDERS, 30):
            cursor.execute("INSERT INTO senders (vault_id, name, key) VALUES (?, ?, ?)",
                           (vault_id, name, searchtext.fold(name)))
            sender_ids[(vault_id, name)] = cursor.lastrowid
        for name in tag_names:
            cursor.execute("INSERT INTO tags (vault_id, name, key) VALUES (?, ?, ?)", (vault_id, name, name))
            tag_ids[(vault_id, name)] = cursor.lastrowid
    kinds = []
    for position, (key, name) in enumerate([("invoice", "Rechnung"), ("contract", "Vertrag"),
                                            ("insurance", "Versicherung"), ("tax", "Steuer"), ("other", "Sonstiges")]):
        cursor.execute("INSERT INTO kinds (key, name, name_key, hue, position) VALUES (?, ?, ?, 30, ?)",
                       (key, name, searchtext.fold(name), position))
        kinds.append(cursor.lastrowid)
    stamp = now.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    began = time.perf_counter()
    for number in range(1, count + 1):
        vault_id = vault_ids[number % VAULTS]
        sender = rng.choice([name for (v, name) in sender_ids if v == vault_id][:30])
        body = made_up_text(rng, words, cumulative, sender, number)
        day = (date(2018, 1, 1) + timedelta(days=rng.randint(0, 3200))).isoformat()
        title = f"{rng.choice(PREFIXES)}{rng.choice(SUFFIXES)} {rng.choice(COMMON[100:])}".capitalize()
        status = "inbox" if number % 50 == 0 else "trash" if number % 97 == 0 else "filed"
        cursor.execute(
            "INSERT INTO documents (id, vault_id, owner_id, title, sender_id, kind_id, date, amount, currency, status, "
            "source, added_at, pages, current_version, change_seq, trashed_status, duplicate_kind, process_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'EUR', ?, 'upload', ?, 2, 1, ?, '', '', '')",
            (number, vault_id, rng.choice(ids["owners"]), title, sender_ids[(vault_id, sender)], rng.choice(kinds),
             day, rng.randint(100, 300000), status, stamp, number),
        )
        cursor.execute(
            "INSERT INTO versions (id, document_id, n, original_path, archive_path, sha256, size, pages, created_at, "
            "note, phash) VALUES (?, ?, 1, ?, '', ?, 1000, 2, ?, '', '')",
            (number, number, f"v{vault_id}/{number}.pdf", hashlib.sha256(str(number).encode()).hexdigest(), stamp),
        )
        cursor.execute(
            "INSERT INTO version_texts (version_id, document_id, text, pages, ocr_pages, languages, digest, "
            "created_at) VALUES (?, ?, ?, 2, 2, 'deu', ?, ?)",
            (number, number, body, search_index.text_digest(body), stamp),
        )
        for name in rng.sample(tag_names, rng.randint(0, 2)):
            cursor.execute("INSERT INTO document_tags (document_id, tag_id) VALUES (?, ?)",
                           (number, tag_ids[(vault_id, name)]))
        if number % 20 == 0:
            cursor.execute("INSERT INTO notes (document_id, user_id, text, created_at) VALUES (?, ?, ?, ?)",
                           (number, ids["anna"], "Mit dem Steuerberater besprochen, Kopie im Ordner Garage.", stamp))
        if number % 10_000 == 0:
            raw.commit()
            cursor.execute("BEGIN")
            print(f"  {number} documents written, {time.perf_counter() - began:.0f} s", flush=True)
    # Ben sees one vault and 50 documents of others, one by one.
    for document_id in rng.sample(range(1, count + 1), min(BEN_SHARES, count)):
        cursor.execute(
            "INSERT OR IGNORE INTO shares (document_id, user_id, right, created_at) VALUES (?, ?, 'read', ?)",
            (document_id, ids["ben"], stamp))
    cursor.execute("INSERT INTO counters (name, value) VALUES ('change_seq', ?)", (count,))
    raw.commit()
    cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw.close()
    engine.dispose()
    (path.parent / "base.json").write_text(json.dumps({"count": count, "ids": ids}), encoding="utf-8")
    return {"count": count, "ids": ids}


# --- The measurement ---------------------------------------------------------------------------------------------

QUERIES = [
    ("one common word", "rechnung"),
    ("one rare word", "kessler"),
    ("two words", "stadtwerke abschlag"),
    ("part of a word", "werke"),
    ("part inside the text", "abschlag"),
    ("phrase", '"bitte überweisen"'),
    ("number", "R-2023-001234"),
    ("filters only", "art:rechnung betrag:>100"),
    ("word and filters", "strom art:rechnung absender:stadtwerke"),
    ("short word", "zu"),
    ("nothing found", "xylophonkonzert"),
]


def size_of(path: Path) -> int:
    return path.stat().st_size + sum(p.stat().st_size for p in path.parent.glob(path.name + "-*"))


def checkpoint(engine: Any) -> None:
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")


def measure(folder: Path, info: dict[str, Any], runs: int) -> dict[str, Any]:
    target = folder / "indexed.db"
    for leftover in folder.glob(target.name + "*"):
        leftover.unlink()
    shutil.copyfile(folder / "base.db", target)
    engine = engine_for(target)
    with engine.begin() as connection:
        for table in ("doc_fts", "doc_tri"):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        for statement in models.SEARCH_STATEMENTS[:2]:
            connection.exec_driver_sql(statement)
    checkpoint(engine)
    empty = size_of(target)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    began = time.perf_counter()
    with maker() as db:
        written = search_index.run_job(db)
    indexing = time.perf_counter() - began
    checkpoint(engine)
    indexed = size_of(target)
    result: dict[str, Any] = {
        "documents": info["count"], "written": written,
        "index_seconds": round(indexing, 1), "index_ms_per_document": round(indexing * 1000 / max(written, 1), 2),
        "db_bytes": indexed, "index_bytes": indexed - empty,
    }
    # One change at a time, as a person makes them: a title changed, the index follows before the commit.
    rng = random.Random(3)
    singles = []
    with maker() as db:
        for document_id in rng.sample(range(1, info["count"] + 1), 100):
            began = time.perf_counter()
            changes.write_lock(db)
            seq = changes.next_seq(db)
            db.execute(text("UPDATE documents SET title = title || ' x', change_seq = :seq WHERE id = :id"),
                       {"seq": seq, "id": document_id})
            db.commit()
            singles.append((time.perf_counter() - began) * 1000)
    result["change_ms_median"] = round(statistics.median(singles), 2)
    result["change_ms_max"] = round(max(singles), 2)
    people = info["ids"]
    timings: dict[str, dict[str, Any]] = {}
    with maker() as db:
        for label, raw in QUERIES:
            for who in ("anna", "ben", "carla"):
                times = []
                found = None
                for _ in range(runs):
                    began = time.perf_counter()
                    found = search.find(db, people[who], raw, search.Filters(), limit=50)
                    times.append((time.perf_counter() - began) * 1000)
                timings.setdefault(label, {"query": raw})[who] = {
                    "ms": round(statistics.median(times), 1), "total": found.total if found else 0}
    result["searches"] = timings
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO doc_fts(doc_fts) VALUES ('optimize')")
        connection.exec_driver_sql("INSERT INTO doc_tri(doc_tri) VALUES ('optimize')")
    with engine.connect() as connection:
        connection.exec_driver_sql("VACUUM")
    checkpoint(engine)
    result["db_bytes_optimized"] = size_of(target)
    result["index_bytes_optimized"] = size_of(target) - empty
    engine.dispose()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Search measurement with made-up documents.")
    parser.add_argument("--documents", type=int, default=5000)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--keep", action="store_true", help="keep the indexed database")
    args = parser.parse_args()
    folder: Path = args.folder
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / "base.db"
    meta = folder / "base.json"
    info = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() and base.is_file() else None
    if info is None or info["count"] != args.documents:
        for leftover in folder.glob("base.db*"):
            leftover.unlink()
        print(f"Writing {args.documents} made-up documents ...", flush=True)
        began = time.perf_counter()
        info = build_base(base, args.documents)
        print(f"  done in {time.perf_counter() - began:.0f} s", flush=True)
    engine = engine_for(base)
    with engine.connect() as connection:
        text_bytes = connection.exec_driver_sql("SELECT sum(length(CAST(text AS BLOB))) FROM version_texts").scalar()
    engine.dispose()
    print("Indexing and searching ...", flush=True)
    outcome = measure(folder, info, args.runs)
    results = {"documents": info["count"], "text_bytes": text_bytes, "base_bytes": size_of(base), **outcome}
    print(json.dumps(outcome, ensure_ascii=False), flush=True)
    if not args.keep:
        for leftover in folder.glob("indexed.db*"):
            leftover.unlink()
    (folder / f"results-{info['count']}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                                         encoding="utf-8")
    print(json.dumps({k: v for k, v in results.items() if k != "searches"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
