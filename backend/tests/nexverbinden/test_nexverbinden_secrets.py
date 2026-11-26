"""No token in a page's answer, in the log, or unsealed in what the app keeps. Copied unchanged into every app."""

from __future__ import annotations

import logging
from typing import Any

import pytest


def test_no_token_stands_in_an_answer_the_log_or_unsealed_in_the_app(
    world: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    assert world.connect("app").status_code == 200
    world.expire_partner_access()
    assert world.partner_calls_app(f"{world.pkg.PREFIX}/hello").status == 200
    pages = [
        world.app.client("owner").get(f"{world.pkg.PREFIX}/partners").text,
        world.app.client("owner").post(f"{world.pkg.PREFIX}/partners/{world.partner.name}/check").text,
        world.app.client("operator").get(f"{world.pkg.PREFIX}/admin").text,
    ]
    kept = world.app.everything()
    assert len(world.tokens) >= 4
    for token in world.tokens:
        assert all(token not in page for page in pages)
        assert token not in caplog.text
        assert token not in kept
