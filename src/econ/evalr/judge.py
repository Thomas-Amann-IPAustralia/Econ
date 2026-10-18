"""Graded relevance judgments for the judged test set, by a model from another family (Gemini).

Each need's pooled passages are shown in a hashed order, at most GROUP per request, with the need's
question and narrative; the judge returns a 0-3 grade per passage (prompts/judge-v1.md). Requests go by
Gemini's Batch API (half price) or, as a fallback, one by one. Every reply is a cached paid reply
(eval/cache/llm, same keys as econ.evalr.llmcall) and the grades are collected in
eval/judgments/<set>.jsonl, one line per (need, chunk).
"""

from __future__ import annotations

import hashlib
import json
import time

import httpx

from econ import config, spend
from econ.answer import pipeline
from econ.answer.providers import _gemini_usage
from econ.evalr import llmcall
from econ.evalr.judged import Need
from econ.manifest import write_text_atomic

PROMPT = "judge-v1"
GROUP = 20
SCHEMA = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "grade": {"type": "integer", "minimum": 0, "maximum": 3},
                },
                "required": ["id", "grade"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["grades"],
    "additionalProperties": False,
}


def _order(need_id: str, chunk_id: str) -> str:
    return hashlib.sha256(f"{need_id}|{chunk_id}".encode()).hexdigest()


def requests_for(
    need: Need, chunk_list: list[dict], *, model: str, effort: str
) -> list[tuple[llmcall.Call, dict]]:
    """Calls for one need, each with its map from local passage id to chunk id."""
    docs = config.sources().by_id()
    system = (config.ROOT / "prompts" / "eval" / f"{PROMPT}.md").read_text(encoding="utf-8")
    ordered = sorted(chunk_list, key=lambda c: _order(need.id, c["chunk_id"]))
    out = []
    for g in range(0, len(ordered), GROUP):
        part = ordered[g : g + GROUP]
        ids = {f"p{i + 1}": c["chunk_id"] for i, c in enumerate(part)}
        blocks = []
        for pid, c in zip(ids, part, strict=True):
            d = docs[c["doc_id"]]
            sec = " > ".join(c["section"]) if c["section"] else ""
            blocks.append(
                f'<passage id="{pid}" document="{pipeline.defang(d.title)}" year="{d.year}" '
                f'section="{pipeline.defang(sec)}">\n{pipeline.defang(c["text"])}\n</passage>'
            )
        user = (
            f"<need>\n<question>{pipeline.defang(need.question)}</question>\n"
            f"<narrative>{pipeline.defang(need.narrative)}</narrative>\n</need>\n\n" + "\n\n".join(blocks)
        )
        call = llmcall.Call(
            model=model,
            system=system,
            user=user,
            schema=SCHEMA,
            schema_name="grades",
            effort=effort,
            max_output_tokens=8000,
            purpose=f"judge:{PROMPT}:{model}",
            tag=need.id,
        )
        out.append((call, ids))
    return out


def parse(reply: dict, ids: dict) -> dict[str, int] | None:
    """chunk_id -> grade, or None if the reply doesn't grade every passage exactly once.

    Batch ignores the response schema (seen in the first batches, as in the reference build's D-027), so
    the grades come back in several shapes: {"grades": [...]}, a bare list, items keyed "grade" or
    "score", or a map from passage id to grade. All are read; the exactly-once check still applies."""
    if "error" in reply:
        return None
    data = reply["data"]
    if isinstance(data, dict) and isinstance(data.get("grades"), list | dict):
        data = data["grades"]
    pairs: list[tuple] = []
    if isinstance(data, list):
        for g in data:
            if isinstance(g, dict):
                val = next((g[k] for k in ("grade", "score", "relevance") if k in g), None)
                pairs.append((g.get("id"), val))
    elif isinstance(data, dict):
        pairs = list(data.items())
    got: dict[str, int] = {}
    for pid, val in pairs:
        if (
            pid not in ids
            or pid in got
            or isinstance(val, bool)
            or not isinstance(val, int)
            or not 0 <= val <= 3
        ):
            return None
        got[pid] = val
    if set(got) != set(ids):
        return None
    return {ids[k]: v for k, v in got.items()}


# --- Gemini Batch ----------------------------------------------------------------------------------


def _gen_config(call: llmcall.Call) -> dict:
    gen = {
        "responseMimeType": "application/json",
        "responseJsonSchema": call.schema,
        "maxOutputTokens": call.max_output_tokens,
    }
    if call.effort:
        gen["thinkingConfig"] = {"thinkingLevel": call.effort}
    return gen


