"""The module's own notifications, in the language of each account:

- ``update`` (G18, G24): "<app> 1.3.0 ist erschienen. Dein Server läuft mit 1.2.1." to every operator, once per
  version: the app hands ``updates.on_newer(version)`` to ``newer`` beside its bell; ``updates`` calls it once per
  version and only while "Einmal am Tag nachsehen" is on;
- ``security`` (G29): "Neues Gerät verbunden" to the account's other devices, after every pairing (``paired``).

Only devices that understand the kind get it (the published apps do not, G16)."""

from __future__ import annotations

from typing import Any

from . import push
from .config import KIND_SECURITY, KIND_UPDATE, AppConfig
from .model import Holder, Store
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
