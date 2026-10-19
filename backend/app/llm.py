"""Minimal OpenRouter client with streaming and per-call cost reporting."""

import json
from collections.abc import Iterator

import httpx

from .config import settings

URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    pass


def _headers() -> dict:
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not configured on the server.")
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "https://github.com/HariCore-Async/SiteBot",
        "X-Title": "SiteBot",
    }


def _body(model: str, messages: list[dict], max_tokens: int, stream: bool) -> dict:
    return {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": stream,
        "usage": {"include": True},
    }


def complete(model: str, messages: list[dict], max_tokens: int = 300) -> tuple[str, dict]:
    try:
        r = httpx.post(URL, headers=_headers(), json=_body(model, messages, max_tokens, False), timeout=60)
    except httpx.HTTPError as e:
        raise LLMError(f"Could not reach OpenRouter: {e}") from e
    if r.status_code != 200:
        raise LLMError(f"OpenRouter error {r.status_code}: {r.text[:300]}")
    data = r.json()
    if "error" in data:
        raise LLMError(f"OpenRouter error: {data['error']}")
    return data["choices"][0]["message"].get("content") or "", data.get("usage") or {}


def stream(model: str, messages: list[dict], max_tokens: int = 900) -> Iterator[tuple[str, object]]:
    """Yields ("token", str) pieces, then one ("usage", dict)."""
    usage: dict = {}
    try:
        with httpx.stream("POST", URL, headers=_headers(), json=_body(model, messages, max_tokens, True), timeout=90) as r:
            if r.status_code != 200:
                raise LLMError(f"OpenRouter error {r.status_code}: {r.read().decode()[:300]}")
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue  # SSE comments such as ": OPENROUTER PROCESSING"
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                data = json.loads(payload)
                if "error" in data:
                    raise LLMError(f"OpenRouter error: {data['error']}")
                if data.get("usage"):
                    usage = data["usage"]
                for choice in data.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield "token", piece
    except httpx.HTTPError as e:
        raise LLMError(f"Could not reach OpenRouter: {e}") from e
    yield "usage", usage
