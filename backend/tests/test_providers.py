"""AI providers: request formats, streaming, cost, fallback, encrypted keys and the Admin console API.

These tests talk to fake HTTP servers (httpx.MockTransport), never to real providers.
"""

import json

import httpx
import pytest

from app import llm, providers
from app.config import settings
from app.db import SessionLocal
from app.models import AIModel, AIProvider
from app.providers import Target, decrypt_key, encrypt_key

# conftest swaps llm.complete/stream for fakes in every test; these tests need the real ones.
REAL_COMPLETE, REAL_STREAM = llm.complete, llm.stream


def sse(*events) -> bytes:
    return "".join(f"data: {json.dumps(e) if not isinstance(e, str) else e}\n\n" for e in events).encode()


class FakeServer:
    """Answers like a provider and records what it was asked."""

    def __init__(self, handler):
        self.requests = []
        self.handler = handler

    def __call__(self, request: httpx.Request):
        self.requests.append(request)
        return self.handler(request)


@pytest.fixture
def serve(monkeypatch):
    def install(handler):
        server = FakeServer(handler)
        monkeypatch.setattr(llm, "http", httpx.Client(transport=httpx.MockTransport(server)))
        return server

    return install


def target(kind="openai", **kw):
    base = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com", "azure": "https://res.openai.azure.com"}.get(kind, "https://llm.example/v1")
    return Target(ref="m:1", kind=kind, base_url=base, api_key="sk-test", model=kw.pop("model", "gpt-4o-mini"), label=f"Test {kind} · model", **kw)


MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]


def test_openai_complete_prices_tokens_when_no_cost_reported(serve):
    server = serve(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "Hello!"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}))
    text, usage = llm.complete_with(target(input_per_m=2.0, output_per_m=8.0), MSGS)
    req = server.requests[0]
    body = json.loads(req.content)
    assert text == "Hello!" and req.url.path == "/v1/chat/completions" and req.headers["authorization"] == "Bearer sk-test"
    assert body["model"] == "gpt-4o-mini" and body["temperature"] == 0 and body["max_tokens"] == 300
    assert usage["cost"] == pytest.approx(1000 * 2 / 1e6 + 500 * 8 / 1e6)


def test_openai_reasoning_models_use_max_completion_tokens(serve):
    server = serve(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
    llm.complete_with(target(model="o4-mini"), MSGS, max_tokens=50)
    body = json.loads(server.requests[0].content)
    assert body["max_completion_tokens"] == 50 and "max_tokens" not in body and "temperature" not in body


def test_openai_stream_with_usage(serve):
    serve(lambda r: httpx.Response(200, content=sse(
        {"choices": [{"delta": {"content": "Hel"}}]}, {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}, "[DONE]")))
    out = list(llm.stream_with(target(input_per_m=1, output_per_m=1), MSGS))
    assert [p for k, p in out if k == "token"] == ["Hel", "lo"]
    assert out[-1][0] == "usage" and out[-1][1]["completion_tokens"] == 2


def test_openrouter_cost_is_taken_from_the_provider(serve):
    server = serve(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1, "cost": 0.0123}}))
    _, usage = llm.complete_with(Target("env:answer", "openrouter", "https://openrouter.ai/api/v1", "k", "anthropic/claude", "OpenRouter · claude"), MSGS)
    body = json.loads(server.requests[0].content)
    assert usage["cost"] == 0.0123 and body["usage"] == {"include": True} and server.requests[0].headers["x-title"] == "SiteBot"


def test_azure_url_and_header(serve):
    server = serve(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
    llm.complete_with(target("azure", model="my-deployment", api_version="2024-10-21"), MSGS)
    req = server.requests[0]
    assert str(req.url) == "https://res.openai.azure.com/openai/deployments/my-deployment/chat/completions?api-version=2024-10-21"
    assert req.headers["api-key"] == "sk-test" and "authorization" not in req.headers and "model" not in json.loads(req.content)


def test_anthropic_complete_and_stream(serve):
    server = serve(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "Hi there"}], "usage": {"input_tokens": 7, "output_tokens": 3}}))
    text, usage = llm.complete_with(target("anthropic", model="claude-haiku"), MSGS)
    req = server.requests[0]
    body = json.loads(req.content)
    assert text == "Hi there" and req.url.path == "/v1/messages" and req.headers["x-api-key"] == "sk-test"
    assert body["system"] == "Be brief." and [m["role"] for m in body["messages"]] == ["user"]
    assert usage["prompt_tokens"] == 7 and usage["completion_tokens"] == 3

    serve(lambda r: httpx.Response(200, content=(
        b"event: message_start\ndata: " + json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 9}}}).encode() + b"\n\n"
        + b"event: content_block_delta\ndata: " + json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}}).encode() + b"\n\n"
        + b"event: content_block_delta\ndata: " + json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}}).encode() + b"\n\n"
        + b"event: message_delta\ndata: " + json.dumps({"type": "message_delta", "usage": {"output_tokens": 2}}).encode() + b"\n\n")))
    out = list(llm.stream_with(target("anthropic", model="claude-haiku"), MSGS))
    assert "".join(p for k, p in out if k == "token") == "Hello" and out[-1][1]["prompt_tokens"] == 9 and out[-1][1]["completion_tokens"] == 2


