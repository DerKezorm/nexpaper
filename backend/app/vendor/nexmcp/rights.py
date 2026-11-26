"""What a key may do with a tool: allow, ask, or nothing (the tool does not exist for it). In this order: a tool the
operator blocked, above the key's level (capped by the operator's highest level), for operators only, or needing an
extra the key lacks, is not there; then the key's own right for the tool, else its group's default (decision 3: allow);
a tool that only looks is never asked for; "deny" makes it disappear. ``request_status`` is always there."""

from __future__ import annotations

from collections.abc import Iterable

from .config import ALLOW, ASK, DENY, RIGHTS, AppConfig, Tool, all_tools
from .model import Caller


def level_of(config: AppConfig, caller: Caller, max_level: str | None) -> str:
    """The key's level, never above the operator's highest (lowered, it holds for keys made before as well)."""
    ceiling = max_level if max_level in config.levels else config.highest
    if caller.level not in config.levels:
        return config.levels[0]
    return caller.level if config.at_least(ceiling, caller.level) else ceiling


def why_not(config: AppConfig, caller: Caller, tool: Tool, blocked: Iterable[str], max_level: str | None) -> str | None:
    """Why the tool is not there for the key whatever its right says (for the greyed rows of "Rights per tool"):
    ``blocked``, ``level``, ``admin``, ``extra``; ``None`` when nothing stands in the way."""
    if tool.always:
        return None
    if tool.name in set(blocked):
        return "blocked"
    if not config.at_least(level_of(config, caller, max_level), tool.level):
        return "level"
    if tool.admin_only and not caller.admin:
        return "admin"
    if tool.needs is not None and not caller.options.get(tool.needs):
        return "extra"
    return None


def chosen(config: AppConfig, caller: Caller, tool: Tool) -> str:
    """The right set for the tool: the key's own, else the group's default; a looking tool is never "ask"."""
    right = caller.rights.get(tool.name, config.default_rights.get(tool.group, ALLOW))
    if right not in RIGHTS:
        right = config.default_rights.get(tool.group, ALLOW)
    if tool.looks_only and right == ASK:
        right = ALLOW
    return right


def right(config: AppConfig, caller: Caller, tool: Tool, blocked: Iterable[str], max_level: str | None) -> str | None:
    """``allow``, ``ask``, or ``None`` when the tool does not exist for the key."""
    if tool.always:
        return ALLOW
    if why_not(config, caller, tool, blocked, max_level) is not None:
        return None
    found = chosen(config, caller, tool)
    return None if found == DENY else found


def visible(config: AppConfig, caller: Caller, blocked: Iterable[str], max_level: str | None) -> list[Tool]:
    fixed = tuple(blocked)
    return [tool for tool in all_tools(config) if right(config, caller, tool, fixed, max_level) is not None]


def own_rights(config: AppConfig, wanted: dict[str, str]) -> dict[str, str]:
    """What a key stores of the rights an account sets: only known tools, only where they differ from the group's
    default; a looking tool set to "ask" is stored as allow (so: not at all)."""
    kept: dict[str, str] = {}
    for name, value in wanted.items():
        tool = config.tool(name)
        if tool is None or tool.always or value not in RIGHTS:
            continue
        if tool.looks_only and value == ASK:
            value = ALLOW
        if value != config.default_rights.get(tool.group, ALLOW):
            kept[name] = value
    return kept
