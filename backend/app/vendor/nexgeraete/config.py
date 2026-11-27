"""What the module needs to know about the app: its name and link scheme, the prefix of its device keys, the old form
its published iPhone app speaks, the rules of pairing, the push relay and the kinds of notification it sends. The rows
stay in the app's tables; the module reaches them through the ``Store`` (``model.py``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from types import MappingProxyType

#: The forms of the app routes: ``nex`` (nexnotes, nextime and every app since the module), ``tasks`` (nextasks,
#: nexlore: secret in ``X-Pairing-Secret``, ``{key, account}``, ``not_signed_in``), ``mail`` (nexmail: the same with
#: German codes and ``detail`` as text). A request with ``X-Nex-App`` is always answered in ``nex``.
FORM_NEX = "nex"
FORM_TASKS = "tasks"
FORM_MAIL = "mail"
FORMS = (FORM_NEX, FORM_TASKS, FORM_MAIL)

#: The header of the apps built on NexKonto: ``<app>-ios/<version> (<model>; iOS <x>)``.
CLIENT_HEADER = "X-Nex-App"

#: What ``device_kind`` may be; ``ios`` when the app names none.
DEVICE_KINDS = ("ios", "ipados", "mac")

#: How a device came in (``Device.via``); older rows carry what the app wrote then (nexpaper ``token``, ``oauth``).
VIA_QR = "qr"
VIA_CODE = "code"
VIA_BROWSER = "browser"
VIA_ICLOUD = "icloud"
VIAS = (VIA_QR, VIA_CODE, VIA_BROWSER, VIA_ICLOUD)

#: The operator's switches (the same settings as ``schluessel``): devices may use the app, new devices may come in.
SWITCH_APP = "app"
SWITCH_PAIRING = "pairing"
SWITCHES = (SWITCH_APP, SWITCH_PAIRING)

#: The kinds of notification the module sends itself (G18, G29); the app's own come in ``AppConfig.kinds``.
#: The forms of the QR code's link (G58): ``connect`` for every app, ``pair`` as the published nexpaper-ios reads it.
LINK_FORMS = ("connect", "pair")
KIND_UPDATE = "update"
KIND_SECURITY = "security"

#: The letters of a code to type: no 0, O, 1, I, which are mixed up (nextasks, nexlore, nexmail).
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

LANGUAGES = ("de", "en", "fr")

_APP = re.compile(r"[a-z][a-z0-9-]{1,30}")
_PREFIX = re.compile(r"[a-z][a-z0-9_]{1,14}")
_KIND = re.compile(r"[a-z][a-z0-9_]{0,31}")


@dataclass(frozen=True)
class PushKind:
    """One kind of notification: its id (what the device lists in ``understands``), its words per language, whether
    it is on where nobody chose, whether only operators get it."""

    id: str
    #: ``{"de": …, "en": …, "fr": …}``; ``{app}`` is the app's name.
    title: Mapping[str, str]
    hint: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    default_on: bool = True
    operator_only: bool = False

    def __post_init__(self) -> None:
        if not _KIND.fullmatch(self.id):
            raise ValueError(f"kind {self.id!r} must be lower-case letters, digits and underscores")
        for words in (self.title, self.hint):
            for language in words:
                if language not in LANGUAGES:
                    raise ValueError(f"kind {self.id}: language {language!r} must be one of {LANGUAGES}")
        if "en" not in self.title:
            raise ValueError(f"kind {self.id}: needs at least an English title")

    def words(self, language: str, app: str) -> tuple[str, str]:
        """Title and hint in ``language`` (English where the language is missing)."""
        title = self.title.get(language) or self.title["en"]
        hint = self.hint.get(language) or self.hint.get("en", "")
        return title.replace("{app}", app), hint.replace("{app}", app)


@dataclass(frozen=True)
class AppConfig:
    """The app's devices. Everything but ``app``, ``scheme`` and ``token_prefix`` has the value of the plan."""

    #: ``nexnotes``: named in notifications and hints.
    app: str
    #: The scheme of the iPhone app's links (``nexnotes://connect``).
    scheme: str
    #: The prefix of a new device key (``nnd_``); never changed.
    token_prefix: str
    #: More prefixes keys of older versions may have.
    accepted_prefixes: tuple[str, ...] = ()
    #: Random bytes of a new key (``secrets.token_urlsafe``): 32; nexmail 48.
    token_bytes: int = 32
    #: The old form of the app routes for requests without ``X-Nex-App``.
    form: str = FORM_NEX
    #: The code to type: 8 characters (nexpaper 12), valid ``pairing_minutes`` like the QR code.
    code_length: int = 8
    pairing_minutes: int = 10
    #: Pairings of one account that may wait at once (nexpaper 1: a new one ends the one before, ``pairing.start``).
    open_pairings: int = 5
    #: Since 0.1.1 (G58): the QR code's link. ``connect`` (every app): ``<scheme>://connect?server=&address=&pairing=
    #: &secret=``. ``pair`` (nexpaper): ``<scheme>://pair?server=&code=&address=&pairing=&secret=``, which the published
    #: nexpaper-ios reads by ``server`` and ``code`` and a coming app by ``pairing`` and ``secret``.
    link_form: str = "connect"
    #: The one-time code of the sign-in in the browser.
    connect_minutes: int = 5
    max_devices: int = 30
    siblings_per_hour: int = 5
    #: A device not used for this long is disconnected at its next call (G27).
    idle_days: int = 365
    #: The longest device name.
    name_max: int = 80
    #: ``last seen`` is written at most this often.
    seen_every: timedelta = timedelta(minutes=1)
    #: The app in the App Store; empty while there is none.
    app_store_url: str = ""
    #: Whether there is an iPhone app at all (nexdiary, nexfolk not yet): without one no page shows the card.
    has_app: bool = True
    #: The push relay; empty, or a callable giving empty: nothing goes out (the operator's setting).
    relay_url: str | Callable[[], str] = "https://push.nexapps.dev"
    #: The ``info`` of HKDF in the sealing of a message (``nexnotes-push-v1``).
    push_info: str = ""
    #: The app's kinds of notification, in the order of the list.
    kinds: tuple[PushKind, ...] = ()
    #: What a device that sends no ``understands`` gets: exactly the kinds the published app knows (G16).
    legacy_kinds: tuple[str, ...] = ()
    #: The operator's switches the app has; without ``pairing`` new devices follow ``app`` (nexlore, nexmail).
    switches: tuple[str, ...] = SWITCHES
    #: The type of an account's id and a device's id in the app (nexmail: ``str``).
    account_id: type = int
    device_id: type = int
    #: A fixed mark of the server that the module's notifications carry as ``server`` (nexnotes ``server_id``).
    server_id: Callable[[], str] | None = None

    def __post_init__(self) -> None:
        if not _APP.fullmatch(self.app) or not _APP.fullmatch(self.scheme):
            raise ValueError("app and scheme must be lower-case letters, digits and dashes")
        for prefix in (self.token_prefix, *self.accepted_prefixes):
            if not _PREFIX.fullmatch(prefix):
                raise ValueError(f"prefix {prefix!r} must be lower-case letters, digits and underscores")
        if self.link_form not in LINK_FORMS:
            raise ValueError(f"link_form {self.link_form!r} must be one of {LINK_FORMS}")
        if self.form not in FORMS:
            raise ValueError(f"form {self.form!r} must be one of {FORMS}")
        if not 6 <= self.code_length <= 16 or not 1 <= self.pairing_minutes <= 60 or not 1 <= self.open_pairings:
            raise ValueError("pairing limits out of range")
        if not 1 <= self.connect_minutes <= 15 or not 1 <= self.max_devices <= 1000:
            raise ValueError("limits out of range")
        if not 1 <= self.siblings_per_hour <= 100 or not 30 <= self.idle_days or not 10 <= self.name_max <= 400:
            raise ValueError("limits out of range")
        if not 16 <= self.token_bytes <= 64:
            raise ValueError("token_bytes out of range")
        for switch in self.switches:
            if switch not in SWITCHES:
                raise ValueError(f"switch {switch!r} must be one of {SWITCHES}")
        if SWITCH_APP not in self.switches:
            raise ValueError("every app has the switch app")
        ids = [kind.id for kind in self.all_kinds]
        if len(ids) != len(set(ids)):
            raise ValueError("each kind of notification once (update and security are the module's)")
        for kind in self.legacy_kinds:
            if kind not in ids:
                raise ValueError(f"legacy kind {kind!r} is no kind of the app")
        if self.account_id not in (int, str) or self.device_id not in (int, str):
            raise ValueError("account_id and device_id must be int or str")

    @property
    def prefixes(self) -> tuple[str, ...]:
        return (self.token_prefix, *self.accepted_prefixes)

    @property
    def all_kinds(self) -> tuple[PushKind, ...]:
        """The app's kinds, then the module's: ``security`` for everybody, ``update`` for operators."""
        return (*self.kinds, SECURITY, UPDATE)

    def kind(self, kind_id: str) -> PushKind | None:
        return next((kind for kind in self.all_kinds if kind.id == kind_id), None)

    def relay(self) -> str:
        """The relay's address without a trailing slash; empty: nothing goes out."""
        found = self.relay_url() if callable(self.relay_url) else self.relay_url
        return (found or "").strip().rstrip("/")

    @property
    def pairing_switch(self) -> str:
        """The switch that lets new devices in: ``pairing`` where the app has it, else ``app``."""
        return SWITCH_PAIRING if SWITCH_PAIRING in self.switches else SWITCH_APP


#: The module's kinds (G18, G29), with the words of the list in the app and in the browser.
SECURITY = PushKind(
    id=KIND_SECURITY,
    title=MappingProxyType(
        {"de": "Neues Gerät verbunden", "en": "New device connected", "fr": "Nouvel appareil connecté"}
    ),
    hint=MappingProxyType(
        {
            "de": "Wenn ein weiteres Gerät mit deinem Konto verbunden wird.",
            "en": "When another device is connected to your account.",
            "fr": "Lorsqu'un autre appareil est connecté à ton compte.",
        }
    ),
)
UPDATE = PushKind(
    id=KIND_UPDATE,
    title=MappingProxyType(
        {"de": "Neue Version von {app}", "en": "New version of {app}", "fr": "Nouvelle version de {app}"}
    ),
    hint=MappingProxyType(
        {
            "de": "Einmal je Version, nur für Betreiber.",
            "en": "Once per version, for operators only.",
            "fr": "Une fois par version, seulement pour les administrateurs.",
        }
    ),
    operator_only=True,
)
