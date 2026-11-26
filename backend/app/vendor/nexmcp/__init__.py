"""nexmcp: the AI tools (MCP) of every nex app, the same everywhere.

Vendored unchanged into ``backend/app/vendor/nexmcp/``; a test in the app compares the files with the checksums in
``MANIFEST.json``, so a change is made in the module's source, never in the copy.

The module brings the protocol, the walls, the check of arguments, OAuth for programs, levels and rights per tool,
requests waiting for the account, the brakes; the app brings its tools, its check of a key (module ``schluessel``)
and its tables behind the ``Store``:

- ``config``: the app's MCP (``AppConfig``) and its tools (``Tool``);
- ``model``: who calls (``Caller``), programs, codes, requests, and the ``Store``;
- ``arguments``: the check of a call's arguments against the tool's schema;
- ``rights``: what a key may do with a tool;
- ``protocol``: JSON-RPC, ``tools/list``, ``tools/call`` and the tool's answer;
- ``requests``: the right "ask", ``request_status``, allowing and declining;
- ``oauth``: metadata, registration, consent, tokens, revoking;
- ``oauthcore``: the OAuth core shared with the module ``verbinden`` (since 1.1.0);
- ``brake``: the brakes in memory;
- ``errors``: the refusals;
- ``api``: the routes (needs FastAPI; imported only by ``from app.vendor.nexmcp import api``).
"""

from __future__ import annotations

from . import arguments, brake, oauth, oauthcore, protocol, requests, rights
from .config import (
    ALLOW,
    ASK,
    DEFAULT_RIGHTS,
    DENY,
    GROUPS,
    PROTOCOL_VERSIONS,
    RIGHTS,
    AppConfig,
    Tool,
    all_tools,
)
from .errors import CODES, McpRefused, OAuthError, ToolError
from .model import STATES, Caller, Client, Code, Grant, Program, Request, Store
from .protocol import Context, Session

__version__ = "1.1.1"

__all__ = [
    "ALLOW",
    "ASK",
    "CODES",
    "DEFAULT_RIGHTS",
    "DENY",
    "GROUPS",
    "PROTOCOL_VERSIONS",
    "RIGHTS",
    "STATES",
    "AppConfig",
    "Caller",
    "Client",
    "Code",
    "Context",
    "Grant",
    "McpRefused",
    "OAuthError",
    "Program",
    "Request",
    "Session",
    "Store",
    "Tool",
    "ToolError",
    "__version__",
    "all_tools",
    "arguments",
    "brake",
    "oauth",
    "oauthcore",
    "protocol",
    "requests",
    "rights",
]