def test_error_status_raises(serve):
    serve(lambda r: httpx.Response(401, text="bad key"))
    with pytest.raises(llm.LLMError, match="401"):
        llm.complete_with(target(), MSGS)


def test_fallback_to_next_model(monkeypatch, serve):
    first, second = target(), target(model="backup")
    second.ref = "m:2"
    monkeypatch.setattr(llm, "_targets", lambda purpose, site_id: [first, second])
    serve(lambda r: httpx.Response(500, text="down") if json.loads(r.content)["model"] == "gpt-4o-mini"
          else httpx.Response(200, json={"choices": [{"message": {"content": "from backup"}}]}))
    text, usage = REAL_COMPLETE("answer", MSGS)
    assert text == "from backup" and usage["model"] == "backup"


def test_stream_falls_back_only_before_the_first_token(monkeypatch, serve):
    first, second = target(), target(model="backup")
    monkeypatch.setattr(llm, "_targets", lambda purpose, site_id: [first, second])
    serve(lambda r: httpx.Response(503) if json.loads(r.content)["model"] == "gpt-4o-mini"
          else httpx.Response(200, content=sse({"choices": [{"delta": {"content": "B"}}]}, "[DONE]")))
    assert [p for k, p in REAL_STREAM("answer", MSGS) if k == "token"] == ["B"]

    def broken_midway(r):
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "A"}}]}, {"error": "boom"}))

    serve(broken_midway)
    with pytest.raises(llm.LLMError):
        list(REAL_STREAM("answer", MSGS))


def test_keys_are_encrypted_and_never_returned():
    token = encrypt_key("sk-secret-1234")
    assert "sk-secret" not in token and decrypt_key(token) == "sk-secret-1234"
    assert decrypt_key("garbage") == ""


def test_env_openrouter_is_the_bootstrap_default():
    db = SessionLocal()
    chain = providers.targets(db, "answer")
    db.close()
    assert chain and chain[0].ref == "env:answer" and chain[0].model == settings.openrouter_model


def test_admin_api_providers_models_defaults_and_bot_override(admin, member, site, serve):
    assert member.get("/api/admin/ai").status_code == 403
    r = admin.post("/api/admin/ai/providers", json={"name": "My OpenAI", "kind": "openai", "api_key": "sk-live-abcd1234"})
    p = r.json()["providers"][-1]
    assert p["has_key"] and p["key_hint"] == "1234" and "sk-live" not in r.text
    assert admin.post("/api/admin/ai/providers", json={"name": "Local", "kind": "openai_compatible"}).status_code == 400
    assert admin.post("/api/admin/ai/providers", json={"name": "Bad", "kind": "openai_compatible", "base_url": "ftp://x"}).status_code == 400
    r = admin.post(f"/api/admin/ai/providers/{p['id']}/models", json={"model": "gpt-4o-mini", "label": "4o mini", "input_per_m": 0.15, "output_per_m": 0.6})
    ref = r.json()["providers"][-1]["models"][0]["ref"]

    serve(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "usage": {"prompt_tokens": 9, "completion_tokens": 1}}))
    t = admin.post("/api/admin/ai/test", json={"ref": ref}).json()
    assert t["ok"] and t["reply"] == "OK"

    assert admin.put("/api/admin/ai/defaults", json={"answer": "m:99999", "fast": "env:fast", "fallbacks": []}).status_code == 400
    d = admin.put("/api/admin/ai/defaults", json={"answer": ref, "fast": "env:fast", "fallbacks": ["env:answer"]}).json()["defaults"]
    assert d == {"answer": ref, "fast": "env:fast", "fallbacks": ["env:answer"]}
    db = SessionLocal()
    assert [x.ref for x in providers.targets(db, "answer")] == [ref, "env:answer"]
    db.close()

    assert admin.patch(f"/api/admin/sites/{site.id}/models", json={"answer_model": "env:answer"}).json()["answer_model"] == "env:answer"
    db = SessionLocal()
    assert providers.targets(db, "answer", site.id)[0].ref == "env:answer"
    db.close()

    # Turning the provider off skips its model; deleting it clears every reference to it.
    admin.patch(f"/api/admin/ai/providers/{p['id']}", json={"enabled": False})
    db = SessionLocal()
    assert [x.ref for x in providers.targets(db, "answer")] == ["env:answer"]
    db.close()
    admin.delete(f"/api/admin/ai/providers/{p['id']}")
    assert admin.get("/api/admin/ai").json()["defaults"]["answer"] == "env:answer"
    db = SessionLocal()
    assert db.query(AIModel).count() == 0 or all(m.provider_id != p["id"] for m in db.query(AIModel)) and not db.get(AIProvider, p["id"])
    db.close()


def test_usage_records_provider_and_model(client, admin, site):
    chat = admin.post("/api/chats", json={"site_id": site.id}).json()
    admin.post(f"/api/chats/{chat['id']}/messages", json={"content": "What do you sell?"})
    from app.models import UsageEvent

    db = SessionLocal()
    ev = db.query(UsageEvent).filter(UsageEvent.kind == "answer").order_by(UsageEvent.id.desc()).first()
    db.close()
    assert ev.model == "fake-answer" and ev.provider == "Fake"
