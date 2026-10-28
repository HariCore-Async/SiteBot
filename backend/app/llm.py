"""Calls the AI model chosen for a purpose ("answer" or "fast"), with streaming, cost reporting and fallback.

Which models to try comes from providers.targets(); if one fails (network, error status, error payload), the next is
tried. Streaming only falls back before the first token, so a visitor never sees two half-answers.
Most providers speak the OpenAI chat-completions format (OpenRouter, OpenAI, Gemini's compatible endpoint, Azure,
Hugging Face's router, Ollama/vLLM); Anthropic has its own Messages API.
"""

import json
import logging
from collections.abc import Iterator

import httpx

log = logging.getLogger(__name__)

# One shared client (connection reuse). Tests swap it for one with a mock transport.
http = httpx.Client(timeout=httpx.Timeout(90, connect=15))


class LLMError(Exception):
    pass


# ---------- Building requests ----------

def _openai_request(t, messages: list[dict], max_tokens: int, stream: bool) -> tuple[str, dict, dict]:
    headers = {"Content-Type": "application/json"}
    if t.kind == "azure":
        url = f"{t.base_url}/openai/deployments/{t.model}/chat/completions?api-version={t.api_version or '2024-10-21'}"
        headers["api-key"] = t.api_key
    else:
        url = f"{t.base_url}/chat/completions"
        if t.api_key:
            headers["Authorization"] = f"Bearer {t.api_key}"
    body = {"messages": messages, "stream": stream}
    if t.kind != "azure":
        body["model"] = t.model
    # Reasoning models (OpenAI o-series, GPT-5) take max_completion_tokens and only their default temperature.
    reasoning = t.kind in ("openai", "azure") and t.model.split("/")[-1].startswith(("o1", "o3", "o4", "gpt-5"))
    body["max_completion_tokens" if reasoning else "max_tokens"] = max_tokens
    if not reasoning:
        body["temperature"] = 0
    if t.kind == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/HariCore-Async/SiteBot"
        headers["X-Title"] = "SiteBot"
        body["usage"] = {"include": True}
        # Extended thinking can use up a small max_tokens budget and return empty text.
        body["reasoning"] = {"enabled": False}
    elif stream:
        body["stream_options"] = {"include_usage": True}
    return url, headers, body


def _anthropic_request(t, messages: list[dict], max_tokens: int, stream: bool) -> tuple[str, dict, dict]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
    headers = {"x-api-key": t.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    body = {"model": t.model, "max_tokens": max_tokens, "temperature": 0, "messages": chat, "stream": stream}
    if system:
        body["system"] = system
    return f"{t.base_url}/v1/messages", headers, body


def _request(t, messages, max_tokens, stream):
    return (_anthropic_request if t.kind == "anthropic" else _openai_request)(t, messages, max_tokens, stream)


# ---------- Usage and cost ----------

def _usage(t, raw: dict, prompt_chars: int, text: str) -> dict:
    """Tokens and cost in one shape. OpenRouter reports cost itself; otherwise it's priced from the model's rates
    (tokens are estimated at ~4 characters each when a provider doesn't report them)."""
    prompt = raw.get("prompt_tokens", raw.get("input_tokens"))
    completion = raw.get("completion_tokens", raw.get("output_tokens"))
    prompt = int(prompt) if prompt is not None else prompt_chars // 4
    completion = int(completion) if completion is not None else len(text) // 4
    cost = raw.get("cost")
    if cost is None:
        cost = prompt * t.input_per_m / 1e6 + completion * t.output_per_m / 1e6
    return {"prompt_tokens": prompt, "completion_tokens": completion, "cost": float(cost), "model": t.model, "provider": t.label.split(" · ")[0]}


def _chars(messages) -> int:
    return sum(len(m["content"]) for m in messages)


def _fail(t, r: httpx.Response, body: str) -> LLMError:
    return LLMError(f"{t.label}: error {r.status_code}: {body[:300]}")


# ---------- One model ----------

def complete_with(t, messages: list[dict], max_tokens: int = 300) -> tuple[str, dict]:
    url, headers, body = _request(t, messages, max_tokens, False)
    try:
        r = http.post(url, headers=headers, json=body, timeout=60)
    except httpx.HTTPError as e:
        raise LLMError(f"{t.label}: could not connect: {e}") from e
    if r.status_code != 200:
        raise _fail(t, r, r.text)
    data = r.json()
    if "error" in data:
        raise LLMError(f"{t.label}: {data['error']}")
    if t.kind == "anthropic":
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
    else:
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return text, _usage(t, data.get("usage") or {}, _chars(messages), text)


def stream_with(t, messages: list[dict], max_tokens: int = 900) -> Iterator[tuple[str, object]]:
    """Yields ("token", str) pieces, then one ("usage", dict)."""
    url, headers, body = _request(t, messages, max_tokens, True)
    raw, text = {}, ""
    try:
        with http.stream("POST", url, headers=headers, json=body, timeout=90) as r:
            if r.status_code != 200:
                raise _fail(t, r, r.read().decode(errors="ignore"))
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue  # SSE comments (": OPENROUTER PROCESSING") and Anthropic's "event:" lines
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                data = json.loads(payload)
                if "error" in data and data.get("type") != "message_delta":
                    raise LLMError(f"{t.label}: {data['error']}")
                if t.kind == "anthropic":
                    kind = data.get("type")
                    if kind == "message_start":
                        raw.update((data.get("message") or {}).get("usage") or {})
                    elif kind == "message_delta":
                        raw.update(data.get("usage") or {})
                    elif kind == "content_block_delta" and (data.get("delta") or {}).get("type") == "text_delta":
                        piece = data["delta"].get("text", "")
                        text += piece
                        yield "token", piece
                    continue
                if data.get("usage"):
                    raw = data["usage"]
                for choice in data.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        text += piece
                        yield "token", piece
    except httpx.HTTPError as e:
        raise LLMError(f"{t.label}: could not connect: {e}") from e
    yield "usage", _usage(t, raw, _chars(messages), text)


# ---------- With fallback ----------

def _targets(purpose: str, site_id: int | None):
    from .db import SessionLocal
    from .providers import targets

    db = SessionLocal()
    try:
        chain = targets(db, purpose, site_id)
    finally:
        db.close()
    if not chain:
        raise LLMError("No AI model is configured. Add a provider in Admin console > AI providers, or set OPENROUTER_API_KEY.")
    return chain


def complete(purpose: str, messages: list[dict], max_tokens: int = 300, site_id: int | None = None) -> tuple[str, dict]:
    errors = []
    for t in _targets(purpose, site_id):
        try:
            return complete_with(t, messages, max_tokens)
        except LLMError as e:
            log.warning("AI call failed, trying the next model: %s", e)
            errors.append(str(e))
    raise LLMError("; ".join(errors))


def stream(purpose: str, messages: list[dict], max_tokens: int = 900, site_id: int | None = None) -> Iterator[tuple[str, object]]:
    errors = []
    for t in _targets(purpose, site_id):
        started = False
        try:
            for kind, payload in stream_with(t, messages, max_tokens):
                started = started or kind == "token"
                yield kind, payload
            return
        except LLMError as e:
            if started:
                raise
            log.warning("AI stream failed before any text, trying the next model: %s", e)
            errors.append(str(e))
    raise LLMError("; ".join(errors))


def configured() -> bool:
    """Whether any AI model is usable (for the health of the app, not which one)."""
    try:
        return bool(_targets("answer", None))
    except LLMError:
        return False

