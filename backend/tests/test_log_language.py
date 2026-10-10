"""Log messages are English and stay so.

A mixed log is not searchable: whoever looks for "not reachable" misses the German half of the cases, and a
line pasted into a bug report or a web search must be readable to everyone. Comments, docstrings and the UI are
not affected.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
#: Words that do not exist in English and turn up in real messages. Deliberately without "in", "so" and other
#: doubles. Matched as whole words, case-insensitively.
GERMAN_WORDS = ("und", "nicht", "wird", "wurde", "der", "die", "das", "für", "mit", "ist", "kein", "keine", "wurden")
GERMAN = re.compile(r"(?<![\w%])(" + "|".join(GERMAN_WORDS) + r")(?![\w])", re.IGNORECASE)
UMLAUTS = re.compile(r"[äöüÄÖÜß]")
#: A run of the whole app has at least this many log calls; fewer means the scan looked in the wrong place.
#: M0 has 16. Raise it with each milestone, a little below what the app has.
FLOOR = 15


def is_log_call(node: ast.Call) -> bool:
    target = node.func
    if not isinstance(target, ast.Attribute) or target.attr not in LOG_METHODS:
        return False
    root = target.value
    if isinstance(root, ast.Call):
        return "getLogger" in ast.unparse(root.func)
    name = getattr(root, "id", "") or getattr(root, "attr", "")
    return "log" in name.lower()


def message_texts(node: ast.Call) -> list[str]:
    """Every fixed text a log call carries: the format string and constant arguments after it."""
    arguments = node.args[1:] if isinstance(node.func, ast.Attribute) and node.func.attr == "log" else node.args
    texts: list[str] = []
    for argument in arguments:
        branches = (argument.body, argument.orelse) if isinstance(argument, ast.IfExp) else (argument,)
        for branch in branches:
            if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                texts.append(branch.value)
            elif isinstance(branch, ast.JoinedStr):
                texts.append("".join(p.value for p in branch.values if isinstance(p, ast.Constant) and isinstance(p.value, str)))
    return texts


def messages() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and is_log_call(node):
                for text in message_texts(node):
                    found.append((str(path.relative_to(APP.parent)), node.lineno, text))
    return found


def offending(text: str) -> str | None:
    if UMLAUTS.search(text):
        return "umlaut"
    match = GERMAN.search(text)
    return match.group(1) if match else None


def test_every_log_message_is_english() -> None:
    found = messages()
    assert len(found) >= FLOOR, f"only {len(found)} log calls found; is the scan looking at the app?"
    bad = [f"{path}:{line}: {word!r} in {text!r}" for path, line, text in found if (word := offending(text))]
    assert not bad, "German in log messages:\n" + "\n".join(bad)


def test_the_scan_knows_german_when_it_sees_it() -> None:
    assert offending("Verbindung wird aufgebaut") == "wird"
    assert offending("Schlüssel geladen") == "umlaut"
    assert offending("Die Sitzung ist zu Ende") in {"die", "Die", "ist"}
    assert offending("Session ended target=%s") is None
    assert offending("Connection %s died: %s") is None, "'died' is not 'die'"
    assert offending("Added column %s.%s") is None


def test_the_scan_sees_calls_on_named_loggers_and_on_getlogger() -> None:
    tree = ast.parse(
        'logger.info("a")\n'
        'logging.getLogger("x").warning("b")\n'
        'self.log.debug("c")\n'
        'log.log(logging.INFO, "d")\n'
        'print("not a log call")\n'
    )
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and is_log_call(node)]
    assert [message_texts(call) for call in calls] == [["a"], ["b"], ["c"], ["d"]]


# --- The family's English words in what the server says (decided 06.10.2026) ------------------------------------------
#
# The trash is "trash", never "bin"; a rule "applies", it never "Holds". Checked wherever the server speaks to people:
# log lines, the API's own documentation (summary=, description=), refusals (detail=, error(), detail() and the typed
# errors, whose second argument is the sentence) and mails. Docstrings and comments are not read; neither are paths,
# routes or names such as "/bin", ".venv/bin" or "clients_bin", nor the word as a key on its own ("bin").

AVOIDED = (
    ("bin", re.compile(r"(?<![\w/.-])bins?(?![\w/-])(?!\.\w)", re.IGNORECASE)),
    ("Holds", re.compile(r"(?<![\w/.-])Holds?(?![\w/-])(?!\.\w)")),
)
SPOKEN_KEYWORDS = {"summary", "description", "detail"}
MAIL_FILES = {"mailer.py", "email_change.py", "notify.py"}
#: The app speaks in at least this many places; fewer means the scan looked in the wrong place.
SPOKEN_FLOOR = 300


def texts_of(node: ast.AST) -> list[str]:
    """The fixed text of a string, of an f-string (its constant parts) or of both branches of ``a if b else c``."""
    if isinstance(node, ast.IfExp):
        return texts_of(node.body) + texts_of(node.orelse)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return ["".join(p.value for p in node.values if isinstance(p, ast.Constant) and isinstance(p.value, str))]
    return []


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def spoken_in(tree: ast.AST, mail: bool = False) -> list[tuple[int, str]]:
    """What a module says to people: log lines, API documentation, refusals and, in a mail module, every text."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if is_log_call(node):
            found += [(node.lineno, text) for text in message_texts(node)]
        for keyword in node.keywords:
            if keyword.arg in SPOKEN_KEYWORDS:
                found += [(node.lineno, text) for text in texts_of(keyword.value)]
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name in {"error", "detail"} or name.endswith("Error") or name == "HTTPException":
            for argument in node.args[1:]:
                found += [(node.lineno, text) for text in texts_of(argument)]
    if mail:
        skip = _docstrings(tree)
        # The constant parts of an f-string are read with the f-string, not a second time on their own.
        skip |= {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in ast.walk(node)
                 if part is not node}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Constant, ast.JoinedStr)) and id(node) not in skip:
                found += [(getattr(node, "lineno", 0), text) for text in texts_of(node)]
    return found


