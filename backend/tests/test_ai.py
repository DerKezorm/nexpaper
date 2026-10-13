"""The AI of the operator: only the operator chooses the service, nothing goes out on its own, the address is no way into
the own network, and every request has its deadline and its limits. Always against a stand-in for the model
(``httpx.MockTransport``) in both formats, never a real service and never a real key: the key is made for the run.
The proposals for documents come with the block that sorts them; here the setting, the list of models and the probe
that every request of that block will go through."""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import ai, logs

from .conftest import PASSWORD, new_client, person

CLOUD = "https://ai.example.com/v1"
LOCAL = "http://ollama.example.com:11434/v1"
PUBLIC_IP = "93.184.216.34"
HOME_IP = "192.168.1.20"


def made_key() -> str:
    return "sk-" + secrets.token_hex(20)


class Model:
    """The stand-in for the model: records what came, answers what it is told (both formats)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: Callable[[httpx.Request], httpx.Response] = self.write
        self.text = "OK"

    def write(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "model-a", "display_name": "Model A"}, {"id": "model-b"}]})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": self.text}], "stop_reason": "end_turn"})
        return httpx.Response(200, json={"choices": [{"message": {"content": self.text}}]})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Iterator[Model]:
    stand_in = Model()
    ai.transport = httpx.MockTransport(stand_in.handle)
    monkeypatch.setattr(ai, "resolver", lambda host, port: [HOME_IP] if "ollama" in host else [PUBLIC_IP])
    yield stand_in
    ai.transport = None


def resolving_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    monkeypatch.setattr(ai, "resolver", lambda host, port: list(addresses))


def set_up(operator: TestClient, provider: str = "openai", url: str = CLOUD, key: str | None = None,
           model_name: str = "model-a") -> str:
    key = made_key() if key is None and provider != "local" else key
    body: dict[str, Any] = {"provider": provider, "url": url, "model": model_name}
    if key is not None:
        body["key"] = key
    answer = operator.put("/api/v1/settings/ai", json=body)
    assert answer.status_code == 200, answer.text
    return key or ""


def probe(client: TestClient) -> httpx.Response:
    """The one request of the service that is made on the operator's own: every later request goes the same way."""
    return client.post("/api/v1/settings/ai/probe")


# --- The operator decides, none from the start -----------------------------------------------------------------------


def test_there_is_no_ai_from_the_start_and_nothing_goes_out(client: TestClient, account: Account, model: Model) -> None:
    assert client.get("/api/v1/settings/ai").json() == {"provider": "none", "url": "", "model": "", "key_set": False, "skip_personal": True,
                                                         "daily_limit": 200, "used_today": 0, "instructions": ""}
    assert client.get("/api/v1/ai").json() == {"provider": "none", "to": "", "model": "", "mine": True,
                                               "allowed": True, "available": False, "skip_personal": True}
    assert probe(client).json()["detail"]["code"] == "ai_off"
    assert model.requests == []


def test_only_the_operator_chooses_the_service(client: TestClient, account: Account, model: Model) -> None:
    with person("ben") as ben:
        for method, path, body in (("get", "/api/v1/settings/ai", None),
                                   ("put", "/api/v1/settings/ai", {"provider": "openai", "url": CLOUD, "model": "x"}),
                                   ("post", "/api/v1/settings/ai/models", {"provider": "openai", "url": CLOUD}),
                                   ("post", "/api/v1/settings/ai/probe", None)):
            answer = getattr(ben, method)(path, **({"json": body} if body is not None else {}))
            assert (answer.status_code, answer.json()["detail"]["code"]) == (403, "operator_only"), path
    assert client.get("/api/v1/settings/ai").json()["provider"] == "none"
    assert model.requests == []


