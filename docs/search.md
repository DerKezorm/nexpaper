# Search: how it is built and what it costs

The plan said: SQLite holds the assignment of documents, their text and the search index, and that holds up over years
(a household with 1,000 documents a year, a small business with 20,000). Before the search was built this was measured
with made-up documents (`backend/tools/search_bench.py`): 200,000 documents with about 4 KB of German text each (invoices,
letters, contracts of invented senders, with the numbers a scan carries), written into the real tables, indexed by the
real code and searched by the real code for three people: Anna (member of 40 of 200 vaults), Ben (one vault and 50
documents shared with him) and Carla (all 200 vaults).

    python tools/search_bench.py --documents 200000 --folder <empty folder>

(The comparison of the variants below was made with an earlier version of the script, which could switch them.)
Measured on the Windows development machine (Python 3.14, SQLite 3.50), the machine busy with other work at the same
time, so the times are an upper bound.

## What the index costs

| | 5,000 documents | 200,000 documents | per document |
|---|---|---|---|
| Text (UTF-8) | 21 MB | 825 MB | 4.1 KB |
| Database without index | 26 MB | 1.02 GB | 5.1 KB |
| Word index (`doc_fts`, FTS5 `unicode61`) | 14 MB | 464 MB | 2.3 KB |
| Trigram index over title, sender, notes, tags only | +1 MB | +41 MB | 0.2 KB |
| Trigram index over everything, text included | +70 MB | +2.70 GB | 13.5 KB |
| Trigram index over everything without positions (`detail=none`) | +7 MB | not measured | 1.5 KB |
| **Database with word index and full trigram index** | 110 MB | **4.18 GB** | **21 KB** |
| Indexing a document (both indexes, in batches of 200) | 1.9 ms | 5.5 ms | |
| A change to one document (the index follows before the commit) | | median 18 ms, at most 76 ms | |

`optimize` and `VACUUM` save under 1 %: the index stays at its size.

## How fast a search answers (200,000 documents)

Median of three runs (the final one: five), for the whole answer: count, the first 50 documents newest first, their
excerpts and marks, for Carla (Anna and Ben within a tenth of that: the time follows the words, not the rights). The
final column is the code as it is now, measured while other work ran on the machine (indexing took 8.2 ms per document
there against 5.5 ms in the first run): take it as an upper bound.

| Search | finds (Carla) | word index only | full trigram, first run | full trigram, final |
|---|---|---|---|---|
| one common word (`rechnung`) | 198,000 | 0.45 s | 1.0 s | 1.4 s |
| one rare word (`kessler`) | 5,000 | 0.06 s | 0.10 s | 0.15 s |
| two words | 4,500 | 0.19 s | 0.25 s | 0.45 s |
| part of a word (`werke`) | 10,000 | **not found** | 0.14 s | 0.23 s |
| part inside the text (`abschlag`) | 197,600 | 181,300 found (prefix only) | 0.9 s | 1.3 s |
| phrase (`"bitte überweisen"`) | 198,000 | 0.35 s | 0.35 s | 0.41 s |
| filters only (`art:rechnung betrag:>100`) | 38,000 | 2.7 s | 2.7 s | **0.26 s** |
| word and filters | 1,000 | 0.75 s | 0.58 s | 0.70 s |
| nothing found | 0 | 2 ms | 3 ms | 2 ms |

The variant "trigram without positions" (each candidate checked against its text) took 4 seconds already with 5,000
documents for a common word: out.

The filter searches were slow for a person in many vaults: SQLite fetched the documents vault by vault through the index
(2.7 s for Carla). The search now compares the vault on every row (`vault_id + 0`, `services/search.py`); measured on
the same 200,000 documents, `art:rechnung betrag:>100` straight in SQLite: count and page 1.7 s each down to 0.1 s for
Carla, 0.3 s down to 0.07 s for Anna, 0.1 s down to 0.075 s for a member of a few vaults. A sort index on the date was tried and dropped: it made the common case instant and a rare filter 1.7 s.

