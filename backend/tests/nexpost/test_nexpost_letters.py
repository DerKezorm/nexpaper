"""Since 1.0.0: the mail "New sign-in" as the app writes it (decided 25.11.2026, the same in every app): the browser on
its system and the moment in the person's time zone, the button "See signed-in devices" to the app's page Security,
never a network address."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
SENDER = "203.0.113.77"


def test_the_mail_about_a_new_sign_in_names_browser_moment_and_links_the_devices(app: Any, post: Any) -> None:
    letter = app.new_sign_in_letter(AGENT, SENDER)
    assert letter.kind == "new_sign_in"
    said = {"Firefox auf Linux", "Firefox on Linux", "Firefox sous Linux"}
    assert any(words in letter.text for words in said), letter.text
    # The moment: the day (a day either side for the person's time zone) in one of the forms, and its zone.
    days = [datetime.now(UTC).date() + timedelta(days=step) for step in (-1, 0, 1)]
    forms = {day.strftime(form) for day in days for form in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y")}
    assert any(form in letter.text for form in forms), letter.text
    assert re.search(r"\d{2}:\d{2}.{0,8}\(UTC(?:[+-]\d{1,2}(?::\d{2})?)?\)", letter.text), letter.text
    # The button to the page Security, in the letter's language.
    actions = {post.letters.texts(language)["new_sign_in"]["action"] for language in post.letters.LANGUAGES}
    assert any(action in letter.html for action in actions), "no button 'See signed-in devices'"
    assert re.search(r'href="https?://', letter.html), "the button needs the address of the page Security"
    # Never where the sign-in came from.
    for text in (letter.text, letter.html, letter.subject):
        assert SENDER not in text