def test_the_key_is_never_shown_and_belongs_to_its_address(client: TestClient, account: Account, model: Model) -> None:
    key = set_up(client)
    view = client.get("/api/v1/settings/ai")
    assert view.json() == {"provider": "openai", "url": CLOUD + "/", "model": "model-a", "key_set": True,
                           "skip_personal": True, "daily_limit": 200, "used_today": 0, "instructions": ""}
    assert key not in view.text
    # Another model keeps the key.
    assert client.put("/api/v1/settings/ai", json={"model": "model-b"}).json()["key_set"] is True
    # A model list for another address typed in goes out without the stored key.
    client.post("/api/v1/settings/ai/models", json={"provider": "openai", "url": "https://other.example.com/v1"})
    assert "authorization" not in model.requests[-1].headers
    # Asked for the stored address, with the stored key.
    client.post("/api/v1/settings/ai/models", json={})
    assert model.requests[-1].headers["authorization"] == f"Bearer {key}"
    # A new address without a new key forgets the old one: it never goes to the host the new address names.
    moved = client.put("/api/v1/settings/ai", json={"url": "https://other.example.com/v1"})
    assert moved.json()["key_set"] is False
    set_up(client)
    assert client.put("/api/v1/settings/ai", json={"provider": "messages"}).json()["key_set"] is False


def test_the_key_lies_sealed_in_the_database(client: TestClient, account: Account, model: Model) -> None:
    from app.db import SessionLocal
    from app.models import Setting

    key = set_up(client)
    with SessionLocal() as db:
        stored = db.get(Setting, "ai_key_enc")
        assert stored is not None and key not in str(stored.value) and stored.value


def test_a_service_on_the_internet_is_reached_over_https_only(client: TestClient, account: Account,
                                                               model: Model) -> None:
    for provider in ("openai", "messages"):
        answer = client.put("/api/v1/settings/ai", json={"provider": provider, "url": "http://ai.example.com/v1"})
        assert (answer.status_code, answer.json()["detail"]["code"]) == (422, "ai_https_required"), provider
    for wrong in ("ftp://ai.example.com", "https://user:pw@ai.example.com/v1", "ai.example.com", "https://"):
        answer = client.put("/api/v1/settings/ai", json={"provider": "openai", "url": wrong})
        assert answer.status_code == 422, wrong
    assert client.get("/api/v1/settings/ai").json()["provider"] == "none"


def test_the_models_are_listed_and_the_probe_carries_nothing_stored(client: TestClient, account: Account,
                                                                     model: Model) -> None:
    set_up(client)
    assert client.post("/api/v1/settings/ai/models", json={}).json() == [
        {"id": "model-a", "name": "Model A"}, {"id": "model-b", "name": ""}]
    client.put("/api/v1/me/profile", json={"display_name": "Geheimer Name"})
    probed = probe(client)
    assert probed.status_code == 200 and isinstance(probed.json()["seconds"], float)
    sent = model.requests[-1].content.decode()
    assert ai.PROBE in sent and "Geheimer" not in sent
    assert model.body()["max_tokens"] == 20


@pytest.mark.parametrize("provider", ["openai", "messages", "local"])
def test_both_formats_are_spoken(client: TestClient, account: Account, model: Model, provider: str) -> None:
    url = LOCAL if provider == "local" else CLOUD
    set_up(client, provider, url)
    assert probe(client).status_code == 200
    sent = model.requests[-1]
    body = model.body()
    if provider == "messages":
        assert sent.url.path.endswith("/messages") and body["system"] and body["messages"][0]["role"] == "user"
        assert sent.headers["anthropic-version"] == ai.MESSAGES_VERSION and "x-api-key" in sent.headers
    else:
        assert sent.url.path.endswith("/chat/completions")
        assert [message["role"] for message in body["messages"]] == ["system", "user"] and body["stream"] is False


def test_a_model_that_turns_down_the_temperature_is_asked_once_more_without(client: TestClient, account: Account,
                                                                              model: Model) -> None:
    set_up(client)

    def picky(request: httpx.Request) -> httpx.Response:
        if "temperature" in json.loads(request.content):
            return httpx.Response(400, json={"error": {"message": "`temperature` is deprecated for this model"}})
        return model.write(request)

    model.answer = picky
    assert probe(client).status_code == 200
    assert len(model.requests) == 2 and "temperature" not in model.body()


# --- The person's side: what they may know, and the switches ---------------------------------------------------------


