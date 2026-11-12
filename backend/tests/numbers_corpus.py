"""Made-up papers for measuring the proposals of "goes with" (``services/numbers.py``, ``services/related.py``).

``corpus(seed)`` makes groups of papers that go together (an invoice and its delivery note, an order confirmation and
its invoice, an invoice and its reminder or credit note; German and English, the number words written in many ways)
and papers that do not: other invoices of the same senders with the same customer number, IBAN and contract account,
numbers that differ in one digit, monthly invoices of one framework order, letters full of dates, amounts, phone and
article numbers. Some papers of a group are written as a scan reads them: ``O`` for ``0``, ``l`` or ``I`` for ``1``,
blanks and dashes in the number, the number on the line after its word, a word misread. Nothing here is real: the
senders, numbers and IBANs are made up (the IBANs get valid check digits so that they are read as IBANs).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

SENDERS_DE = ["Stadtwerke Lindenau", "Möbelhaus Brandt", "Elektro Kessler GmbH", "Bürobedarf Hansen",
              "Glanzwerk Reinigungsservice", "Bergmann Baustoffe", "Druckerei Weiss", "Gartenbau Lehmann",
              "Autohaus Petersen", "Fahrradladen Kruse"]
SENDERS_EN = ["Harbor Tools Ltd", "Northfield Supplies Ltd", "Bluebell Office Goods", "Kestrel Print Co"]


@dataclass
class Paper:
    text: str
    #: The group of papers it goes with; ``None`` for one that goes with nothing.
    group: int | None
    sender: str
    kind: str


@dataclass
class Corpus:
    papers: list[Paper] = field(default_factory=list)

    def true_pairs(self) -> set[tuple[int, int]]:
        groups: dict[int, list[int]] = {}
        for index, paper in enumerate(self.papers):
            if paper.group is not None:
                groups.setdefault(paper.group, []).append(index)
        return {(a, b) for members in groups.values() for i, a in enumerate(members) for b in members[i + 1:]}


def _iban(rng: random.Random) -> str:
    account = "".join(rng.choice("0123456789") for _ in range(18))
    moved = account + "1314" + "00"  # DE as digits, check digits 00
    check = 98 - int(moved) % 97
    return f"DE{check:02d}{account}"


def _spaced_iban(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def _number(rng: random.Random, style: str) -> str:
    year = rng.choice(["2025", "2026"])
    return {
        "R": f"R-{year}-{_digits(rng, 5)}",
        "RE": f"RE{year}{_digits(rng, 4)}",
        "INV": f"INV-{_digits(rng, 6)}",
        "LS": f"LS-{_digits(rng, 6)}",
        "DN": f"DN {_digits(rng, 5)}",
        "AB": f"AB {year}/{_digits(rng, 4)}",
        "B": f"B-{_digits(rng, 7)}",
        "PO": f"PO-{_digits(rng, 5)}",
        "N": _digits(rng, 8),
        "SO": f"SO{_digits(rng, 6)}",
    }[style]


def _scan(rng: random.Random, value: str) -> str:
    """The number as a scan may read it."""
    choice = rng.randrange(6)
    if choice == 0:
        return value.replace("0", "O", rng.randint(1, 2))
    if choice == 1:
        return value.replace("1", rng.choice(["l", "I"]), 1) if "1" in value else value.replace("0", "O", 1)
    if choice == 2:
        return value.replace("-", " - ").replace("/", " / ")
    if choice == 3:
        middle = len(value) // 2
        return value[:middle] + " " + value[middle:] if value[middle - 1].isdigit() and value[middle].isdigit() \
            else value.replace("-", " ")
    if choice == 4:
        return value.replace("-", "")
    return value.lower() if rng.random() < 0.5 else value


def _label(rng: random.Random, kind: str, english: bool) -> str:
    words = {
        ("invoice", False): ["Rechnungsnummer:", "Rechnungs-Nr.", "Rechnung Nr.", "Re.-Nr.", "Rechnungsnr.",
                             "Rechnung"],
        ("invoice", True): ["Invoice No.", "Invoice #", "Invoice number:", "Invoice"],
        ("order", False): ["Bestellnummer:", "Ihre Bestellung", "Bestell-Nr.", "Auftrag Nr.", "Auftragsnummer:",
                           "Auftrag:", "AB-Nr."],
        ("order", True): ["Order No.", "PO number:", "Your order", "Order #", "Purchase Order"],
        ("delivery", False): ["Lieferschein-Nr.", "Lieferscheinnummer:", "LS-Nr.", "Lieferschein"],
        ("delivery", True): ["Delivery note No.", "Delivery note:", "Packing slip"],
    }[(kind, english)]
    return rng.choice(words)


def _line(rng: random.Random, kind: str, value: str, english: bool, scanned: bool) -> str:
    label = _label(rng, kind, english)
    if scanned:
        value = _scan(rng, value)
        if rng.random() < 0.25:
            return f"{label}\n{value}"
        if rng.random() < 0.08:
            # A word the scan misread: this number is not found.
            label = label.replace("e", "c", 1)
    return f"{label} {value}"


@dataclass
class Sender:
    name: str
    english: bool
    customer: str
    iban: str
    contract: str
    styles: dict[str, str]
    street: str


def _sender(rng: random.Random, name: str, english: bool) -> Sender:
    styles = {"invoice": rng.choice(["INV", "N"] if english else ["R", "RE", "N"]),
              "order": rng.choice(["PO", "SO"] if english else ["AB", "B", "N"]),
              "delivery": rng.choice(["DN"] if english else ["LS", "N"])}
    return Sender(name=name, english=english, customer=f"{_digits(rng, 3)} {_digits(rng, 4)}", iban=_iban(rng),
                  contract=_digits(rng, 10), styles=styles, street=f"{rng.choice(['Lindenweg', 'Hafenstraße', 'Mill Lane'])} "
                  f"{rng.randint(1, 90)}")


def _head(rng: random.Random, sender: Sender, title: str) -> list[str]:
    day = f"{rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.2026"
    lines = [sender.name, sender.street, "12345 Musterstadt" if not sender.english else "Bristol BS1 1AA", "",
             title, ("Date: " if sender.english else "Datum: ") + day,
             ("Customer number: " if sender.english else "Kundennummer: ") + sender.customer]
    if rng.random() < 0.3:
        lines.append(("Phone " if sender.english else "Tel. ") + f"0{_digits(rng, 3)} {_digits(rng, 6)}")
    return lines


def _foot(rng: random.Random, sender: Sender) -> list[str]:
    amount = f"{rng.randint(10, 2400)},{rng.randint(0, 99):02d}"
    lines = [("Total " if sender.english else "Gesamtbetrag ") + amount + " EUR",
             f"IBAN {_spaced_iban(sender.iban)}", "BIC TESTDEFFXXX"]
    if rng.random() < 0.5:
        lines.insert(0, ("Item " if sender.english else "Art.-Nr. ") + _digits(rng, 5) + " Muster 2 Stk")
    if not sender.english and rng.random() < 0.3:
        lines.append(f"Vertragskonto {sender.contract}")
    return lines


def _paper(rng: random.Random, sender: Sender, kind: str, numbers: dict[str, str], group: int | None,
           scanned: bool) -> Paper:
    english = sender.english
    titles = {"invoice": "Invoice" if english else "Rechnung", "delivery": "Delivery note" if english else "Lieferschein",
              "confirmation": "Order confirmation" if english else "Auftragsbestätigung",
              "reminder": "Reminder" if english else "Zahlungserinnerung",
              "credit": "Credit note" if english else "Gutschrift", "letter": "Information" if english else "Mitteilung"}
    lines = _head(rng, sender, titles[kind])
    for which in ("invoice", "order", "delivery"):
        if which in numbers:
            lines.append(_line(rng, which, numbers[which], english, scanned))
    if kind == "reminder":
        lines.append("Please pay the invoice above." if english else "Bitte begleichen Sie die oben genannte Rechnung.")
    if kind == "credit":
        lines.append("We credit you the amount." if english else "Wir schreiben Ihnen den Betrag gut.")
    lines += _foot(rng, sender)
    return Paper(text="\n".join(lines), group=group, sender=sender.name, kind=kind)


def corpus(seed: int = 15, groups: int = 66, noise: int = 220) -> Corpus:
    rng = random.Random(seed)
    senders = [_sender(rng, name, False) for name in SENDERS_DE] + [_sender(rng, name, True) for name in SENDERS_EN]
    out = Corpus()
    for group in range(groups):
        sender = rng.choice(senders)
        shape = rng.choice(["delivery", "confirmation", "reminder", "credit", "three"])
        number = {which: _number(rng, sender.styles[which]) for which in ("invoice", "order", "delivery")}
        first_scanned = rng.random() < 0.35
        second_scanned = rng.random() < 0.45
        if shape == "delivery":
            papers = [_paper(rng, sender, "invoice", {"invoice": number["invoice"], "delivery": number["delivery"]},
                             group, first_scanned),
                      _paper(rng, sender, "delivery", {"delivery": number["delivery"]}, group, second_scanned)]
        elif shape == "confirmation":
            papers = [_paper(rng, sender, "confirmation", {"order": number["order"]}, group, first_scanned),
                      _paper(rng, sender, "invoice", {"invoice": number["invoice"], "order": number["order"]}, group,
                             second_scanned)]
        elif shape in ("reminder", "credit"):
            papers = [_paper(rng, sender, "invoice", {"invoice": number["invoice"]}, group, first_scanned),
                      _paper(rng, sender, shape, {"invoice": number["invoice"]}, group, second_scanned)]
        else:
            papers = [_paper(rng, sender, "confirmation", {"order": number["order"]}, group, first_scanned),
                      _paper(rng, sender, "delivery", {"order": number["order"], "delivery": number["delivery"]},
                             group, second_scanned),
                      _paper(rng, sender, "invoice", {"invoice": number["invoice"], "delivery": number["delivery"],
                                                      "order": number["order"]}, group, rng.random() < 0.3)]
        out.papers += papers
    # Papers that go with nothing: other invoices of the same senders, one digit off the numbers above, and the monthly
    # invoices of a framework order that is on more than ten of them.
    taken = [paper for paper in out.papers if paper.kind == "invoice"]
    used: set[object] = set()
    for index in range(noise):
        sender = rng.choice(senders)
        roll = rng.random()
        if roll < 0.55:
            numbers = {"invoice": _number(rng, sender.styles["invoice"])}
            if rng.random() < 0.4:
                numbers["order"] = _number(rng, sender.styles["order"])
            kind = "invoice"
        elif roll < 0.7 and taken:
            # One digit off a number of a group.
            base = rng.choice(taken).text
            found = [line for line in base.split("\n") if any(c.isdigit() for c in line) and "Rechnung" in line]
            value = _number(rng, sender.styles["invoice"])
            if found and found[0].split()[-1] not in used:
                # The number with its last digit changed (each number of a group once: two papers that both differ
                # from it in the same way would carry the same number).
                original = found[0].split()[-1]
                used.add(original)
                at = max(i for i, c in enumerate(original) if c.isdigit())
                value = original[:at] + str((int(original[at]) + 1) % 10) + original[at + 1:]
            numbers, kind = {"invoice": value}, "invoice"
        elif roll < 0.8:
            numbers, kind = {}, "letter"
        elif roll < 0.88:
            # Small businesses count their invoices from 10001 on: another sender, the same number (each sender has a
            # number once).
            value = str(rng.randint(10200, 10229))
            while (sender.name, value) in used:
                value = str(rng.randint(10200, 10299))
            used.add((sender.name, value))
            numbers, kind = {"invoice": value}, "invoice"
        else:
            numbers, kind = {"invoice": _number(rng, sender.styles["invoice"]), "order": "RA-2026-0042"}, "invoice"
        out.papers.append(_paper(rng, sender, kind, numbers, None, rng.random() < 0.4))
        if kind == "letter" and index % 3 == 0:
            out.papers[-1].text += "\nIhre Bestellung vom 03.10.2026 ist eingegangen. Rechnung folgt separat."
    return out


__all__ = ["Corpus", "Paper", "corpus"]
