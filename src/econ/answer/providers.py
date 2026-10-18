"""Model adapters: one per provider, each a pinned HTTPS client, plus a scripted model for tests.

Pinning: the base URL comes from config/service.yaml, never from ambient variables; the key comes from
the environment under the name config gives; no organisation or project headers are sent; OpenAI calls
set store=false, so the provider keeps no copy of prompts full of document text.

These adapters follow the providers' documented REST shapes (checked 2026-10-18). No live call has been
made yet: the first key that arrives needs the smoke test in SOP §20.4.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from econ import config
from econ.config import Provider


class ProviderError(Exception):
    pass


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
    ) -> Reply:
        raise NotImplementedError


class OpenAIModel(Model):
    name = "openai"

    def __init__(self, provider: Provider, key: str, timeout: float):
        self.base = provider.base_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def generate_json(self, *, system, user, schema, schema_name, model, effort, max_output_tokens) -> Reply:
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
        t = time.time()
        try:
            r = httpx.post(
                f"{self.base}/responses",
                json=body,
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.key}"},
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"openai: {type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"openai: HTTP {r.status_code}: {r.text[:300]}")
        d = r.json()
        if d.get("status") == "incomplete":
            raise ProviderError(f"openai: incomplete ({(d.get('incomplete_details') or {}).get('reason')})")
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
            raise ProviderError(f"openai: refused: {refusal[:200]}")
        if text is None:
            raise ProviderError("openai: no output text")
        u = d.get("usage") or {}
        cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
        usage = Usage(
            model=model,
            input=(u.get("input_tokens", 0) or 0) - cached,
            cached_input=cached,
            output=u.get("output_tokens", 0) or 0,
            reasoning=(u.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
            seconds=round(time.time() - t, 2),
        ).price()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("openai: output is not JSON") from e
        return Reply(
            data=data, usage=usage, raw_finish=d.get("status", ""), meta={"response_id": d.get("id")}
        )


class GeminiModel(Model):
    name = "gemini"

    def __init__(self, provider: Provider, key: str, timeout: float):
        self.base = provider.base_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def generate_json(self, *, system, user, schema, schema_name, model, effort, max_output_tokens) -> Reply:
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
            r = httpx.post(
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
        cands = d.get("candidates") or []
        if not cands:
            block = (d.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError(f"gemini: no candidates (blocked: {block})")
        finish = cands[0].get("finishReason", "")
        if finish not in ("STOP", ""):
            raise ProviderError(f"gemini: finished with {finish}")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        u = d.get("usageMetadata") or {}
        cached = u.get("cachedContentTokenCount", 0) or 0
        thoughts = u.get("thoughtsTokenCount", 0) or 0
        usage = Usage(
            model=model,
            input=(u.get("promptTokenCount", 0) or 0) - cached,
            cached_input=cached,
            output=(u.get("candidatesTokenCount", 0) or 0) + thoughts,
            reasoning=thoughts,
            seconds=round(time.time() - t, 2),
        ).price()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("gemini: output is not JSON") from e
        return Reply(data=data, usage=usage, raw_finish=finish, meta={"model_version": d.get("modelVersion")})


class ScriptedModel(Model):
    """Replies from a function of (schema_name, user prompt). Tests only: the service never builds it."""

    name = "scripted"

    def __init__(self, fn: Callable[[str, str], dict], model: str = "gpt-6-luna"):
        self.fn, self.model = fn, model
        self.calls: list[dict] = []

    def generate_json(self, *, system, user, schema, schema_name, model, effort, max_output_tokens) -> Reply:
        self.calls.append({"schema_name": schema_name, "user": user, "model": model})
        return Reply(
            data=self.fn(schema_name, user),
            usage=Usage(model=model, input=len(user) // 4, output=200).price(),
        )


def configured() -> tuple[Model, Provider] | None:
    """The first provider in config whose key is in the environment; None means evidence-only mode."""
    llm = config.service().llm
    for p in llm.providers:
        key = os.environ.get(p.key_env, "").strip()
        if key:
            cls = OpenAIModel if p.name == "openai" else GeminiModel
            return cls(p, key, llm.timeout_seconds), p
    return None
