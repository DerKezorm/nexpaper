"""What a request carries and how an answer is read, with every peculiarity of the models in one place. Gathered from
the four apps, each measured there in use:

* Newer models choose the temperature themselves and turn down a request that sets it ("`temperature` is deprecated
  for this model", nexmail 29.09.2026): asked once more without it.
* Newer OpenAI models take the limit only as ``max_completion_tokens`` and say so in their refusal (nexdiary issue
  #3). They think before they answer, and the thoughts count against the limit: room for them on top
  (``AppConfig.thinking_out``) and ``reasoning_effort: "low"``.
* A thinking model in the own network (Qwen3, DeepSeek-R1 through Ollama) spends the few tokens of an answer on its
  thoughts and gives back nothing; Ollama's OpenAI door takes ``reasoning_effort: "none"`` (nexpaper 1.5.1). A model
  that cannot think turns it down, Ollama with "does not support thinking" (nexmail): once more without.
* A service that does not take tools turns them down: once more without.
* Every field is left out or renamed at most once, and only when that changes the request: asking again always ends.
* The Messages API keeps ``max_tokens`` whatever its refusal says, and knows no ``reasoning_effort``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import AiRefused

#: (field, words of a refusal that name it). ``max_tokens`` is not dropped but renamed.
OPTIONAL_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("temperature", ("temperature",)),
    ("reasoning_effort", ("reasoning", "think")),
    ("max_tokens", ("max_completion_tokens",)),
    ("tools", ("tool",)),
)


def body(
    api: str,
    model: str,
    system: str,
    user: str,
    *,
    max_out: int,
    temperature: float | None,
    local: bool,
    thinking_out: int,
    left_out: frozenset[str] = frozenset(),
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The request, without the fields in ``left_out`` (``max_tokens`` there means: renamed)."""
    made: dict[str, Any] = {"model": model}
    renamed = api == "openai" and "max_tokens" in left_out
    if renamed:
        made["max_completion_tokens"] = max_out + thinking_out
    else:
        made["max_tokens"] = max_out
    if temperature is not None and "temperature" not in left_out:
        made["temperature"] = temperature
    if api == "openai" and "reasoning_effort" not in left_out:
        if local:
            made["reasoning_effort"] = "none"
        elif renamed:
            made["reasoning_effort"] = "low"
    if tools and "tools" not in left_out:
        made["tools"] = tools
    if api == "messages":
        made["system"] = system
        made["messages"] = [{"role": "user", "content": user}]
    else:
        made["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        made["stream"] = False
    return made


def next_left_out(said: str, left_out: frozenset[str], make: Any) -> frozenset[str] | None:
    """After a 400: the fields to leave out next, or ``None`` when the refusal names nothing that would change the
    request (then it is not sent again). ``make(left_out)`` builds the request."""
    said = said.lower()
    carried = make(left_out)
    for name, words in OPTIONAL_FIELDS:
        if name in left_out or name not in carried:
            continue
        if not any(word in said for word in words):
            continue
        if name == "max_tokens" and "max_completion_tokens" not in said:
            continue
        candidate = left_out | {name}
        if make(candidate) != carried:
            return candidate
    return None


def ran_out(api: str, data: Any) -> bool:
    """Whether the service stopped because the room for the answer was used up."""
    try:
        if api == "messages":
            return data.get("stop_reason") == "max_tokens"
        return data["choices"][0].get("finish_reason") == "length"
    except (AttributeError, KeyError, IndexError, TypeError):
        return False


def content_of(api: str, data: Any) -> str:
    """The text of an answer (``ai_unreadable`` when it has no form the module knows)."""
    try:
        if api == "messages":
            parts = data["content"]
            if not isinstance(parts, list):
                raise TypeError
            return "".join(
                part.get("text", "") for part in parts if isinstance(part, dict) and part.get("type") == "text"
            )
        content = data["choices"][0]["message"].get("content")
        if content is None:
            return ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            raise TypeError
        return content
    except (AttributeError, KeyError, IndexError, TypeError) as exc:
        raise AiRefused("ai_unreadable") from exc


def tool_calls_of(api: str, data: Any) -> list[dict[str, Any]]:
    """The tool calls of an answer, as ``{"id", "name", "arguments"}`` (arguments as text), for an app that offers
    tools (nexlore's "Frag Lore"). Anything without a name is passed over."""
    found: list[dict[str, Any]] = []
    try:
        if api == "messages":
            for part in data.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name"):
                    found.append({"id": str(part.get("id") or ""), "name": str(part["name"]),
                                  "arguments": json.dumps(part.get("input") or {})})
        else:
            for call in data["choices"][0]["message"].get("tool_calls") or []:
                function = call.get("function") or {}
                if function.get("name"):
                    found.append({"id": str(call.get("id") or ""), "name": str(function["name"]),
                                  "arguments": str(function.get("arguments") or "{}")})
    except (AttributeError, KeyError, IndexError, TypeError):
        return []
    return found


_FENCE = re.compile(r"\A`{3,}[a-zA-Z]*[ \t]*\n(.*?)\n?`{3,}\Z", re.DOTALL)


def unfence(text: str) -> str:
    """The answer without a code fence around all of it (models like to wrap Markdown or JSON in one)."""
    stripped = text.strip()
    found = _FENCE.match(stripped)
    return found.group(1).strip() if found else stripped


def said(data: Any, limit: int) -> str:
    """A service's own words about an error (``{"error": {"message": …}}`` nearly everywhere), one line, short."""
    found = data.get("error") if isinstance(data, dict) else None
    if isinstance(found, dict):
        found = found.get("message")
    if not isinstance(found, str):
        return ""
    return " ".join("".join(c if c.isprintable() else " " for c in found).split())[:limit]