def test_each_person_may_switch_the_ai_off_for_themselves(client: TestClient, account: Account, model: Model) -> None:
    set_up(client)
    with person("ben") as ben:
        assert ben.get("/api/v1/ai").json() == {"provider": "openai", "to": "ai.example.com", "model": "model-a",
                                                "mine": True, "allowed": True, "available": True, "skip_personal": True}
        assert ben.put("/api/v1/me/preferences", json={"ai": False}).json()["ai"] is False
        assert ben.get("/api/v1/ai").json()["available"] is False and ben.get("/api/v1/ai").json()["mine"] is False
        # The others keep theirs.
        assert client.get("/api/v1/ai").json()["available"] is True
        assert ben.put("/api/v1/me/preferences", json={"ai": "no"}).status_code == 422
    assert model.requests == []


def test_a_local_model_is_not_named_to_the_members(client: TestClient, account: Account, model: Model) -> None:
    set_up(client, "local", LOCAL, model_name="llama3.1:8b")
    with person("ben") as ben:
        state = ben.get("/api/v1/ai").json()
        assert state == {"provider": "local", "to": "", "model": "llama3.1:8b", "mine": True,
                         "allowed": True, "available": True, "skip_personal": True}
        assert "ollama" not in ben.get("/api/v1/ai").text


def test_an_incomplete_service_is_not_offered(client: TestClient, account: Account, model: Model) -> None:
    client.put("/api/v1/settings/ai", json={"provider": "openai", "url": CLOUD})
    assert client.get("/api/v1/ai").json()["available"] is False
    assert probe(client).json()["detail"]["code"] == "ai_incomplete"
    assert model.requests == []


def test_the_operator_can_take_the_ai_from_single_accounts(client: TestClient, account: Account, model: Model) -> None:
    """On for every account from the start; taken away, the account is told so and no one else is touched."""
    set_up(client)
    with person("ben") as ben:
        assert ben.get("/api/v1/ai").json()["allowed"] is True
        ben_id = next(row["id"] for row in client.get("/api/v1/accounts").json() if row["name"] == "ben")
        assert client.put(f"/api/v1/accounts/{ben_id}/permissions", json={"ai_allowed": False}).status_code == 200
        state = ben.get("/api/v1/ai").json()
        assert state["allowed"] is False and state["available"] is False and state["mine"] is True
        assert client.get("/api/v1/ai").json()["available"] is True
        assert client.put(f"/api/v1/accounts/{ben_id}/permissions", json={"ai_allowed": True}).status_code == 200
        assert ben.get("/api/v1/ai").json()["available"] is True


def test_the_service_checks_the_permission_itself_not_only_the_route(client: TestClient, account: Account,
                                                                    model: Model) -> None:
    """Whatever asks the service for a person's text (a job later) goes through ``check_allowed``: it refuses."""
    from fastapi import HTTPException

    from app.db import SessionLocal
    from app.models import Account as Row

    set_up(client)
    with SessionLocal() as db:
        row = db.get(Row, account.id)
        assert row is not None
        ai.check_allowed(db, account.id)
        row.ai_allowed = False
        db.commit()
        with pytest.raises(HTTPException) as caught:
            ai.check_allowed(db, account.id)
        assert caught.value.detail["code"] == "ai_not_allowed"  # type: ignore[index]
    assert model.requests == []


# --- Errors said so a person understands them ------------------------------------------------------------------------


@pytest.mark.parametrize(("answer", "status", "code"), [
    (lambda request: httpx.Response(401, json={"error": {"message": "invalid x-api-key"}}), 502, "ai_key_refused"),
    (lambda request: httpx.Response(404), 502, "ai_address_not_found"),
    (lambda request: httpx.Response(429), 502, "ai_service_busy"),
    (lambda request: httpx.Response(500, json={"error": {"message": "overloaded"}}), 502, "ai_service_failed"),
    (lambda request: httpx.Response(200, content=b"<html>not json</html>"), 502, "ai_unreadable"),
    (lambda request: httpx.Response(200, json={"choices": []}), 502, "ai_unreadable"),
    (lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}), 502, "ai_empty"),
])
def test_what_goes_wrong_is_said_plainly(client: TestClient, account: Account, model: Model,
                                         answer: Callable[[httpx.Request], httpx.Response], status: int,
                                         code: str) -> None:
    key = set_up(client)
    model.answer = answer
    failed = probe(client)
    assert (failed.status_code, failed.json()["detail"]["code"]) == (status, code)
    assert key not in failed.text
    if code == "ai_service_failed":
        assert failed.json()["detail"]["said"] == "overloaded" and failed.json()["detail"]["answered"] == 500


