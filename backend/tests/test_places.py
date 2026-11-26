"""The places the README, ``docs/api.md``, ``docs/iphone-shortcut.md``, the page of the interface and the server's own
notices and mails name are the settings as they are now (plan "Einstellungen", E39): "Settings › My account › …" or
"Settings › Server › …" with an area of that group in the words of the navigation; a notice or a mail leads to
``/settings/<slug>`` of an area there is (the addresses of before still lead on, ``frontend/src/pages/settings/areas.ts``).
The word for a program's access is "API key", never "API token" (only Paperless and authentik call their own one so).
The page's own texts are held the same way by ``frontend/src/i18n/places.test.ts``.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import filecheck, notices, oidc_store, reminders

ROOT = Path(__file__).resolve().parents[2]
DOCS = ("README.md", "docs/api.md", "docs/iphone-shortcut.md")

#: The groups of the navigation and their areas (ui kit ``texts.ts`` and nexpaper's own areas), in English.
AREAS = {
    "My account": ("Profile", "Security", "Appearance", "Upload", "AI", "Notifications", "Connections"),
    "Server": ("General", "Sign-in", "Mail", "Storage and backups", "Text recognition", "AI provider", "Filing",
               "Inputs", "Import", "Accounts", "Log"),
}
#: The slugs of the areas (``frontend/src/pages/settings/areas.ts``).
SLUGS = {"profile", "security", "appearance", "upload", "ai", "notifications", "connections", "general", "sign-in",
         "mail", "storage", "ocr", "ai-provider", "filing", "inputs", "import", "accounts", "log", "about"}
OLD = re.compile(r"Settings, |Settings →|My account, |\(\*\*Settings\*\*\)|Devices and apps|Settings › (?!My account|Server)")
TOKEN = re.compile(r"API tokens?\b")


def _texts() -> dict[str, str]:
    return {name: (ROOT / name).read_text(encoding="utf-8") for name in DOCS}


def test_every_path_into_the_settings_names_a_group_and_one_of_its_areas() -> None:
    wrong, paths = [], 0
    for name, text in _texts().items():
        flat = re.sub(r"\s+", " ", text)
        for found in re.finditer(r"Settings › ", flat):
            paths += 1
            rest = flat[found.end():]
            if not any(rest.startswith(f"{group} › {area}") for group, areas in AREAS.items() for area in areas):
                wrong.append(f"{name}: {rest[:60]}")
    assert wrong == []
    assert paths >= 45


def test_no_text_points_the_old_way_and_a_programs_access_is_an_api_key() -> None:
    old = []
    for name, text in _texts().items():
        for number, line in enumerate(text.splitlines(), 1):
            if OLD.search(line) or (TOKEN.search(line) and not re.search(r"Paperless|authentik", line)):
                old.append(f"{name}:{number}: {line.strip()[:100]}")
    assert old == []


def test_the_page_of_the_interface_says_key() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        page = client.get("/api/v1/docs").text
    assert "a program an API key, as <code>Authorization: Bearer &lt;key&gt;</code>" in page
    assert "key or session" in page and "token or session" not in page


def test_the_server_leads_to_the_areas_of_the_settings() -> None:
    """The notice of a new sign-in and of a reset factor (and its mail), a provider unlinked or linked, the check of
    the files and a failed restore: each opens the area it is about."""
    led = {"notices": notices.SECURITY_PATH, "files": filecheck.PATH, "provider": oidc_store.ACCOUNT_PAGE}
    assert led == {"notices": "/settings/security", "files": "/settings/storage", "provider": "/settings/security"}
    for path in led.values():
        assert path.startswith("/settings/") and path.removeprefix("/settings/") in SLUGS
    source = (ROOT / "backend" / "app").rglob("*.py")
    named = [(file.name, found) for file in source if "vendor" not in file.parts
             for found in re.findall(r"url=\"(/[^\"]*)\"", file.read_text(encoding="utf-8"))]
    assert all(not path.startswith(("/konto", "/einstellungen", "/ueber")) for _file, path in named), named
    assert ("oidc.py", "/settings/security") in named and ("backup_hooks.py", "/settings/storage") in named


def test_the_mails_of_the_reminders_name_where_they_are_switched() -> None:
    assert "Mein Konto › Benachrichtigungen" in reminders.WORDS["de"]["week_why"]
    assert "Mein Konto › Benachrichtigungen" in reminders.WORDS["de"]["single_why"]
    assert "My account › Notifications" in reminders.WORDS["en"]["week_why"]
    assert "My account › Notifications" in reminders.WORDS["en"]["single_why"]
