"""Model adapters: one per provider, each a pinned HTTPS client, plus a scripted model for tests.

Pinning: the base URL comes from config/service.yaml, never from ambient variables; the key comes from
the environment under the name config gives; no organisation or project headers are sent; OpenAI calls
set store=false, so the provider keeps no copy of prompts full of document text.

These adapters follow the providers' documented REST shapes (checked 2026-10-18). No live call has been
made yet: the first key that arrives needs the smoke test in SOP §20.4.

Streaming (D-024): given `on_text`, the OpenAI adapter streams the reply (server-sent events) and passes each
piece of output text to it as it arrives, so the service can show the answer's prose while it is written.
The reply it returns is the same as without streaming. Other adapters ignore `on_text`.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx

from econ import config
from econ.config import Provider


class ProviderError(Exception):
    """A failed call. `usage` is set when the provider billed for it (a truncated or blocked reply), so
    the caller can still meter what it cost."""

    def __init__(self, message: str, usage: Usage | None = None):
        super().__init__(message)
        self.usage = usage


@dataclass
class Usage:
    """Exclusive buckets: input = uncached input; reasoning is counted inside output where the provider
    bills it as output."""

    model: str
    input: int = 0
    cached_input: int = 0
    output: int = 0
    reasoning: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0

    def price(self) -> Usage:
        p_in, p_cached, p_out = config.service().llm.prices_per_mtok[self.model]
        self.cost_usd = round(
            (self.input * p_in + self.cached_input * p_cached + self.output * p_out) / 1e6, 6
        )
        return self


@dataclass
class Reply:
    data: dict
    usage: Usage
    raw_finish: str = ""
    meta: dict = field(default_factory=dict)


TRANSIENT = (429, 500, 502, 503, 504)
RETRY_WAIT = 2.0


def post_once_more(url: str, *, json: dict, headers: dict, timeout: float) -> httpx.Response:
    """POST, and once more after a short wait if the first try failed transiently: a rate limit, a 5xx or
    a dropped connection. Those replies are not billed. Seen in D-014's run: an answer call returned
    "HTTP 502: upstream request failed" and the user would have had no answer."""
    for attempt in (1, 2):
        try:
            r = httpx.post(url, json=json, timeout=timeout, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == 2:
                raise
            time.sleep(RETRY_WAIT)
            continue
        if r.status_code in TRANSIENT and attempt == 1:
            time.sleep(RETRY_WAIT)
            continue
        return r
    raise AssertionError("unreachable")


class Model:
    """generate_json(system, user, schema) -> Reply. Subclasses are the only network code."""

    name: str = "model"

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        schema_name: str,
        model: str,
        effort: str | None,
        max_output_tokens: int,
        on_text: Callable[[str], None] | None = None,
    ) -> Reply:
        raise NotImplementedError


class OpenAIModel(Model):
    name = "openai"

    def __init__(self, provider: Provider, key: str, timeout: float, service_tier: str | None = None):
        self.base = provider.base_url.rstrip("/")
        self.key = key
        self.timeout = timeout
        # "flex" (evaluation only): half price, slower, and may be refused when capacity is short.
        self.service_tier = service_tier

    def generate_json(
        self, *, system, user, schema, schema_name, model, effort, max_output_tokens, on_text=None
    ) -> Reply:
        body = {
            "model": model,
            "instructions": system,
            "input": [{"role": "user", "content": user}],
            "text": {
                "format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}
            },
            "store": False,
            "max_output_tokens": max_output_tokens,
        }
        if effort:
            body["reasoning"] = {"effort": effort}
        if self.service_tier:
            body["service_tier"] = self.service_tier
        t = time.time()
        url, headers = f"{self.base}/responses", {"Authorization": f"Bearer {self.key}"}
        if on_text is not None:
            d = self._stream(url, body, headers, on_text)
        else:
            try:
                r = post_once_more(url, json=body, timeout=self.timeout, headers=headers)
            except httpx.HTTPError as e:
                raise ProviderError(f"openai: {type(e).__name__}") from e
            if r.status_code != 200:
                raise ProviderError(f"openai: HTTP {r.status_code}: {r.text[:300]}")
            d = r.json()
        return _openai_reply(d, model, time.time() - t)

    def _stream(self, url: str, body: dict, headers: dict, on_text: Callable[[str], None]) -> dict:
        """The response object from a streamed call, passing output text to `on_text` as it arrives. A
        transient failure is retried once, but only before any text has been passed on."""
        body = {**body, "stream": True}
        sent = False
        for attempt in (1, 2):
            try:
                with httpx.stream("POST", url, json=body, timeout=self.timeout, headers=headers) as r:
                    if r.status_code != 200:
                        r.read()
                        if r.status_code in TRANSIENT and attempt == 1:
                            time.sleep(RETRY_WAIT)
                            continue
                        raise ProviderError(f"openai: HTTP {r.status_code}: {r.text[:300]}")
                    final = None
                    for ev in sse_events(r.iter_lines()):
                        kind = ev.get("type", "")
                        if kind == "response.output_text.delta":
                            sent = True
                            on_text(ev.get("delta") or "")
                        elif kind in ("response.completed", "response.incomplete", "response.failed"):
                            final = ev.get("response") or {}
                        elif kind == "error":
                            raise ProviderError(f"openai: stream error: {str(ev.get('message') or ev)[:300]}")
                    if final is None:
                        raise ProviderError("openai: the stream ended before the response did")
                    return final
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt == 2 or sent:
                    raise ProviderError(f"openai: {type(e).__name__}") from e
                time.sleep(RETRY_WAIT)
            except httpx.HTTPError as e:
                raise ProviderError(f"openai: {type(e).__name__}") from e
        raise AssertionError("unreachable")


def sse_events(lines) -> Iterator[dict]:
    """The JSON payloads of a server-sent event stream, one per event."""
    data: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip() and data:
            payload = "\n".join(data)
            data = []
            if payload != "[DONE]":
                yield json.loads(payload)
    if data and data != ["[DONE]"]:
        yield json.loads("\n".join(data))


def _openai_reply(d: dict, model: str, seconds: float) -> Reply:
    """A Reply from a Responses API response object, streamed or not."""
    u = d.get("usage") or {}
    cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
    usage = Usage(
        model=model,
        input=(u.get("input_tokens", 0) or 0) - cached,
        cached_input=cached,
        output=u.get("output_tokens", 0) or 0,
        reasoning=(u.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
        seconds=round(seconds, 2),
    ).price()
    if d.get("status") == "incomplete":
        reason = (d.get("incomplete_details") or {}).get("reason")
        raise ProviderError(f"openai: incomplete ({reason})", usage)
    if d.get("status") == "failed":
        err = d.get("error") or {}
        raise ProviderError(f"openai: failed ({str(err.get('message') or err)[:200]})", usage)
    text, refusal = None, None
    for item in d.get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                text = c.get("text")
            elif c.get("type") == "refusal":
                refusal = c.get("refusal")
    if refusal:
        raise ProviderError(f"openai: refused: {refusal[:200]}", usage)
    if text is None:
        raise ProviderError("openai: no output text", usage)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ProviderError("openai: output is not JSON", usage) from e
    return Reply(data=data, usage=usage, raw_finish=d.get("status", ""), meta={"response_id": d.get("id")})


class GeminiModel(Model):
    name = "gemini"

    def __init__(self, provider: Provider, key: str, timeout: float):
        self.base = provider.base_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def generate_json(
        self, *, system, user, schema, schema_name, model, effort, max_output_tokens, on_text=None
    ) -> Reply:
        gen = {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "maxOutputTokens": max_output_tokens,
        }
        if effort and effort != "none":
            gen["thinkingConfig"] = {"thinkingLevel": effort}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen,
        }
        t = time.time()
        try:
            r = post_once_more(
                f"{self.base}/models/{model}:generateContent",
                json=body,
                timeout=self.timeout,
                headers={"x-goog-api-key": self.key},
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini: {type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"gemini: HTTP {r.status_code}: {r.text[:300]}")
        d = r.json()
        usage = _gemini_usage(d, model, time.time() - t)
        cands = d.get("candidates") or []
        if not cands:
            block = (d.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError(f"gemini: no candidates (blocked: {block})", usage)
        finish = cands[0].get("finishReason", "")
        if finish not in ("STOP", ""):
            raise ProviderError(f"gemini: finished with {finish}", usage)
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("gemini: output is not JSON", usage) from e
        return Reply(data=data, usage=usage, raw_finish=finish, meta={"model_version": d.get("modelVersion")})


def _gemini_usage(d: dict, model: str, seconds: float) -> Usage:
    u = d.get("usageMetadata") or {}
    cached = u.get("cachedContentTokenCount", 0) or 0
    thoughts = u.get("thoughtsTokenCount", 0) or 0
    return Usage(
        model=model,
        input=(u.get("promptTokenCount", 0) or 0) - cached,
        cached_input=cached,
        output=(u.get("candidatesTokenCount", 0) or 0) + thoughts,
        reasoning=thoughts,
        seconds=round(seconds, 2),
    ).price()


class ScriptedModel(Model):
    """Replies from a function of (schema_name, user prompt). Tests only: the service never builds it."""

    name = "scripted"

    def __init__(self, fn: Callable[[str, str], dict], model: str = "gpt-6-luna"):
        self.fn, self.model = fn, model
        self.calls: list[dict] = []

    def generate_json(
        self, *, system, user, schema, schema_name, model, effort, max_output_tokens, on_text=None
    ) -> Reply:
        self.calls.append({"schema_name": schema_name, "user": user, "model": model, "system": system})
        data = self.fn(schema_name, user)
        if on_text is not None:  # streamed as a provider would: the JSON text in small pieces
            text = json.dumps(data)
            for i in range(0, len(text), 7):
                on_text(text[i : i + 7])
        return Reply(data=data, usage=Usage(model=model, input=len(user) // 4, output=200).price())


def configured() -> tuple[Model, Provider] | None:
    """The first provider in config whose key is in the environment; None means evidence-only mode."""
    llm = config.service().llm
    for p in llm.providers:
        key = os.environ.get(p.key_env, "").strip()
        if key:
            cls = OpenAIModel if p.name == "openai" else GeminiModel
            return cls(p, key, llm.timeout_seconds), p
    return None
