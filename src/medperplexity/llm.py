"""LLM access for the agent: OpenRouter first, then direct Claude / OpenAI / Gemini as fallbacks.

Design goals
------------
* **One call, many providers.** ``FallbackLLM.complete_json`` tries providers in order and moves on when one
  fails (network error, rate limit, no credit, safety block, or output that is not valid JSON for the schema).
* **No extra dependencies.** Plain HTTPS through ``urllib`` (the same request shapes the providers document),
  so there is no SDK to install or version-pin, and everything is easy to mock in tests.
* **Structured output you can trust.** Replies are parsed leniently (code fences, text around the JSON) and
  then validated by a caller-supplied validator. One repair attempt is made on the same provider before
  falling back.
* **Auditable.** Every result lists the providers tried and why each failed, with no prompt text and no patient data.

Configuration (environment variables, see ``.env.example``)::

    LLM_PROVIDERS=openrouter,anthropic,openai,gemini      # order of preference; unconfigured ones are skipped
    OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_FALLBACK_MODELS=slug1,slug2   # OpenRouter-side fallback
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL
    OPENAI_API_KEY,    OPENAI_MODEL
    GOOGLE_API_KEY (or GEMINI_API_KEY), GEMINI_MODEL
    LLM_TIMEOUT_S=45

Model names change often, so apart from Anthropic's, no model name is hard-coded: set the exact IDs you want
(OpenRouter IDs look like ``provider/model``; copy them from https://openrouter.ai/models). ``.env.example`` lists
the flagship models verified when it was written.

Privacy (OpenRouter): requests carry ``provider.data_collection = "deny"`` by default, so they are routed only to
providers that do not store prompts; set ``OPENROUTER_ZDR=true`` to additionally require zero-data-retention endpoints.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config  # noqa: F401  (loads .env)

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "45"))
DEFAULT_PROVIDER_ORDER = "openrouter,anthropic,openai,gemini"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


# --------------------------------------------------------------------------- #
# Errors and results
# --------------------------------------------------------------------------- #
class LLMError(Exception):
    """A single provider call failed."""

    def __init__(self, message: str, *, provider: str = "", status: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.provider, self.status, self.retryable = provider, status, retryable


class LLMUnavailable(LLMError):
    """Every configured provider failed (or none is configured)."""

    def __init__(self, message: str, attempts: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.attempts = attempts or []


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0

    def audit(self) -> Dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "elapsed_ms": self.elapsed_ms,
                "attempts": self.attempts}


# --------------------------------------------------------------------------- #
# HTTP (one patchable function)
# --------------------------------------------------------------------------- #
def _http_post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any]]:
    """POST JSON, return (status, parsed body). HTTP errors are returned, network errors raised as LLMError."""
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https endpoints)
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            body = {}
        return exc.code, body
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        raise LLMError(f"network error: {type(exc).__name__}", retryable=True) from exc
    except ValueError as exc:
        raise LLMError("provider returned a non-JSON response", retryable=True) from exc


def _error_message(body: Dict[str, Any]) -> str:
    err = body.get("error", body)
    if isinstance(err, dict):
        return str(err.get("message") or err.get("status") or err)[:300]
    return str(err)[:300]


def _raise_for_status(provider: str, status: int, body: Dict[str, Any]) -> None:
    if 200 <= status < 300:
        return
    retryable = status in (408, 409, 425, 429) or status >= 500
    raise LLMError(f"HTTP {status}: {_error_message(body)}", provider=provider, status=status, retryable=retryable)


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in ``text`` (tolerates code fences and surrounding prose)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty response")
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\{\[]", cleaned):
        try:
            value, _end = decoder.raw_decode(cleaned[match.start():])
            return value
        except ValueError:
            continue
    raise ValueError("no JSON found in response")


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
Mutator = Callable[[Dict[str, Any]], None]


class Provider:
    name = "base"

    def __init__(self, model: str = ""):
        self.model = model

    def _send(self, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float,
              droppable: Dict[str, Mutator]) -> Tuple[int, Dict[str, Any]]:
        """POST; if the provider answers HTTP 400 naming an optional parameter, retry without that parameter.

        Newer models sometimes reject parameters older ones accept (``temperature``, ``response_format``).
        Dropping the offending one and retrying keeps a good model usable instead of failing over.
        """
        remaining = dict(droppable)
        while True:
            status, body = _http_post(url, headers, payload, timeout)
            if status != 400 or not remaining:
                return status, body
            message = _error_message(body).lower()
            hit = next((name for name in remaining if name.lower() in message), None)
            if hit is None:
                return status, body
            remaining.pop(hit)(payload)
            log.info("%s rejected '%s'; retrying without it", self.name, hit)

    def available(self) -> bool:  # pragma: no cover - overridden
        return False

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float, json_mode: bool,
                 timeout: float) -> Tuple[str, str]:
        """Return (text, model_actually_used)."""
        raise NotImplementedError


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


class OpenRouterProvider(Provider):
    """https://openrouter.ai: OpenAI-compatible; ``models`` + ``route: fallback`` gives server-side model fallback."""

    name = "openrouter"
    url = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 fallback_models: Optional[List[str]] = None,
                 data_collection: Optional[str] = None, zdr: Optional[bool] = None):
        super().__init__(_env("OPENROUTER_MODEL") if model is None else model)
        self.api_key = _env("OPENROUTER_API_KEY") if api_key is None else api_key
        policy = (data_collection or _env("OPENROUTER_DATA_COLLECTION") or "deny").lower()
        self.data_collection = policy if policy in ("allow", "deny") else "deny"
        self.zdr = zdr if zdr is not None else _env("OPENROUTER_ZDR").lower() in ("1", "true", "yes", "on")
        raw = fallback_models if fallback_models is not None else _env("OPENROUTER_FALLBACK_MODELS").split(",")
        self.fallback_models = [m.strip() for m in raw if m and m.strip() and m.strip() != self.model]

    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def complete(self, system, user, *, max_tokens, temperature, json_mode, timeout):
        payload: Dict[str, Any] = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.fallback_models:
            payload["models"] = [self.model] + self.fallback_models
            payload["route"] = "fallback"
        else:
            payload["model"] = self.model
        if json_mode:
            payload["response_format"] = {"type": "json_object"}  # ignored by models that do not support it
        # Route only to providers that do not store prompts (patient context may be present).
        payload["provider"] = {"data_collection": self.data_collection}
        if self.zdr:
            payload["provider"]["zdr"] = True
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                   "X-Title": _env("OPENROUTER_APP_NAME") or "Med Perplexity"}
        referer = _env("OPENROUTER_SITE_URL")
        if referer:
            headers["HTTP-Referer"] = referer
        status, body = self._send(self.url, headers, payload, timeout, {
            "response_format": lambda p: p.pop("response_format", None),
            "temperature": lambda p: p.pop("temperature", None)})
        _raise_for_status(self.name, status, body)
        if "error" in body and not body.get("choices"):  # upstream failure reported inside a 200
            code = body["error"].get("code") if isinstance(body["error"], dict) else None
            raise LLMError(f"upstream error: {_error_message(body)}", provider=self.name,
                           status=code if isinstance(code, int) else None, retryable=True)
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape", provider=self.name, retryable=False) from None
        if not isinstance(text, str) or not text.strip():
            raise LLMError("empty completion", provider=self.name, retryable=True)
        return text, str(body.get("model") or self.model)