## Decision

**The trigram index covers everything, the text included.** Reasons:

* Words in German documents are compounds. With the word index alone `abschlag` finds "Abschlag" but not
  "Stromabschlag", `versicherung` not "Haftpflichtversicherung", `nummer` not "Kundennummer": in the measurement the
  search for `abschlag` missed one document in ten. The mock promises "Teile von Wörtern gehen auch".
* The cost meets the plan's own estimate (20 to 30 KB per document with its index): 21 KB. A household with 1,000
  documents a year has about 210 MB after ten years; a small business with 20,000 a year about 4.2 GB.
* At 200,000 documents the worst case (a word or part of a word in nearly every document) takes one to one and a half
  seconds, a word that is not everywhere a tenth to half a second, filters a quarter of a second, and nothing found a
  few milliseconds. A household's archive is a twentieth of that.
* The trigram index only over title, sender, notes and tags would save 2.7 GB at 200,000 documents and lose parts of
  words in the text. That is the way back if the size ever matters more than compounds: the index code does not change,
  only what `services/search_index.py` writes into `doc_tri`.

Both indexes are contentless (`content=''`, `contentless_delete=1`): neither keeps a copy of the text, which is stored
once in `version_texts`. The excerpt and the marks are made in Python from that text.

**Floor:** `tests/test_search_floor.py` builds 5,000 of these documents in every test run and fails when a search takes
more than 2 seconds or the index more than 40 KB per document (measured: well under 0.2 s, 17 KB).

**For the backups (B10):** the database of a large archive is mostly index. A backup could leave `doc_fts` and `doc_tri`
out and rebuild them after a restore (the job `index` does that for any document without a current entry).

## Rights and what the time tells

The rights are in the index and in the query. Each entry of `doc_fts` and `doc_tri` carries a column `scope` with the
token of its vault (`v12v`) and one for each person it is shared with (`u7u`); a search asks the index for
`{scope}: (the caller's vaults OR their own token) AND {content}: (the words)`, so the entries of documents the caller
cannot see are never read and never counted. The query that finds and counts carries the rights once more, so the
number, the order and the excerpts follow only what the caller may see (tested with 300 foreign documents that match
better; a random sequence of changes, shares, moves and members checked against a brute-force oracle after each step).
The scope follows a move and a share (both take a change number); a person who joins or leaves a vault changes only the
tokens the search asks for.

What is left of the time: the index still looks up whether a word (or a trigram) exists anywhere on the server before it
narrows to the scope. The reviewer of B3 measured how a person in one vault could tell, from the time, whether a name
stands in a document in somebody else's vault (20,000 documents, the word in 1 or 5 foreign documents, controls of the
same length; AUC 0.5 means "no better than a coin"):

| | in the process, before | in the process, with scope | over HTTP, before | over HTTP, now (scope and step) |
|---|---|---|---|---|
| kowalczyk (1 foreign) | +11 µs, AUC 0.54 | +117 µs, AUC 0.60 | +497 µs, AUC 0.545 | +30 µs of 33 ms, **AUC 0.499** |
| ostrowski (5 foreign) | +64 µs, AUC 0.60 | +69 µs, AUC 0.56 | +476 µs, AUC 0.522 | +13 µs, **AUC 0.504** |
| zimmermannteubner (1 foreign) | +135 µs, AUC 0.64 | +230 µs, AUC 0.65 | +370 µs, AUC 0.533 | -98 µs, **AUC 0.505** |

(1,500 pairs each; "in the process" calls the search directly, without the network, the most a measurement can see.)
The scope alone does not close it: the controls differ in their last letter, so a trigram of theirs is likely found
nowhere, and a lookup that finds a trigram missing is quicker than one that finds it in a foreign document. Three
things together do:

