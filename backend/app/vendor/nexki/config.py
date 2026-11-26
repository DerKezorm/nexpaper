"""What an app tells the module: its name, its tasks, the ways it offers, its limits. The defaults are the decisions of
the plan (``Entwurf KI-Anbieter``, K1 to K7, and what was decided while building, K8 onwards); an app sets its own
limits from what it had before (nexpaper 200 a day on the server, nexdiary 6 a minute and 60 a day per person)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: The two interfaces a service may speak. "Local" is no interface but a place (the own network, K9).
APIS = ("openai", "messages")
#: How the AI is set up on a server (K2): one service of the operator for all, or each account its own.
MODES = ("shared", "own")
#: The Messages API's version header, its value, and the provider's address for the tile. The only product names of the
#: package stand here (the apps' guard against attributions lists this file for them).
MESSAGES_VERSION_HEADER = "anthropic-version"
MESSAGES_VERSION = "2023-06-01"
MESSAGES_URL = "https://api.anthropic.com/v1/"

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _account_context(account_id: Any) -> str:
    return f"account:{account_id}:ai"


@dataclass(frozen=True)
class Task:
    """One thing the app asks of the AI.

    ``manual``: a person pressed a button for it (kept word for word in "what went out", K5); automatic tasks (a
    proposal for every new document, writing in the morning) are kept as a line without content. ``temperature`` None
    leaves it to the service. ``max_out`` is the room for the answer in the model's units; a thinking model gets
    ``AppConfig.thinking_out`` on top. ``seconds`` is the deadline of the whole request, the answer read included."""

    id: str
    manual: bool = True
    temperature: float | None = 0.3
    max_out: int = 1_200
    seconds: float = 180.0

    def __post_init__(self) -> None:
        if not _NAME.match(self.id):
            raise ValueError(f"a task's id is lower case letters, digits and _: {self.id!r}")
        if self.max_out < 1 or self.seconds <= 0:
            raise ValueError(f"task {self.id}: max_out and seconds must be positive")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError(f"task {self.id}: temperature between 0 and 2")


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    tasks: tuple[Task, ...]
    #: The ways the operator may choose between (K2); an app that never had own accesses may offer only "shared".
    modes: tuple[str, ...] = MODES
    #: The context the operator's key is sealed with (nexpaper, nexdiary, nexlore: ``operator:ai-key``).
    operator_key_context: str = "operator:ai-key"
    #: The context an account's own key is sealed with (nexmail ``benutzer:<id>:ki``; nexlore its own).
    account_key_context: Callable[[Any], str] = field(default=_account_context)
    # The brakes (K10): per person at once is always 1.
    per_minute: int = 20
    #: Per person and day; 0: none.
    per_day: int = 0
    #: Requests on the whole server at once.
    at_once: int = 4
    #: Requests on the whole server per day (a service paid by the request); 0: none.
    server_day: int = 0
    #: The operator's model lists and probes per minute.
    operator_per_minute: int = 10
    # The network.
    list_seconds: float = 10.0
    connect_seconds: float = 10.0
    max_answer: int = 2 * 1024 * 1024
    max_models: int = 500
    #: What a model that thinks before it answers gets on top of a task's ``max_out``.
    thinking_out: int = 4_000
    #: How much of a service's own words about an error the person sees (only from the internet).
    said_chars: int = 300
    # "What went out" (K5).
    events_days: int = 14
    events_max: int = 200
    #: The probe of the operator: nothing of anybody's data in it.
    probe_text: str = "Answer with the single word OK."
    #: The address the interface fills in for the Messages API (its tile).
    messages_url: str = MESSAGES_URL

    def __post_init__(self) -> None:
        if not self.app_name:
            raise ValueError("app_name is needed")
        ids = [task.id for task in self.tasks]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("tasks: at least one, each id once")
        if not self.modes or set(self.modes) - set(MODES) or len(set(self.modes)) != len(self.modes):
            raise ValueError(f"modes is a choice of {MODES}")
        if "shared" not in self.modes:
            raise ValueError("every app offers the operator's service for all (K2)")
        for name in ("per_minute", "at_once", "operator_per_minute", "max_answer", "max_models", "events_max"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        for name in ("per_day", "server_day", "thinking_out", "said_chars"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.list_seconds <= 0 or self.connect_seconds <= 0 or self.events_days < 1:
            raise ValueError("list_seconds, connect_seconds and events_days must be positive")
        if self.operator_key_context == self.account_key_context(1):
            raise ValueError("the operator's key and an account's key need contexts of their own")

    def task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        from .errors import AiRefused

        raise AiRefused("ai_task_unknown")
