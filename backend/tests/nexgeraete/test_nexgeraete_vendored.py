"""The copied module is the module: every file as ``MANIFEST.json`` names it, and it needs nothing beyond the
standard library, FastAPI (its routes), segno (the QR code) and cryptography (sealing). Runs in the app's own test run
and CI, which see only the app's repository. Red means: a file was changed in the app. Change it in the module's
source and copy it again; never here."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any


def _manifest(app: Any) -> tuple[Path, dict]:
    package = importlib.import_module(app.package)
    folder = Path(package.__file__).resolve().parent
    manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
    depth = len(Path(manifest["vendor_path"]).parts)
    return folder.parents[depth - 1], manifest


def _digest(path: Path) -> str:
    """``sha256-<base64>`` of the file with line ends as LF (a form the commit scanners pass, unlike 64 hex)."""
    raw = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest()
    return "sha256-" + base64.b64encode(raw).decode("ascii")


def test_every_copied_file_equals_the_module(app: Any) -> None:
    root, manifest = _manifest(app)
    assert manifest["module"] == "geraete" and len(manifest["files"]) >= 20
    deviating = [
        name
        for name, expected in manifest["files"].items()
        if not (root / name).is_file() or _digest(root / name) != expected
    ]
    assert deviating == [], f"changed in the app instead of in the module's source: {deviating}"


def test_the_copied_package_carries_the_version_of_the_manifest(app: Any) -> None:
    _, manifest = _manifest(app)
    package = importlib.import_module(app.package)
    assert package.__version__ == manifest["version"]


def test_the_module_needs_only_fastapi_segno_and_cryptography_beyond_the_standard_library(app: Any) -> None:
    _, manifest = _manifest(app)
    assert set(manifest["requires"]) == {"fastapi", "segno", "cryptography"}


def test_the_module_s_bodies_keep_their_names_beside_the_app_s(app: Any) -> None:
    """G59: in the app's description the module's bodies are ``Nexgeraete…``, and none of the app's names is
    renamed into a long module path (FastAPI does that when two models share a name)."""
    schemas = app.client("anonymous").app.openapi().get("components", {}).get("schemas", {})
    renamed = [name for name in schemas if "__" in name]
    assert renamed == [], renamed
    for name in schemas:
        if name.endswith(("PairIn", "PushIn", "NameIn", "AddressIn", "ConnectIn")) and name.startswith("Nex"):
            assert name.startswith("Nexgeraete"), name