class AnthropicProvider(Provider):
    """Claude via the Anthropic Messages API."""

    name = "anthropic"
    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        if model is None:
            model = _env("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL
        super().__init__(model)
        self.api_key = _env("ANTHROPIC_API_KEY") if api_key is None else api_key

    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def complete(self, system, user, *, max_tokens, temperature, json_mode, timeout):
        payload = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                   "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        status, body = self._send(self.url, headers, payload, timeout,
                                  {"temperature": lambda p: p.pop("temperature", None)})
        _raise_for_status(self.name, status, body)
        blocks = body.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        if not text.strip():
            raise LLMError("empty completion", provider=self.name, retryable=True)
        return text, str(body.get("model") or self.model)


class OpenAIProvider(Provider):
    """OpenAI Chat Completions. ``temperature`` is omitted because some current models only accept the default."""

    name = "openai"
    url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        super().__init__(_env("OPENAI_MODEL") if model is None else model)
        self.api_key = _env("OPENAI_API_KEY") if api_key is None else api_key

    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def complete(self, system, user, *, max_tokens, temperature, json_mode, timeout):
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}  # requires the word "JSON" in the prompt
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        status, body = self._send(self.url, headers, payload, timeout,
                                  {"response_format": lambda p: p.pop("response_format", None)})
        _raise_for_status(self.name, status, body)
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape", provider=self.name) from None
        if not isinstance(text, str) or not text.strip():
            raise LLMError("empty completion (possibly a refusal)", provider=self.name, retryable=True)
        return text, str(body.get("model") or self.model)


