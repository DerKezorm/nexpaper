"""Which nex app connects with which, and for what: the one list every app reads, so that both sides of a connection
name the same purposes (decisions V2, V3: 14 pairs, one connection per pair of apps with both directions in it).

A **purpose** belongs to the app that grants it (the host of that purpose): its id, the right it stands for in that
app today (``read`` or ``write``, the levels of the apps' API keys) and whether it can be limited to areas (spaces,
calendars, vaults, address books). The words of the purposes are the module's (``frontend/verbinden.*.json``,
``purposes.<app>.<id>``); the server needs none.

A **connection** is a pair of apps and, for each of the two, the purposes it uses at the other. Either app may start
it; one consent covers both directions. A side that uses nothing still holds a token of the other: it opens only the
module's own routes (``hello``, ``revoke``), so that either side can check and end the connection."""

from __future__ import annotations

from dataclasses import dataclass

APPS = ("nexnotes", "nexmail", "nextasks", "nextime", "nexpaper", "nexdiary", "nexlore", "nexfolk")


@dataclass(frozen=True)
class Purpose:
    id: str
    #: The right this purpose stands for in the app that grants it, as its API keys name it.
    level: str
    #: Whether the account picks areas for it on the consent page.
    areas: bool = True


def _purposes(*found: Purpose) -> dict[str, Purpose]:
    return {purpose.id: purpose for purpose in found}


#: What each app grants: app -> purpose id -> purpose.
PURPOSES: dict[str, dict[str, Purpose]] = {
    "nextasks": _purposes(
        Purpose("tasks.read", "read"),
        Purpose("tasks.write", "write"),
        Purpose("tasks.complete", "write"),
        Purpose("members.read", "read"),
    ),
    "nextime": _purposes(
        Purpose("calendars.read", "read"),
        Purpose("events.write", "write"),
        Purpose("invitations.answer", "write"),
    ),
    "nexpaper": _purposes(Purpose("deadlines.read", "read"), Purpose("documents.add", "write")),
    "nexnotes": _purposes(Purpose("notes.add", "write")),
    "nexlore": _purposes(Purpose("notes.add", "write")),
    "nexfolk": _purposes(
        Purpose("birthdays.read", "read"),
        Purpose("contacts.read", "read"),
        Purpose("contacts.write", "write"),
        # V29 (since 0.1.3): people for an entry or an event, only their id, name and mail addresses (no telephone, no
        # address, no notes); nextime and nexdiary take this one, contacts.read stays nexmail's.
        Purpose("people.read", "read"),
    ),
    "nexmail": {},
    "nexdiary": {},
}


@dataclass(frozen=True)
class Pair:
    """Two apps and the purposes each uses at the other (``uses[app]`` names purposes the *other* app grants)."""

    apps: frozenset[str]
    uses: dict[str, tuple[str, ...]]

    def other(self, app: str) -> str:
        (found,) = self.apps - {app}
        return found


def _pair(first: str, second: str, **uses: tuple[str, ...]) -> Pair:
    return Pair(
        apps=frozenset((first, second)),
        uses={first: uses.get(first, ()), second: uses.get(second, ())},
    )


#: The 14 connections (V2). The order is the order of the cards when an app has several partners.
PAIRS: tuple[Pair, ...] = (
    _pair("nexnotes", "nextasks", nexnotes=("tasks.read", "tasks.write")),
    _pair("nexmail", "nextasks", nexmail=("tasks.read", "tasks.write", "tasks.complete", "members.read")),
    _pair("nextime", "nextasks", nextime=("tasks.read", "tasks.complete")),
    _pair("nextime", "nexpaper", nextime=("deadlines.read",)),
    _pair("nexmail", "nextime", nexmail=("calendars.read", "events.write", "invitations.answer")),
    _pair("nextime", "nexfolk", nextime=("birthdays.read", "people.read")),
    _pair("nexmail", "nexfolk", nexmail=("contacts.read", "contacts.write")),
    _pair("nexmail", "nexpaper", nexmail=("documents.add",)),
    _pair("nexpaper", "nextasks", nexpaper=("tasks.read", "tasks.write")),
    _pair("nexnotes", "nexlore", nexnotes=("notes.add",)),
    _pair("nexdiary", "nextime", nexdiary=("calendars.read",)),
    _pair("nexdiary", "nextasks", nexdiary=("tasks.read",)),
    _pair("nexdiary", "nexfolk", nexdiary=("people.read",)),
    _pair("nextime", "nexnotes", nextime=("notes.add",)),
)


@dataclass(frozen=True)
class Catalog:
    """The pairs and purposes an app reads; the module's lists by default, the tests may bring their own."""

    purposes: dict[str, dict[str, Purpose]]
    pairs: tuple[Pair, ...]

    def pair(self, app: str, partner: str) -> Pair | None:
        wanted = frozenset((app, partner))
        return next((pair for pair in self.pairs if pair.apps == wanted), None)

    def partners(self, app: str) -> list[str]:
        """The apps ``app`` connects with, in the order of the list."""
        return [pair.other(app) for pair in self.pairs if app in pair.apps]

    def uses(self, app: str, partner: str) -> tuple[str, ...]:
        """The purposes ``app`` uses at ``partner`` (granted by ``partner``)."""
        found = self.pair(app, partner)
        return found.uses[app] if found else ()

    def purpose(self, granted_by: str, purpose_id: str) -> Purpose:
        return self.purposes[granted_by][purpose_id]

    def level(self, granted_by: str, purpose_ids: tuple[str, ...]) -> str | None:
        """The highest right among the purposes (``write`` above ``read``), ``None`` for none."""
        levels = {self.purpose(granted_by, purpose).level for purpose in purpose_ids}
        if not levels:
            return None
        return "write" if "write" in levels else "read"

    def check(self) -> list[str]:
        """What is wrong with the lists (the module's test keeps this empty): unknown apps, unknown purposes, a pair
        twice, a pair in which nobody uses anything."""
        found = []
        seen: set[frozenset[str]] = set()
        for pair in self.pairs:
            if len(pair.apps) != 2 or not pair.apps <= set(self.purposes):
                found.append(f"pair {sorted(pair.apps)}: unknown app")
                continue
            if pair.apps in seen:
                found.append(f"pair {sorted(pair.apps)}: twice")
            seen.add(pair.apps)
            if not any(pair.uses.values()):
                found.append(f"pair {sorted(pair.apps)}: nobody uses anything")
            for app, purposes in pair.uses.items():
                granted = self.purposes[pair.other(app)]
                found += [
                    f"pair {sorted(pair.apps)}: {pair.other(app)} grants no {p}" for p in purposes if p not in granted
                ]
        return found


CATALOG = Catalog(purposes=PURPOSES, pairs=PAIRS)
