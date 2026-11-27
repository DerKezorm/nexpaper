"""The module's own notifications, in the language of each account:

- ``update`` (G18, G24, G56): "<app> 1.3.0 ist erschienen. Dein Server läuft mit 1.2.1." to every operator, once
  per version: ``nexupdates`` calls ``on_devices(version)`` -> ``newer``, once per version and only while "Einmal am
  Tag nachsehen" is on; ``update_wanted`` is its ``devices_want``: such a device counts as a bell (U24);
- ``security`` (G29): "Neues Gerät verbunden" to the account's other devices, after every pairing (``paired``);
- the mail "Neue Anmeldung" for a new device (G29, G50): ``where`` names it ("„Kims iPhone“ (iPhone 16 Pro)"),
  ``letter`` composes it with ``nexpost.letters`` (whose ``from_account_mail`` names browsers only).

Only devices that understand the kind get it (the published apps do not, G16)."""

from __future__ import annotations

import re
import unicodedata
from datetime import tzinfo
from typing import Any

from . import push
from .config import KIND_SECURITY, KIND_UPDATE, SWITCH_APP, AppConfig
from .model import Device, Holder, Store
from .pairing import Paired

WORDS: dict[str, dict[str, str]] = {
    "de": {
        "update_title": "{app} {version} ist erschienen",
        "update_text": "Dein Server läuft mit {current}. Tippe für das, was neu ist.",
        "security_title": "Neues Gerät verbunden",
        "security_text": "{device} ist jetzt mit deinem Konto verbunden. Warst du das nicht, trenne es im Browser.",
    },
    "en": {
        "update_title": "{app} {version} is out",
        "update_text": "Your server runs {current}. Tap to see what is new.",
        "security_title": "New device connected",
        "security_text": "{device} is now connected to your account. If it was not you, disconnect it in the browser.",
    },
    "fr": {
        "update_title": "{app} {version} est disponible",
        "update_text": "Ton serveur utilise la version {current}. Touche pour voir les nouveautés.",
        "security_title": "Nouvel appareil connecté",
        "security_text": "{device} est maintenant connecté à ton compte. Si ce n'était pas toi, déconnecte-le dans "
        "le navigateur.",
    },
}


def words(language: str) -> dict[str, str]:
    return WORDS.get(language) or WORDS["en"]


def _server(config: AppConfig) -> dict[str, Any]:
    return {"server": config.server_id()} if config.server_id is not None else {}


def newer(
    store: Store, config: AppConfig, version: str, current: str, url: str = "", *, send: push.Send | None = None
) -> push.Told:
    """``update`` to every operator: the new version, the running one, the link "Was neu ist"."""

    def message(holder: Holder) -> dict[str, Any]:
        said = words(holder.language)
        return {
            "type": KIND_UPDATE,
            "title": said["update_title"].format(app=config.app, version=version),
            "text": said["update_text"].format(current=current),
            "version": version,
            "current": current,
            "url": url,
            "account": holder.id,
            **_server(config),
        }

    return push.tell_operators(store, config, KIND_UPDATE, message, collapse=f"update-{version}", send=send)


def update_wanted(store: Store, config: AppConfig) -> bool:
    """For ``nexupdates`` (``devices_want``, U24, G56): True while a device of an operator would get ``update``: a
    relay, the switch ``app`` on, the operator not shut out, the device signed up, naming ``update`` among what it
    understands and not having switched it off. Such a device counts as a bell: the background looks at most once a
    day."""
    if not config.relay() or not store.switch(SWITCH_APP):
        return False
    for account_id in store.operators():
        holder = store.holder(account_id)
        if holder is None or holder.out or not holder.operator:
            continue
        for device in store.devices_of(account_id):
            if device.push is None:
                continue
            if push.understood(config, device, KIND_UPDATE) and push.wanted(config, device, holder, KIND_UPDATE):
                return True
    return False


def paired(store: Store, config: AppConfig, done: Paired, *, send: push.Send | None = None) -> push.Told:
    """``security`` to the account's other devices: which device came in."""
    said = words(done.holder.language)
    message = {
        "type": KIND_SECURITY,
        "title": said["security_title"],
        "text": said["security_text"].format(device=done.device.name),
        "device": done.device.id,
        "account": done.holder.id,
        **_server(config),
    }
    return push.tell(
        store, config, done.holder.id, KIND_SECURITY, message, collapse="security", skip=done.device.id, send=send
    )


#: Text that could lead somewhere: a device's name and model are the pairing device's own words, and the mail goes to
#: the account's address; nothing in it may read like a link (the rule of ``nexpost.letters.describe_browser``).
_LINKISH = re.compile(r"://|www\.|@|\.[a-z]{2,}\b", re.IGNORECASE)
#: A model as the published and the coming apps name it ("iPhone 16 Pro", "iPad Air (M2)", "MacBook Air").
_MODEL = re.compile(r"(iPhone|iPad|iMac|Mac)[A-Za-z0-9 ,.()+-]{0,30}")
KIND_NAMES = {"ios": "iPhone", "ipados": "iPad", "mac": "Mac"}
QUOTES = {"de": ("\u201e", "\u201c"), "en": ("\u201c", "\u201d"), "fr": ("\u00ab\u00a0", "\u00a0\u00bb")}
NAME_LIMIT = 40


def _one_line(text: str | None) -> str:
    kept = "".join(" " if char in "\r\n\t" else char for char in str(text or ""))
    kept = "".join(char for char in kept if unicodedata.category(char) not in ("Cc", "Cf"))
    return " ".join(kept.split())


def where(device: Device, language: str) -> str:
    """The device for the mail "Neue Anmeldung" (G50): its name in quotes and the model, "„Kims iPhone“ (iPhone 16
    Pro)". A model the module does not know as Apple's gives way to the kind ("iPhone", "iPad", "Mac"); a name that
    looks like a link or an address is left out; a long one is cut at 40 characters."""
    kind = KIND_NAMES.get(device.kind or "ios", "iPhone")
    model = _one_line(device.model)
    if not _MODEL.fullmatch(model) or _LINKISH.search(model):
        model = kind
    name = _one_line(device.name)
    if _LINKISH.search(name):
        name = ""
    if len(name) > NAME_LIMIT:
        name = name[: NAME_LIMIT - 1].rstrip() + "\u2026"
    if not name or name.casefold() == model.casefold():
        return model
    opening, closing = QUOTES.get(language, QUOTES["en"])
    return f"{opening}{name}{closing} ({model})"


def letter(letters: Any, mail: Any, device: Device, *, language: str, link: str = "",
           time_zone: str | tzinfo | None = None) -> Any:
    """The mail "Neue Anmeldung" for a new device (G29, G50). ``letters`` is the app's ``nexpost.letters``, ``mail``
    what ``konten.sessions.new_sign_in`` gave (None: no mail). As ``letters.from_account_mail``, but ``where`` names
    the device rather than a browser (``from_account_mail`` reads a User-Agent and knows browsers only); ``device``
    carries the same words for a wording of its own in ``nexpost``."""
    if mail is None:
        return None
    named = where(device, language)
    values: dict[str, object] = {
        "name": getattr(mail, "display_name", "") or getattr(mail, "username", ""),
        "username": getattr(mail, "username", ""),
        "where": named,
        "device": named,
        "when": letters.moment(language, getattr(mail, "at", None), time_zone),
    }
    return letters.compose(str(getattr(mail, "kind", "new_sign_in")), str(getattr(mail, "to", "")),
                           language=language, values=values, link=link)
