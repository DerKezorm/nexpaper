"""The operator's card "Interfaces" (Server › Connections since 1.1.3, E67): "Programming interface (API) for
members", "MCP access" and,
where the app has an iPhone app, "Allow the iPhone app" and "Connect new devices". Each stays where the app keeps it
(its own setting, its own default); the store reads and writes it. Switching off deletes nothing: the keys rest and
work again when it is switched on."""

from __future__ import annotations

from .config import AppConfig
from .errors import KeyRefused
from .model import Store


def state(store: Store, config: AppConfig) -> dict[str, bool]:
    """The switches the app has, each on or off."""
    return {name: bool(store.switch(name)) for name in config.switches}


def change(store: Store, config: AppConfig, changes: dict[str, bool]) -> dict[str, bool]:
    """Set some switches; one the app does not have is refused before anything changes."""
    for name in changes:
        if name not in config.switches:
            raise KeyRefused("switch_unknown", config=config)
    for name, on in changes.items():
        store.set_switch(name, bool(on))
    store.commit()
    return state(store, config)
