"""SOP §20.4: a few questions through the live pipeline per provider, every event kept for reading.

Writes eval/smoke/<provider>-<run>.jsonl (every event of every question) and meters spend in the ledger.
"""

from __future__ import annotations

import json
import os
import time

from econ import config, spend
from econ.answer import pipeline
from econ.answer.providers import GeminiModel, OpenAIModel
from econ.manifest import write_text_atomic

QUESTIONS = [
    ("lookup", "How did IP Australia's patent workload per examiner compare with the UK and US offices?"),
    ("broad", "What statistical methods are used by the chief economist to establish causality?"),
    ("oos", "What's a good recipe for pavlova?"),
]


def run(provider_name: str, run_id: str, embedder, index, limit: int | None = None) -> dict:
    llm = config.service().llm
    prov = next(p for p in llm.providers if p.name == provider_name)
    key = os.environ.get(prov.key_env, "")
    if not key:
        raise SystemExit(f"{prov.key_env} is not set (a placeholder is enough behind the proxy)")
    cls = OpenAIModel if provider_name == "openai" else GeminiModel
    model = cls(prov, key, llm.timeout_seconds)
    svc = pipeline.Services(index=index, embedder=embedder, model=model, provider=prov)
    events, summary = [], []
    for kind, q in QUESTIONS[:limit]:
        spend.guard(provider_name, 0.15)
        t = time.time()
        evs = list(pipeline.run(pipeline.Request(question=q), svc))
        done = evs[-1]
        for u in done.get("usage", []):
            spend.record(
                model=u["model"],
                purpose=f"smoke:{run_id}",
                usage={k: u[k] for k in ("input", "cached_input", "output", "reasoning")},
                cost_usd=u["cost_usd"],
            )
        events += [{"question": q, "kind": kind, **e} for e in evs]
        summary.append(
            {
                "kind": kind,
                "outcome": done.get("outcome"),
                "attempts": done.get("attempts"),
                "cost_usd": done.get("cost_usd"),
                "seconds": round(time.time() - t, 1),
                "errors": [e.get("message") for e in evs if e["event"] == "error"],
            }
        )
    out = config.path("eval/smoke") / f"{provider_name}-{run_id}.jsonl"
    write_text_atomic(out, "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in events))
    return {"provider": provider_name, "file": str(out), "questions": summary}