def batch_reserve(calls: list[llmcall.Call], expected_output: int = 400) -> float:
    """A batch's reserve at the Batch price: its input (4 characters a token) and an expected output per
    request, plus 20%. Calibrated on the judge pilot: 4.4 characters a token, 284 output tokens a reply;
    this formula reserved 1.2 times the pilot's actual cost."""
    p_in, _, p_out = config.service().llm.prices_per_mtok[calls[0].model]
    toks = sum((len(c.system) + len(c.user)) / 4.0 for c in calls)
    return 1.2 * 0.5 * (toks * p_in + len(calls) * expected_output * p_out) / 1e6


def submit_batch(calls: list[llmcall.Call], name: str) -> str:
    model = calls[0].model
    assert all(c.model == model for c in calls)
    spend.guard("gemini", batch_reserve(calls))
    body = {
        "batch": {
            "display_name": name,
            "input_config": {
                "requests": {
                    "requests": [
                        {
                            "request": {
                                "systemInstruction": {"parts": [{"text": c.system}]},
                                "contents": [{"role": "user", "parts": [{"text": c.user}]}],
                                "generationConfig": _gen_config(c),
                            },
                            "metadata": {"key": c.key()},
                        }
                        for c in calls
                    ]
                }
            },
        }
    }
    base = next(p for p in config.service().llm.providers if p.name == "gemini").base_url.rstrip("/")
    r = httpx.post(
        f"{base}/models/{model}:batchGenerateContent",
        json=body,
        headers={"x-goog-api-key": "placeholder"},
        timeout=300,
    )
    if r.status_code != 200:
        raise RuntimeError(f"batch create failed: HTTP {r.status_code}: {r.text[:500]}")
    return r.json()["name"]


def poll(batch: str, every: float = 30, limit: float = 6 * 3600, log=print) -> dict:
    base = next(p for p in config.service().llm.providers if p.name == "gemini").base_url.rstrip("/")
    t0 = time.time()
    while True:
        r = httpx.get(f"{base}/{batch}", headers={"x-goog-api-key": "placeholder"}, timeout=120)
        r.raise_for_status()
        d = r.json()
        state = (d.get("metadata") or {}).get("state") or d.get("state")
        if d.get("done") or state in (
            "JOB_STATE_SUCCEEDED",
            "JOB_STATE_FAILED",
            "JOB_STATE_CANCELLED",
            "JOB_STATE_EXPIRED",
            "BATCH_STATE_SUCCEEDED",
            "BATCH_STATE_FAILED",
        ):
            return d
        if time.time() - t0 > limit:
            raise TimeoutError(f"batch {batch} still {state} after {limit:.0f}s")
        log(f"{batch}: {state} ({time.time() - t0:.0f}s)")
        time.sleep(every)


def _inlined(d: dict) -> list[dict]:
    for path in (
        ("response", "inlinedResponses"),
        ("dest", "inlinedResponses"),
        ("metadata", "output", "inlinedResponses"),
    ):
        node = d
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        if node:
            return node.get("inlinedResponses", node) if isinstance(node, dict) else node
    return []


def collect(d: dict, calls: list[llmcall.Call]) -> dict[str, dict]:
    """Cache every reply under its call's key and meter it at the batch price. Returns key -> reply."""
    by_key = {c.key(): c for c in calls}
    out = {}
    for item in _inlined(d):
        key = (item.get("metadata") or {}).get("key")
        call = by_key.get(key)
        if call is None:
            continue
        resp = item.get("response")
        if not resp:
            out[key] = {"error": json.dumps(item.get("error"))[:300]}
            continue
        usage = _gemini_usage(resp, call.model, 0.0)
        cost = usage.cost_usd * 0.5
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
            mode="batch",
        )
        cands = resp.get("candidates") or []
        parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            out[key] = {"error": f"not JSON (finish {cands[0].get('finishReason') if cands else None})"}
            continue
        rec = {
            "model": call.model,
            "effort": call.effort,
            "schema_name": call.schema_name,
            "purpose": call.purpose,
            "tag": call.tag,
            "data": data,
            "usage": usage.__dict__,
            "cost_usd": round(cost, 6),
            "tier": "batch",
        }
        p = llmcall.cache_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, sort_keys=True, ensure_ascii=False, indent=1))
        out[key] = rec
    return out


def save(name: str, rows: list[dict]) -> None:
    out = config.path("eval/judgments") / f"{name}.jsonl"
    rows = sorted(rows, key=lambda r: (r["need"], r["chunk_id"]))
    write_text_atomic(out, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def load(name: str) -> dict[tuple[str, str], int]:
    p = config.path("eval/judgments") / f"{name}.jsonl"
    if not p.exists():
        return {}
    return {
        (r["need"], r["chunk_id"]): r["grade"]
        for r in (json.loads(x) for x in p.read_text().splitlines() if x.strip())
    }
