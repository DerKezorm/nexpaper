"""The template the app offers is taken by its own server (E59): uploaded as it was downloaded, it becomes a language
with as many texts as it holds. nexpaper's English had lists, and its server refused its own template with
``not_text``; since 1.0.2 the module leaves such things out of the template (``texts_only``, ``textsOnly``). Copied
unchanged into every app."""

from __future__ import annotations

import json
from typing import Any

from sprachen_contract import files_in, upload


def _leaves(tree: object) -> int:
    if isinstance(tree, str):
        return 1
    return sum(_leaves(value) for value in tree.values()) if isinstance(tree, dict) else 0


def test_the_offered_template_is_taken_by_the_server(app: Any, operator: Any, reader: Any) -> None:
    offered = app.offered_template()
    assert isinstance(offered, dict) and "_meta" in offered
    texts = {key: value for key, value in offered.items() if key != "_meta"}
    assert _leaves(texts) > 0, "a template without texts"
    answer = upload(operator, app.prefix, "eo", json.dumps(offered, ensure_ascii=False).encode("utf-8"))
    assert answer.status_code == 200, answer.text
    assert answer.json()["keys"] == _leaves(texts)
    assert reader.get(f"{app.prefix}/eo").json() == texts


def test_texts_only_leaves_out_what_a_file_cannot_carry(nexsprachen: Any, app: Any, operator: Any) -> None:
    """The rules behind the template, against the server's own check: what ``texts_only`` keeps is always taken."""
    deep: Any = "deep"
    for _ in range(12):
        deep = {"k": deep}
    mixed = {"_meta": {"name": "x"}, "a": "A", "days": ["Mo", "Di"], "n": 3, "none": None, "empty": {}, "": "x",
             "__proto__": {"b": "B"}, "k" * 121: "long", "group": {"b": "B", "list": [1]}, "deep": deep}
    kept = nexsprachen.texts_only(mixed)
    assert kept["a"] == "A" and kept["group"] == {"b": "B"}
    assert not {"_meta", "days", "n", "none", "empty", "", "__proto__", "k" * 121} & set(kept)
    answer = upload(operator, app.prefix, "eo", json.dumps(kept).encode("utf-8"))
    assert answer.status_code == 200, answer.text
    assert files_in(app.folder()) == ["eo.json"]
