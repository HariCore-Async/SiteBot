"""AI providers and models that admins configure, and which model answers a given question.

A model is referred to by a short string, a "ref":
  "m:<id>"      a model the admin added under a provider (stored in ai_models)
  "env:answer"  the OpenRouter model from OPENROUTER_MODEL, using OPENROUTER_API_KEY (the original setup)
  "env:fast"    the OpenRouter model from OPENROUTER_FAST_MODEL
Defaults live in app_settings; a bot can override them (sites.answer_model / sites.fast_model).
With nothing configured, answers use the env models, exactly as before providers existed.
"""

import base64
import hashlib
import json
import logging
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AIModel, AIProvider, AppSetting, Site

log = logging.getLogger(__name__)

KINDS = {
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1"},
    "anthropic": {"label": "Anthropic", "base_url": "https://api.anthropic.com"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "azure": {"label": "Azure OpenAI", "base_url": ""},  # https://<resource>.openai.azure.com; models are deployment names
    "huggingface": {"label": "Hugging Face", "base_url": "https://router.huggingface.co/v1"},
    "openai_compatible": {"label": "OpenAI-compatible (Ollama, vLLM, LM Studio…)", "base_url": ""},
}
DEFAULT_AZURE_API_VERSION = "2024-10-21"


@dataclass
class Target:
    """One model to try: everything needed to call it, and its prices for when the provider doesn't report cost."""

    ref: str
    kind: str
    base_url: str
    api_key: str
    model: str
    label: str
    api_version: str = ""
    input_per_m: float = 0.0
    output_per_m: float = 0.0


# ---------- Keys at rest ----------

_warned = False


def _fernet() -> Fernet:
    global _warned
    secret = settings.provider_keys_secret
    if not secret:
        if not _warned:
            log.warning("PROVIDER_KEYS_SECRET isn't set; provider API keys are encrypted with a key derived from SECRET_KEY. "
                        "Changing SECRET_KEY will then make saved provider keys unreadable.")
            _warned = True
        secret = "sitebot-provider-keys:" + settings.secret_key
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt_key(key: str) -> str:
    return _fernet().encrypt(key.encode()).decode() if key else ""


def decrypt_key(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.error("A saved provider API key can't be decrypted (was PROVIDER_KEYS_SECRET or SECRET_KEY changed?). Re-enter it.")
        return ""


# ---------- Settings ----------

def _get(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    return json.loads(row.value) if row else default


def _put(db: Session, key: str, value) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = json.dumps(value)
    else:
        db.add(AppSetting(key=key, value=json.dumps(value)))


def defaults(db: Session) -> dict:
    return {
        "answer": _get(db, "ai_answer_model", "env:answer"),
        "fast": _get(db, "ai_fast_model", "env:fast"),
        "fallbacks": _get(db, "ai_fallbacks", []),
    }


def set_defaults(db: Session, answer: str, fast: str, fallbacks: list[str]) -> None:
    _put(db, "ai_answer_model", answer)
    _put(db, "ai_fast_model", fast)
    _put(db, "ai_fallbacks", [f for f in dict.fromkeys(fallbacks) if f])
    db.commit()


def env_available() -> bool:
    return bool(settings.openrouter_api_key)


def env_models() -> list[dict]:
    if not env_available():
        return []
    return [
        {"ref": "env:answer", "model": settings.openrouter_model, "label": f"{settings.openrouter_model} (OPENROUTER_MODEL)"},
        {"ref": "env:fast", "model": settings.openrouter_fast_model, "label": f"{settings.openrouter_fast_model} (OPENROUTER_FAST_MODEL)"},
    ]


# ---------- Which model answers ----------

def target_for(db: Session, ref: str) -> Target | None:
    """The callable model a ref points to, or None if it's missing, disabled or has no key."""
    if ref in ("env:answer", "env:fast"):
        if not env_available():
            return None
        model = settings.openrouter_model if ref == "env:answer" else settings.openrouter_fast_model
        return Target(ref, "openrouter", KINDS["openrouter"]["base_url"], settings.openrouter_api_key, model, f"OpenRouter · {model}")
    if not ref.startswith("m:") or not ref[2:].isdigit():
        return None
    m = db.get(AIModel, int(ref[2:]))
    p = db.get(AIProvider, m.provider_id) if m else None
    if not m or not p or not m.enabled or not p.enabled:
        return None
    key = decrypt_key(p.api_key_enc)
    if not key and p.kind != "openai_compatible":
        return None
    return Target(
        ref, p.kind, (p.base_url or KINDS.get(p.kind, {}).get("base_url", "")).rstrip("/"), key, m.model,
        f"{p.name} · {m.label or m.model}", p.api_version or "", m.input_per_m or 0.0, m.output_per_m or 0.0,
    )


def targets(db: Session, purpose: str, site_id: int | None = None) -> list[Target]:
    """Models to try in order: the bot's own choice (or the default), then the fallbacks. Duplicates and broken
    entries are skipped. If nothing is usable, the original OpenRouter env setup is the last resort."""
    d = defaults(db)
    first = d["answer"] if purpose == "answer" else d["fast"]
    if site_id:
        site = db.get(Site, site_id)
        override = site and (site.answer_model if purpose == "answer" else site.fast_model)
        first = override or first
    chain, seen = [], set()
    for ref in [first, *d["fallbacks"]]:
        if ref in seen:
            continue
        seen.add(ref)
        t = target_for(db, ref)
        if t:
            chain.append(t)
    if not chain:
        t = target_for(db, "env:answer" if purpose == "answer" else "env:fast")
        if t:
            chain.append(t)
    return chain


def clear_references(db: Session, ref: str) -> None:
    """When a model goes away, stop pointing at it (defaults fall back to the env models)."""
    d = defaults(db)
    set_defaults(
        db,
        "env:answer" if d["answer"] == ref else d["answer"],
        "env:fast" if d["fast"] == ref else d["fast"],
        [f for f in d["fallbacks"] if f != ref],
    )
    for site in db.scalars(select(Site).where((Site.answer_model == ref) | (Site.fast_model == ref))):
        site.answer_model = None if site.answer_model == ref else site.answer_model
        site.fast_model = None if site.fast_model == ref else site.fast_model
    db.commit()


def provider_out(p: AIProvider, models: list[AIModel]) -> dict:
    key = decrypt_key(p.api_key_enc)
    return {
        "id": p.id, "name": p.name, "kind": p.kind, "kind_label": KINDS.get(p.kind, {}).get("label", p.kind),
        "base_url": p.base_url, "api_version": p.api_version, "enabled": p.enabled,
        # Keys are write-only: the UI only ever sees whether one is set and its last 4 characters.
        "has_key": bool(key), "key_hint": key[-4:] if key else "",
        "models": [
            {"ref": f"m:{m.id}", "id": m.id, "model": m.model, "label": m.label, "input_per_m": m.input_per_m,
             "output_per_m": m.output_per_m, "enabled": m.enabled}
            for m in models
        ],
    }