* **The answer leaves at the next step of 25 ms** after the search began (`routers/search.py`, `TIME_STEP`), errors too.
  Over HTTP the difference is gone in the measurement (AUC 0.50; the averages of 50 requests 0.43, 0.63 and 0.51 with
  30 blocks each, within chance). A search that ends right at a step's edge could still land in one step or the next;
  so that this edge cannot be used to amplify the difference, a random wait of 0 to 25 ms (`secrets`, `JITTER`) follows
  the step (reviewer's suggestion, second check of B3).
* **At most 120 searches a minute per person** (browser, device and key alike; `429 search_too_often` with
  `Retry-After`): the thousands of requests a statistical guess needs take hours, and each one is logged.
* What the time still says is how common a word is on the whole server once it is in thousands of documents (searches
  over 25 ms, a word in nearly every document): a property of the language, not of anybody's document.

What it costs: a person who sees everything reads all scope lists. At 20,000 documents a word found nowhere took 3 ms
in the index for a person in 200 vaults instead of under 1 ms, a rare word 22 ms instead of 1 ms; a person in one
vault is quicker than before (the index reads only their part).

## The text recognition

ocrmypdf 17.13 with Tesseract 5.5 (Debian trixie), the six languages of the settings in the image, no Ghostscript
(ocrmypdf draws pages with PDFium and writes a plain PDF). Measured on docker-dev in a throwaway container started as the
compose file starts it (`cap_drop: ALL`, uid 1000):

| | |
|---|---|
| Image | 705 MB (without recognition: 457 MB; Tesseract with its data 110 MB, ocrmypdf and what it brings about 55 MB) |
| Memory at rest | 86 MiB |
| Recognising a scan of 10 pages (200 dpi, skewed, specks; German and English, straightened) | 23 s, at most 297 MB for the whole container |

## "Looks like a document you have"

See `services/similar.py`. Measured with made-up monthly invoices of one form, the reviewer's phone invoice with fixed
prices and contract lines, a rent, and the same sheet scanned again:

| | picture (bits of 1024) | words in common | numbers in common | longest number and dates |
|---|---|---|---|---|
| same sheet, rescanned (turned up to 1°, specks, brightness, JPEG) | 125 to 298 | 100 % (Tesseract) | 93 % (Tesseract) | the same |
| same text, 4 % of words misread on purpose | | 82 % and more | 100 % | the same |
| monthly invoices of one form | 106 to 202 | 95 % | 51 to 71 % | differ |
| phone invoice with fixed lines, two months | | 100 % | 71 to 80 % | differ |
| rent, two months | | 95 % | high | the dates differ |
| unrelated pages | 92 and up, about 512 on average | | | |

The picture cannot tell a rescan from next month's invoice, and the share of numbers not always either (the phone
invoice reached 80 %). A document is called alike when the picture differs in at most 340 bits, words and numbers agree
in 80 % **and** the longest number and the dates are the same (a misread invoice number means no hint: the safe side).

## Measured again with the scope (B3, second round)

| | 5,000 documents | 20,000 documents |
|---|---|---|
| Database with both indexes | 110 MB | 425 MB (21 KB per document) |
| Index | 83 MB | 322 MB |
| Indexing a document | 2.4 ms | 2.9 ms |
| A change to one document | median 15 ms | median 14 ms, at most 67 ms |
| One common word, Anna / Ben / Carla | 27 / 13 / 98 ms | 61 / 26 / 275 ms |
| One rare word | | 29 / 7 / 136 ms |
| Part of a word (`werke`) | | 34 / 10 / 177 ms |
| Filters only | | 20 / 19 / 27 ms |
| Nothing found | | 11 / 3 / 72 ms (warm: 10 ms for Carla) |

The scope costs nothing in size (it is a few tokens per document). The time now follows what a person sees: Ben (one
vault) is several times quicker than before, Carla (all 200 vaults) pays for reading all of them. The floor test stays
green with the same limits.
