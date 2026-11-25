"""A link to set a new password, made on the server itself: the way back in for whoever cannot sign in at all.

The operator sends links from the interface (Settings, Accounts), and a person asks for one on the sign-in page where a
mail server is set up. An operator who forgot their own password, on a server without mail, has nobody to send one.
Whoever can run a command in the container holds the database and the server's secrets anyway, so this gives them
nothing they did not have::

    docker exec -it -u nexpaper nexpaper python -m app.reset_link <username or email> [--days 1|7|30]

It makes the link through the shared account module (``resets.server_reset_link``: the same table, once, one day from
the start, one open link per account, the same checks when it is used) and prints it, and it writes a line to the
server's log without the link. At the next sign-in the account hears that the server made it.
Using the link lifts the lock after failed sign-ins; the second factor stays, the recovery codes still work. An account
that signs in only through a provider gets a password this way and becomes an account with a password (the operator's
link does the same).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SCHEMA_VERSION, SessionLocal, engine, schema_version
from .models import OPERATOR, SIGN_IN_PASSWORD, Account
from .services import logs, settings_service
from .services.konten_store import KontenStore
from .vendor import nexkonten
from .vendor.nexkonten import resets as konten_resets

COMMAND = "python -m app.reset_link"
ROOT_REFUSED = (
    "Run this as the user nexpaper, not as root: a file root makes in /data the server could not open any more.\n"
    f"  From the host:            docker exec -it -u nexpaper <container> {COMMAND} <account>\n"
    f"  From a console inside:    gosu nexpaper {COMMAND} <account>\n"
    "  (Where the compose file starts the container with a user: of its own, give that user to -u instead.)"
)


def _make(db: Session, who: str, days: int) -> tuple[str, str]:
    """The link, with a line in the server's log, appended: the rotating handler belongs to the server's process."""
    handler = logging.FileHandler(logs.log_file(), encoding="utf-8")
    handler.setFormatter(logging.Formatter(logs.LOG_FORMAT, logs.DATE_FORMAT))
    handler.addFilter(logs._ContextFilter())
    root = logging.getLogger("nexpaper")
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        made = konten_resets.server_reset_link(KontenStore(db), who, days=days)
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
        handler.close()
    return made.token, made.expires_at.isoformat(timespec="minutes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description="Print a link to set a new password for an account. It works once, one day from the start.",
    )
    parser.add_argument(
        "name", nargs="?", help="the username or the email address; without it, the accounts are listed",
    )
    parser.add_argument("--days", type=int, default=konten_resets.OPERATOR_DAYS_DEFAULT,
                        choices=konten_resets.OPERATOR_DAYS, help="how long the link holds (1, 7 or 30 days)")
    args = parser.parse_args(argv)

    if hasattr(os, "getuid") and os.getuid() == 0:
        print(ROOT_REFUSED, file=sys.stderr)
        return 2
    if not get_settings().database_path.exists():
        print("There is no database yet. Start nexpaper once and set it up.", file=sys.stderr)
        return 1
    with engine.connect() as connection:
        version = schema_version(connection)
    if version != SCHEMA_VERSION:
        print(f"The database has schema {version}, this nexpaper expects {SCHEMA_VERSION}. Start the server once, "
              "then try again.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        accounts = list(db.scalars(select(Account).order_by(Account.name)))
        if not args.name:
            for row in accounts:
                role = "operator" if row.role == OPERATOR else "member"
                state = ", blocked" if row.blocked_at is not None else ""
                print(f"{row.name}  ({role}{state})")
            return 0
        found = nexkonten.login.resolve_login(KontenStore(db), args.name)
        account = db.get(Account, int(found.id)) if found is not None else None
        if account is None:
            names = ", ".join(row.name for row in accounts) or "none"
            print(f"No account named '{args.name}'. Accounts: {names}", file=sys.stderr)
            return 1
        if account.blocked_at is not None:
            print(f"The account '{account.name}' is blocked. An operator can unblock it in Settings, Accounts.",
                  file=sys.stderr)
            return 1
        if account.role != OPERATOR and not settings_service.get(db, "password_login"):
            print("Signing in with a password is switched off on this server; a link works only for an operator.",
                  file=sys.stderr)
            return 1

        by_provider = account.sign_in != SIGN_IN_PASSWORD
        name = account.name
        token, until = _make(db, name, args.days)
        base = settings_service.public_url(db)
        link = f"{base}/reset/{token}" if base else ""

    if link:
        print(link)
    else:
        print(f"/reset/{token}")
        print("Open this path at the address you use for nexpaper, for example http://192.0.2.10:8560/reset/...",
              file=sys.stderr)
    if by_provider:
        print(f"'{name}' signs in through a provider so far. Using the link gives the account a password and makes it "
              "an account with a password.", file=sys.stderr)
    print(f"The link works once, until {until} (UTC). Your second factor stays: sign in with the new password, "
          "then with the code from your app, a passkey or one of your recovery codes.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
