"""A link to set a new password, made on the server itself: the way back in for whoever cannot sign in at all.

The operator sends links from the interface (Settings, Accounts), and a person asks for one on the sign-in page where a
mail server is set up. An operator who forgot their own password, on a server without mail, has nobody to send one.
Whoever can run a command in the container holds the database and the server's secrets anyway, so this gives them
nothing they did not have::

    docker exec -it -u nexpaper nexpaper python -m app.reset_link <account>

It makes the link the interface makes (``services/resets.py``: the same table, once, 24 hours, one open link per
account, the same checks when it is used) and prints it, and it writes a line to the server's log without the link.
Using the link lifts the lock after failed sign-ins; the second factor stays, the recovery codes still work.
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
from .models import OPERATOR, Account
from .services import logs, resets, settings_service

COMMAND = "python -m app.reset_link"
ROOT_REFUSED = (
    "Run this as the user nexpaper, not as root: a file root makes in /data the server could not open any more.\n"
    f"  From the host:            docker exec -it -u nexpaper <container> {COMMAND} <account>\n"
    f"  From a console inside:    gosu nexpaper {COMMAND} <account>\n"
    "  (Where the compose file starts the container with a user: of its own, give that user to -u instead.)"
)

logger = logging.getLogger("nexpaper.auth")


def _make(db: Session, account: Account) -> str:
    """The link, with a line in the server's log, appended: the rotating handler belongs to the server's process."""
    handler = logging.FileHandler(logs.log_file(), encoding="utf-8")
    handler.setFormatter(logging.Formatter(logs.LOG_FORMAT, logs.DATE_FORMAT))
    handler.addFilter(logs._ContextFilter())
    root = logging.getLogger("nexpaper")
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        _row, token = resets.make(db, account)
        logger.warning("Password link made on the server with %s name=%s", COMMAND, account.name)
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
        handler.close()
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description="Print a link to set a new password for an account. It works once and for 24 hours.",
    )
    parser.add_argument(
        "name", nargs="?", help="the name the account signs in with; without it, the accounts are listed",
    )
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
        wanted = args.name.strip().lower()
        account = next((row for row in accounts if row.name == wanted), None)
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

        token = _make(db, account)
        link = resets.link_to(db, token)

    if link:
        print(link)
    else:
        print(f"/reset/{token}")
        print("Open this path at the address you use for nexpaper, for example http://192.0.2.10:8560/reset/...",
              file=sys.stderr)
    print(f"The link works once and for {resets.HOURS} hours. Your second factor stays: sign in with the new password, "
          "then with the code from your app, a passkey or one of your recovery codes.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
