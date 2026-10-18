"""Paid model calls made by the evaluation tools: cached for good, metered, and guarded by the budget.

- The cache key covers everything that shapes the reply: model, effort, system prompt, user prompt, schema
  and output limit. A re-run reads the cache and spends nothing. Cached replies are committed records
  (eval/cache/llm/), as SOP §14.1 asks.
- Every reply that cost money goes into the spend ledger (econ.spend), failed and truncated ones included.
- OpenAI calls may use the Flex tier (half price) and Gemini bulk work may use Batch (see judge.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from econ import config, spend
from econ.answer.providers import GeminiModel, OpenAIModel, ProviderError, Usage

_lock = threading.Lock()


@dataclass
class Call:
    model: str
    system: str
    user: str
    schema: dict
    schema_name: str
    effort: str | None = None
    max_output_tokens: int = 2000
    purpose: str = "eval"
    tag: str = ""  # caller's id for the item (a need id, a chunk id); not part of the cache key

    def key(self) -> str:
        blob = json.dumps(
            [
                self.model,
                self.effort,
                self.system,
                self.user,
                self.schema,
                self.schema_name,
                self.max_output_tokens,
            ],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode()).hexdigest()


def cache_path(key: str):
    return config.path(spend.cfg().cache) / key[:2] / f"{key}.json"


def cached(call: Call) -> dict | None:
    p = cache_path(call.key())
    return json.loads(p.read_text()) if p.exists() else None


def estimate(call: Call) -> float:
    """A pessimistic cost: about 3.5 characters a token, and the whole output limit."""
    p_in, _, p_out = config.service().llm.prices_per_mtok[call.model]
    toks_in = (len(call.system) + len(call.user) + len(json.dumps(call.schema))) / 3.5
    return (toks_in * p_in + call.max_output_tokens * p_out) / 1e6


def _client(model: str, flex: bool):
    llm = config.service().llm
    prov = spend.provider_of(model)
    p = next(x for x in llm.providers if x.name == prov)
    key = os.environ.get(p.key_env, "") or "placeholder"  # the session proxy injects the real key
    if prov == "openai":
        return OpenAIModel(p, key, max(llm.timeout_seconds, 300), service_tier="flex" if flex else None)
    return GeminiModel(p, key, max(llm.timeout_seconds, 300))


def _meter(call: Call, usage: Usage, flex: bool) -> float:
    factor = 0.5 if flex else 1.0
    cost = usage.cost_usd * factor
    with _lock:
        spend.record(
            model=call.model,
            purpose=call.purpose,
            usage={
                "input": usage.input,
                "cached_input": usage.cached_input,
                "output": usage.output,
                "reasoning": usage.reasoning,
            },
            cost_usd=cost,
            mode="flex" if flex else "sync",
        )
    return cost


def run_one(call: Call, *, flex: bool = False, retries: int = 4) -> dict:
    """The cached reply, or a new one. Returns {"data", "usage", "cost_usd", "cached", ...}."""
    hit = cached(call)
    if hit is not None:
        return {**hit, "cached": True}
    prov = spend.provider_of(call.model)
    with _lock:
        spend.guard(prov, estimate(call))
    client = _client(call.model, flex)
    last = None
    for attempt in range(retries):
        try:
            rep = client.generate_json(
                system=call.system,
                user=call.user,
                schema=call.schema,
                schema_name=call.schema_name,
                model=call.model,
                effort=call.effort,
                max_output_tokens=call.max_output_tokens,
            )
        except ProviderError as e:
            if e.usage:
                _meter(call, e.usage, flex)
            last = str(e)
            # Capacity refusals (429, 503, Flex "resource unavailable") are worth a wait; others are not.
            if any(
                s in last
                for s in ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "ReadTimeout", "ConnectError")
            ):
                time.sleep(4 * 2**attempt)
                continue
            return {"error": last, "cached": False}
        cost = _meter(call, rep.usage, flex)
        out = {
            "model": call.model,
            "effort": call.effort,
            "schema_name": call.schema_name,
            "purpose": call.purpose,
            "tag": call.tag,
            "data": rep.data,
            "usage": rep.usage.__dict__,
            "cost_usd": round(cost, 6),
            "tier": "flex" if flex else "standard",
        }
        p = cache_path(call.key())
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, sort_keys=True, ensure_ascii=False, indent=1))
        tmp.replace(p)
        return {**out, "cached": False}
    return {"error": last or "retries exhausted", "cached": False}


def run_many(calls: list[Call], *, flex: bool = False, workers: int = 8, on_done=None) -> list[dict]:
    """Run calls concurrently, in input order. Three errors in a row stop new calls (SOP §20.5)."""
    results: list[dict | None] = [None] * len(calls)
    streak = {"n": 0}

    def work(i: int) -> None:
        if streak["n"] >= 3:
            results[i] = {"error": "stopped after three errors in a row", "cached": False}
            return
        r = run_one(calls[i], flex=flex)
        with _lock:
            streak["n"] = streak["n"] + 1 if "error" in r else 0
        results[i] = r
        if on_done:
            on_done(i, r)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, range(len(calls))))
    return results  # type: ignore[return-value]