class GeminiProvider(Provider):
    """Google Gemini via the generateContent REST endpoint."""

    name = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        super().__init__(_env("GEMINI_MODEL") if model is None else model)
        self.api_key = _env("GOOGLE_API_KEY", "GEMINI_API_KEY") if api_key is None else api_key

    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def complete(self, system, user, *, max_tokens, temperature, json_mode, timeout):
        generation: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation,
            # Clinical text can trip the default "dangerous content" filter; relax only that one category.
            "safetySettings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"}],
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        status, body = self._send(self.base_url.format(model=self.model), headers, payload, timeout, {
            "responseMimeType": lambda p: p["generationConfig"].pop("responseMimeType", None),
            "temperature": lambda p: p["generationConfig"].pop("temperature", None)})
        _raise_for_status(self.name, status, body)
        block = (body.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMError(f"blocked by Gemini safety filter ({block})", provider=self.name)
        candidates = body.get("candidates") or []
        if not candidates:
            raise LLMError("no candidates returned", provider=self.name, retryable=True)
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text.strip():
            reason = candidates[0].get("finishReason", "unknown")
            raise LLMError(f"empty completion (finishReason={reason})", provider=self.name, retryable=reason != "SAFETY")
        return text, str(body.get("modelVersion") or self.model)


PROVIDER_CLASSES = {"openrouter": OpenRouterProvider, "anthropic": AnthropicProvider,
                    "openai": OpenAIProvider, "gemini": GeminiProvider}


# --------------------------------------------------------------------------- #
# Fallback orchestration
# --------------------------------------------------------------------------- #
Validator = Callable[[Any], Any]


class FallbackLLM:
    """Try providers in order until one returns valid, schema-checked JSON."""

    def __init__(self, providers: List[Provider], *, retries: int = 1, backoff_s: float = 1.0,
                 timeout_s: float = DEFAULT_TIMEOUT_S, sleep: Callable[[float], None] = time.sleep):
        self.providers = [p for p in providers if p.available()]
        self.retries, self.backoff_s, self.timeout_s, self._sleep = retries, backoff_s, timeout_s, sleep

    @classmethod
    def from_env(cls, **kwargs: Any) -> "FallbackLLM":
        order = [n.strip().lower() for n in os.environ.get("LLM_PROVIDERS", DEFAULT_PROVIDER_ORDER).split(",")]
        providers = [PROVIDER_CLASSES[n]() for n in order if n in PROVIDER_CLASSES]
        return cls(providers, **kwargs)

    @property
    def configured(self) -> List[str]:
        return [f"{p.name}:{p.model}" for p in self.providers]

    # -- one provider, with retry on transient errors
    def _call(self, provider: Provider, system: str, user: str, max_tokens: int, temperature: float,
              json_mode: bool) -> Tuple[str, str]:
        for attempt in range(self.retries + 1):
            try:
                return provider.complete(system, user, max_tokens=max_tokens, temperature=temperature,
                                         json_mode=json_mode, timeout=self.timeout_s)
            except LLMError as exc:
                exc.provider = exc.provider or provider.name
                if exc.retryable and attempt < self.retries:
                    self._sleep(self.backoff_s * (2 ** attempt))
                    continue
                raise
        raise LLMError("unreachable", provider=provider.name)  # pragma: no cover

    def complete_json(self, system: str, user: str, validator: Optional[Validator] = None, *,
                      max_tokens: int = 1200, temperature: float = 0.0) -> Tuple[Any, LLMResult]:
        """Return (validated object, LLMResult). Raises :class:`LLMUnavailable` if every provider fails."""
        if not self.providers:
            raise LLMUnavailable("No LLM provider is configured (set OPENROUTER_API_KEY and OPENROUTER_MODEL, "
                                 "or a fallback provider key).", [])
        started = time.perf_counter()
        attempts: List[Dict[str, Any]] = []
        for provider in self.providers:
            current_user = user
            for repair in (False, True):
                try:
                    text, model_used = self._call(provider, system, current_user, max_tokens, temperature, True)
                except LLMError as exc:
                    attempts.append({"provider": provider.name, "model": provider.model, "ok": False,
                                     "error": str(exc)[:200], "status": exc.status})
                    break  # provider-level failure: go to the next provider
                try:
                    value = extract_json(text)
                    if validator is not None:
                        value = validator(value)
                except (ValueError, TypeError, KeyError) as exc:
                    attempts.append({"provider": provider.name, "model": model_used, "ok": False,
                                     "error": f"invalid output: {str(exc)[:160]}"})
                    if repair:
                        break
                    current_user = (f"{user}\n\nYour previous reply was rejected: {str(exc)[:200]}. "
                                    "Reply again with ONLY the corrected JSON object, nothing else.")
                    continue
                attempts.append({"provider": provider.name, "model": model_used, "ok": True})
                return value, LLMResult(text, provider.name, model_used, attempts,
                                        int((time.perf_counter() - started) * 1000))
        raise LLMUnavailable("All LLM providers failed.", attempts)

    def check(self) -> List[Dict[str, Any]]:
        """Send a tiny request to each configured provider separately (for ``llm-check``)."""
        results = []
        for provider in self.providers:
            started = time.perf_counter()
            try:
                text, model_used = self._call(provider, "Reply with the JSON object {\"ok\": true} and nothing else.",
                                              "ping", 40, 0.0, True)
                ok = isinstance(extract_json(text), dict)
                results.append({"provider": provider.name, "model": model_used, "ok": ok,
                                "ms": int((time.perf_counter() - started) * 1000)})
            except (LLMError, ValueError) as exc:
                results.append({"provider": provider.name, "model": provider.model, "ok": False, "error": str(exc)[:200]})
        return results