def test_a_model_that_takes_too_long_or_cannot_be_reached(client: TestClient, account: Account, model: Model) -> None:
    set_up(client)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    model.answer = slow
    late = probe(client)
    assert (late.status_code, late.json()["detail"]["code"]) == (504, "ai_timeout")

    def gone(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    model.answer = gone
    assert probe(client).json()["detail"]["code"] == "ai_unreachable"


def test_the_words_of_a_local_service_are_never_shown(client: TestClient, account: Account, model: Model) -> None:
    set_up(client, "local", LOCAL)
    model.answer = lambda request: httpx.Response(500, json={"error": {"message": "router password is hunter2"}})
    failed = probe(client).json()["detail"]
    assert failed["code"] == "ai_service_failed" and failed["said"] == ""


def test_an_answer_is_read_up_to_a_limit(client: TestClient, account: Account, model: Model,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    set_up(client)
    monkeypatch.setattr(ai, "MAX_ANSWER", 1000)
    # A well-formed answer, only too large: refused for its size, not for its form.
    model.text = "Ein Satz. " * 300
    assert probe(client).json()["detail"]["code"] == "ai_unreadable"
    model.text = "OK"
    assert probe(client).status_code == 200


# --- The address is no way into the own network ----------------------------------------------------------------------


@pytest.mark.parametrize(("addresses", "code"), [
    (("169.254.169.254",), "ai_address_refused"),
    (("fe80::1",), "ai_address_refused"),
    (("0.0.0.0",), "ai_address_refused"),
    (("224.0.0.1",), "ai_address_refused"),
    (("192.168.1.20",), "ai_address_private"),
    (("10.0.0.5",), "ai_address_private"),
    (("127.0.0.1",), "ai_address_private"),
    (("::1",), "ai_address_private"),
    (("::ffff:192.168.1.1",), "ai_address_private"),
    (("100.64.0.7",), "ai_address_private"),
    ((PUBLIC_IP, "192.168.1.20"), "ai_address_private"),
])
def test_a_service_on_the_internet_never_reaches_the_own_network(client: TestClient, account: Account, model: Model,
                                                                 monkeypatch: pytest.MonkeyPatch,
                                                                 addresses: tuple[str, ...], code: str) -> None:
    set_up(client)
    resolving_to(monkeypatch, *addresses)
    for answer in (client.post("/api/v1/settings/ai/models", json={}), probe(client)):
        assert (answer.status_code, answer.json()["detail"]["code"]) == (422, code)
    assert model.requests == []


@pytest.mark.parametrize(("addresses", "code"), [
    ((PUBLIC_IP,), "ai_address_public"),
    (("192.168.1.20", PUBLIC_IP), "ai_address_public"),
    (("169.254.169.254",), "ai_address_refused"),
    (("::ffff:169.254.169.254",), "ai_address_refused"),
])
def test_a_local_model_must_stay_in_the_own_network(client: TestClient, account: Account, model: Model,
                                                    monkeypatch: pytest.MonkeyPatch, addresses: tuple[str, ...],
                                                    code: str) -> None:
    set_up(client, "local", LOCAL)
    resolving_to(monkeypatch, *addresses)
    answer = probe(client)
    assert (answer.status_code, answer.json()["detail"]["code"]) == (422, code)
    assert model.requests == []


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.20", "fd12:3456::1", "100.64.0.7"])
def test_a_local_model_may_be_on_this_machine_or_in_the_own_network(client: TestClient, account: Account,
                                                                    model: Model, monkeypatch: pytest.MonkeyPatch,
                                                                    address: str) -> None:
    set_up(client, "local", LOCAL)
    resolving_to(monkeypatch, address)
    assert probe(client).status_code == 200


def test_a_redirect_is_never_followed(client: TestClient, account: Account, model: Model) -> None:
    set_up(client)
    model.answer = lambda request: httpx.Response(302, headers={"location": "http://192.168.1.1/admin"})
    answer = probe(client)
    assert answer.status_code == 502 and answer.json()["detail"]["answered"] == 302
    assert len(model.requests) == 1


def test_the_name_is_looked_up_once_and_the_checked_address_is_used(client: TestClient, account: Account,
                                                                    model: Model,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS rebinding: a second lookup could answer with an address in the own network. There is none."""
    set_up(client)
    asked: list[str] = []

    def rebinding(host: str, port: int) -> list[str]:
        asked.append(host)
        return [PUBLIC_IP] if len(asked) == 1 else ["127.0.0.1"]

    monkeypatch.setattr(ai, "resolver", rebinding)
    assert probe(client).status_code == 200
    assert asked == ["ai.example.com"]
    assert model.requests[-1].url.host == PUBLIC_IP and model.requests[-1].headers["host"] == "ai.example.com"


def test_an_address_in_the_wrong_network_is_refused_when_saved(client: TestClient, account: Account,
                                                               model: Model, monkeypatch: pytest.MonkeyPatch) -> None:
    resolving_to(monkeypatch, PUBLIC_IP)
    refused = client.put("/api/v1/settings/ai", json={"provider": "local", "url": "http://ai.example.com/v1",
                                                      "model": "m"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "ai_address_public")
    resolving_to(monkeypatch, "169.254.169.254")
    assert client.put("/api/v1/settings/ai", json={"provider": "openai", "url": CLOUD, "model": "m"}).json()[
        "detail"]["code"] == "ai_address_refused"
    assert client.get("/api/v1/settings/ai").json()["provider"] == "none"
    assert model.requests == []


# --- One at a time, a few per minute ---------------------------------------------------------------------------------


def test_a_double_click_makes_one_request(client: TestClient, account: Account, model: Model) -> None:
    set_up(client)
    inside = threading.Event()
    release = threading.Event()

    def held(request: httpx.Request) -> httpx.Response:
        inside.set()
        release.wait(10)
        return model.write(request)

    model.answer = held
    answers: list[httpx.Response] = []
    first = threading.Thread(target=lambda: answers.append(probe(client)))
    first.start()
    assert inside.wait(10)
    with new_client(account) as again:
        second = probe(again)
    release.set()
    first.join(10)
    assert (second.status_code, second.json()["detail"]["code"]) == (409, "ai_busy")
    assert answers[0].status_code == 200
    assert len(model.requests) == 1


def test_the_server_asks_for_a_few_at_once(client: TestClient, account: Account, model: Model,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    set_up(client)
    monkeypatch.setattr(ai, "server_slots", threading.BoundedSemaphore(1))
    inside, release = threading.Event(), threading.Event()

    def held(request: httpx.Request) -> httpx.Response:
        inside.set()
        release.wait(10)
        return model.write(request)

    model.answer = held
    with person("ben") as ben:
        answers: list[httpx.Response] = []
        first = threading.Thread(target=lambda: answers.append(probe(client)))
        first.start()
        assert inside.wait(10)
        # Another operator would ask the same: the place on the server is taken, whoever asks.
        ben_id = next(row["id"] for row in client.get("/api/v1/accounts").json() if row["name"] == "ben")
        assert client.put(f"/api/v1/accounts/{ben_id}/role", json={"role": "operator", "current_password": PASSWORD}).status_code == 200
        busy = probe(ben)
        release.set()
        first.join(10)
        assert (busy.status_code, busy.json()["detail"]["code"]) == (503, "ai_server_busy")
        assert answers[0].status_code == 200 and len(model.requests) == 1
        model.answer = model.write
        assert probe(ben).status_code == 200


def test_the_operator_lists_and_probes_a_few_times_a_minute(client: TestClient, account: Account,
                                                            model: Model) -> None:
    set_up(client)
    answers = [client.post("/api/v1/settings/ai/models", json={}).status_code for _ in range(ai.OPERATOR_PER_MINUTE)]
    assert answers == [200] * ai.OPERATOR_PER_MINUTE
    assert probe(client).json()["detail"]["code"] == "ai_too_often"
    assert len(model.requests) == ai.OPERATOR_PER_MINUTE


# --- Nothing in the log ----------------------------------------------------------------------------------------------


def test_the_log_names_the_request_and_never_a_word_of_it(client: TestClient, account: Account,
                                                          model: Model) -> None:
    logs.set_mode("trace", 30)
    try:
        key = set_up(client)
        answer_word = "Wv" + secrets.token_hex(6) + "Yu"
        model.text = f"OK {answer_word}"
        assert probe(client).status_code == 200
        model.answer = lambda request: httpx.Response(401, json={"error": {"message": f"bad key {key[:12]}"}})
        probe(client)
    finally:
        logs.set_mode(logs.DEFAULT_MODE)
    for handler in logging.getLogger().handlers:
        handler.flush()
    folder = logs.log_file().parent
    text = "".join(path.read_text(encoding="utf-8", errors="replace") for path in folder.glob(logs.log_file().name + "*"))
    assert "provider=openai model=model-a status=ok" in text
    for secret in (answer_word, key, key[:12]):
        assert secret not in text, secret


# --- Deadline, addresses in turn, the key of a local model -----------------------------------------------------------


class Trickle(httpx.SyncByteStream):
    """A service that sends a byte now and then, for ever."""

    def __iter__(self) -> Iterator[bytes]:
        for _ in range(10_000):
            yield b" "


@pytest.fixture
def ticking(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The clock of deadlines and brakes, moved by the test: every look at it is five seconds later."""
    now = [1000.0]

    def tick() -> float:
        now[0] += 5
        return now[0]

    monkeypatch.setattr(ai, "ticks", tick)
    return now


@pytest.mark.parametrize("what", ["models", "probe"])
def test_a_service_that_trickles_is_cut_off_at_the_deadline(client: TestClient, account: Account, model: Model,
                                                            ticking: list[float], monkeypatch: pytest.MonkeyPatch,
                                                            what: str) -> None:
    set_up(client)
    monkeypatch.setattr(ai, "TEXT_SECONDS", 30.0)
    monkeypatch.setattr(ai, "LIST_SECONDS", 30.0)
    model.answer = lambda request: httpx.Response(200, stream=Trickle())
    started = time.monotonic()
    late = client.post("/api/v1/settings/ai/models", json={}) if what == "models" else probe(client)
    assert (late.status_code, late.json()["detail"]["code"]) == (504, "ai_timeout")
    assert time.monotonic() - started < 10
    # The place on the server is free again.
    model.answer = model.write
    assert probe(client).status_code == 200


def test_the_addresses_checked_are_tried_in_turn(client: TestClient, account: Account, model: Model,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """localhost names ::1 first, the service listens on 127.0.0.1 only."""
    resolving_to(monkeypatch, "::1", "127.0.0.1")
    set_up(client, "local", "http://localhost:11434/v1")
    tried: list[str] = []

    def only_ipv4(request: httpx.Request) -> httpx.Response:
        tried.append(request.url.host)
        if request.url.host == "::1":
            raise httpx.ConnectError("refused", request=request)
        return model.write(request)

    model.answer = only_ipv4
    assert probe(client).status_code == 200
    assert tried == ["::1", "127.0.0.1"]
    assert model.requests[-1].headers["host"] == "localhost:11434"
    # Neither answers: unreachable.
    model.answer = lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused", request=request))
    assert probe(client).json()["detail"]["code"] == "ai_unreachable"


def test_an_ipv6_address_stands_in_brackets_in_the_host_header(client: TestClient, account: Account, model: Model,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    resolving_to(monkeypatch, "fd12:3456::5")
    set_up(client, "local", "http://[fd12:3456::5]:11434/v1")
    assert probe(client).status_code == 200
    assert model.requests[-1].headers["host"] == "[fd12:3456::5]:11434"


def test_a_local_model_may_have_a_key(client: TestClient, account: Account, model: Model) -> None:
    key = set_up(client, "local", LOCAL, key=made_key())
    assert client.get("/api/v1/settings/ai").json()["key_set"] is True
    assert probe(client).status_code == 200
    assert model.requests[-1].headers["authorization"] == f"Bearer {key}"
    # Another address without a new key forgets it, as for every kind of service.
    assert client.put("/api/v1/settings/ai", json={"url": "http://ollama.example.com:8080/v1"}).json()["key_set"] is False