def spoken() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, text in spoken_in(tree, mail=path.name in MAIL_FILES):
            found.append((str(path.relative_to(APP.parent)), line, text))
    return found


def avoided(text: str) -> str | None:
    for word, pattern in AVOIDED:
        if pattern.search(text):
            return word
    return None


def test_what_the_server_says_uses_the_family_words() -> None:
    found = spoken()
    assert len(found) >= SPOKEN_FLOOR, f"only {len(found)} texts found; is the scan looking at the app?"
    bad = [f"{path}:{line}: {word!r} in {text!r}" for path, line, text in found if (word := avoided(text))]
    assert not bad, "Words the family does not use:\n" + "\n".join(bad)


def test_the_word_scan_finds_what_it_should_and_leaves_names_alone() -> None:
    tree = ast.parse(
        'logger.info(f"Day {day.date} moved to the bin by {who}")\n'
        '@router.get("/bin", summary="Days in the BIN")\n'
        'def bin(): pass\n'
        'raise error("code", "Holds in every app.")\n'
        'raise DayError("code", f"{name} is in the bins")\n'
        'thing(description="Moved to trash", detail="Gone for good")\n'
        'logger.info("Wrote .venv/bin, bin.exe, clients_bin and /bin")\n'
        'logger.info(f"Mail to {host}: it went to the bin.")\n'
        'data = {"bin": [], "clients_bin": []}\n'
    )
    texts = [text for _line, text in spoken_in(tree)]
    assert [avoided(text) for text in texts] == ["bin", "bin", "Holds", "bin", None, None, None, "bin"]
    mail = ast.parse('"""A docstring about the bin may stay."""\nbody = f"Hello {name}, it is in the bin now."\n')
    assert [avoided(text) for _line, text in spoken_in(mail, mail=True)] == ["bin"]
