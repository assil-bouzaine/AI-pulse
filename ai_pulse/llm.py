"""Three LLM providers behind one function, with automatic fallback.

    Gemini (best quality, generous context)  ->  Groq (very fast)  ->  Ollama (local, always there)

Key decisions:
  * Gemini and Groq both offer an OpenAI-compatible endpoint, so ONE function
    talks to both. Only the base URL, key and model differ. No SDKs needed.
  * Ollama uses its native /api/chat because it lets us switch off Qwen's
    "thinking" mode, which makes a small local model several times faster.
  * We ask for JSON and validate it. Malformed output counts as a failure and
    triggers the next provider, just like a network error would.
"""

import json
import logging
import os
import re
from typing import Callable

from .net import HTTPError, request

log = logging.getLogger(__name__)

OPENAI_COMPATIBLE = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
}
FALLBACK_ORDER = ["gemini", "groq", "ollama"]


class LLMError(Exception):
    pass


# ---------- which providers can we use? ----------

def ollama_running(cfg: dict) -> bool:
    try:
        request("GET", f"{cfg['llm']['ollama_url']}/api/tags", timeout=3, retries=0)
        return True
    except Exception:
        return False


def providers_to_try(cfg: dict, choice: str) -> list[str]:
    if choice == "none":
        return []
    candidates = FALLBACK_ORDER if choice == "auto" else [choice]
    usable = []
    for name in candidates:
        if name in OPENAI_COMPATIBLE and not os.getenv(OPENAI_COMPATIBLE[name][1]):
            log.info("%s skipped: no %s in .env", name, OPENAI_COMPATIBLE[name][1])
        elif name == "ollama" and not ollama_running(cfg):
            log.info("ollama skipped: not running at %s", cfg["llm"]["ollama_url"])
        else:
            usable.append(name)
    return usable


def pick_models(base: str, key: str, preferred: list[str]) -> list[str]:
    """Ask the provider which models exist; keep the preferred ones that do, in order."""
    try:
        listing = request("GET", f"{base}/models", timeout=10, retries=1,
                          headers={"Authorization": f"Bearer {key}"}).json()
        available = {m["id"].removeprefix("models/") for m in listing.get("data", [])}
        models = [m for m in preferred if m in available]
        if models:
            return models
        log.warning("none of %s available; provider offers e.g. %s",
                    preferred, sorted(available)[:8])
    except Exception as exc:
        log.debug("model listing failed (%s), trying %s", exc, preferred[0])
    return preferred[:1]


# ---------- the actual calls ----------

def _chat(base: str, key: str, model: str, system: str, user: str) -> str:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.5,
        "response_format": {"type": "json_object"},
        "reasoning_effort": "low",   # this is writing, not math: think less, answer faster
    }
    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = request("POST", f"{base}/chat/completions", json=body,
                           headers=headers, timeout=90, retries=1)
    except HTTPError as exc:
        # Not every model accepts every optional field. Retry once with the bare minimum.
        if exc.status != 400:
            raise
        log.debug("%s rejected optional fields (%s), retrying without them", model, exc)
        body.pop("response_format")
        body.pop("reasoning_effort")
        response = request("POST", f"{base}/chat/completions", json=body,
                           headers=headers, timeout=90, retries=1)
    return response.json()["choices"][0]["message"]["content"]


def call_openai_compatible(provider: str, cfg: dict, system: str, user: str) -> tuple[str, str]:
    """Try up to 2 models of this provider before giving up on it.

    Brand-new models are often overloaded (HTTP 503) while the previous one
    is fine, so a second model is usually a faster rescue than a new provider.
    """
    base, key_name = OPENAI_COMPATIBLE[provider]
    key = os.environ[key_name]
    models = pick_models(base, key, cfg["llm"][f"{provider}_models"])[:2]
    for model in models:
        try:
            return _chat(base, key, model, system, user), model
        except Exception as exc:
            if model == models[-1]:
                raise
            log.warning("%s %s failed (%s), trying %s", provider, model, exc,
                        models[models.index(model) + 1])
    raise AssertionError("unreachable")


def call_ollama(cfg: dict, system: str, user: str) -> tuple[str, str]:
    model = cfg["llm"]["ollama_model"]
    response = request("POST", f"{cfg['llm']['ollama_url']}/api/chat", timeout=300, retries=0,
                       json={
                           "model": model,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}],
                           "stream": False,
                           "think": False,        # skip the reasoning trace: much faster
                           "format": "json",      # constrain output to valid JSON
                           # num_predict caps output so a rambling model can't run for minutes.
                           "options": {"temperature": 0.5, "num_ctx": 8192, "num_predict": 1500},
                       })
    return response.json()["message"]["content"], model


def parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in ```fences``` or add chatter. Dig it out."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("no JSON object in response")
    return json.loads(text[start:end + 1])


# ---------- public entry point ----------

def generate(cfg: dict, choice: str, system: str,
             build_prompt: Callable[[int], str],
             validate: Callable[[dict], None]) -> tuple[dict, str]:
    """Try providers in order. Returns (parsed JSON, "provider · model").

    `build_prompt(n)` builds the user prompt for n stories, so each provider
    gets a prompt sized to its limits.
    """
    errors = []
    for provider in providers_to_try(cfg, choice):
        try:
            prompt = build_prompt(cfg["llm"]["max_items"][provider])
            log.info("writing digest with %s…", provider)
            if provider == "ollama":
                text, model = call_ollama(cfg, system, prompt)
            else:
                text, model = call_openai_compatible(provider, cfg, system, prompt)
            data = parse_json(text)
            validate(data)
            return data, f"{provider} · {model}"
        except Exception as exc:
            log.warning("%s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")
    raise LLMError("; ".join(errors) or "no LLM provider available")
