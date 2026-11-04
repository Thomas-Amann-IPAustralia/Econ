"""The atlas chat's free retrieval measurement (D-038, WP5): no model calls.

The question is the only query (no plan), and the measure is whether the passages the answer would see come from
the right pages:
- lookups and by-id needs: the share whose gold observations are all among the documents of the 20-passage
  context (search order; the relevance filter can only choose from the pool) and of the 60-passage pool the filter
  reads;
- exploratory needs: the recall of their gold sets in the context and in the pool.

Variants: the code-written context notes on and off (both lanes); `per_doc_cap` 4 and 8; and pinning (D-038) on
and off, which matters only where the question names an id. The notes-off vectors are cached in data/ (ignored).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from econ import config
from econ.answer import pipeline
from econ.kb.bm25 import BM25
from econ.manifest import write_json_atomic, write_text_atomic
from econ.retrieval.index import Index, Selected

TESTSET = "eval/atlas/atlas-v1.jsonl"
RUNS = "eval/runs/atlas-v1"
REPORT = "reports/retrieval-atlas-v1.md"
READ, CONTEXT = 60, 20


def load_needs(path: str = TESTSET) -> list[dict]:
    return [json.loads(x) for x in config.path(path).read_text().splitlines() if x.strip()]


def _cache(name: str) -> Path:
    d = config.path("data/cache/atlas")
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def plain_lanes(idx: Index, emb) -> tuple[np.ndarray, BM25]:
    """The index's lanes without the context notes: the passage text alone."""
    texts = [c["embed_text"] for c in idx.chunks]
    key = hashlib.sha256("\n\0".join(texts).encode()).hexdigest()[:16]
    p = _cache(f"vectors-nonotes-{key}.npy")
    if p.exists():
        vecs = np.load(p)
    else:
        vecs = emb.encode(texts, kind="doc").astype(np.float32)
        np.save(p, vecs)
    return vecs, BM25.build(texts)


def query_vectors(needs: list[dict], emb) -> np.ndarray:
    qs = [n["question"] for n in needs]
    key = hashlib.sha256("\n\0".join(qs).encode()).hexdigest()[:16]
    p = _cache(f"queries-{key}.npy")
    if p.exists():
        return np.load(p)
    v = emb.encode(qs, kind="query").astype(np.float32)
    np.save(p, v)
    return v


def retrieve(idx: Index, need: dict, qvec: np.ndarray, *, cap: int, pin: bool) -> tuple[list[str], list[str]]:
    """The documents of the 20-passage context and of the 60-passage pool, as the service would assemble them
    with the filter keeping the search order."""
    ranked, _ = idx.search([need["question"]], qvec[None, :])
    rows: list[int] = []
    if pin:
        svc = pipeline.Services(index=idx, embedder=None, kb=config.kb("atlas"), kb_name="atlas")
        _, rows = pipeline.pinned_rows(svc, [need["question"]], None)
        ranked = [s for s in ranked if s.row not in set(rows)]
    pool = idx.context(ranked, READ, per_doc_cap=cap)
    context = [Selected(r, 0.0, 0) for r in rows] + pool[: CONTEXT - len(rows)]
    doc = lambda s: idx.chunks[s.row]["doc_id"][len("atlas-") :]  # noqa: E731
    return [doc(s) for s in context], [doc(s) for s in [*context[: len(rows)], *pool]]


def score(needs: list[dict], got: dict[str, tuple[list[str], list[str]]]) -> dict:
    out: dict = {}
    for kind in ("lookup", "by_id", "exploratory"):
        ns = [n for n in needs if n["kind"] == kind]
        ctx = [len(set(n["gold"]) & set(got[n["id"]][0])) / len(n["gold"]) for n in ns]
        pool = [len(set(n["gold"]) & set(got[n["id"]][1])) / len(n["gold"]) for n in ns]
        if kind == "exploratory":
            out[kind] = {"n": len(ns), "context_recall": _mean(ctx), "pool_recall": _mean(pool)}
        else:
            out[kind] = {
                "n": len(ns),
                "in_context": sum(x == 1.0 for x in ctx) / len(ns),
                "in_pool": sum(x == 1.0 for x in pool) / len(ns),
                "missed": [n["id"] for n, x in zip(ns, ctx, strict=True) if x < 1.0],
            }
    return out


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def run(emb) -> dict:
    """Every variant, written to eval/runs/atlas-v1/ and the report."""
    import os

    akb = config.kb("atlas")
    root = Path(os.environ.get(akb.index_env or "") or config.path(akb.index_dir))
    idx = Index(root)
    needs = [n for n in load_needs() if n["kind"] != "out_of_scope"]
    qv = query_vectors(needs, emb)
    with_notes = (idx.vecs, idx.bm25)
    without = plain_lanes(idx, emb)
    variants = {}
    for notes in (True, False):
        idx.vecs, idx.bm25 = with_notes if notes else without
        for cap in (4, 8):
            for pin in (True, False):
                name = f"notes-{'on' if notes else 'off'}.cap{cap}.pin-{'on' if pin else 'off'}"
                got = {n["id"]: retrieve(idx, n, qv[i], cap=cap, pin=pin) for i, n in enumerate(needs)}
                variants[name] = {"scores": score(needs, got), "context": {k: v[0] for k, v in got.items()}}
    idx.vecs, idx.bm25 = with_notes
    result = {
        "testset": TESTSET,
        "index": {k: idx.meta.get(k) for k in ("atlas_ref", "atlas_passages_sha256", "embedder", "chunks")},
        "variants": variants,
    }
    out = config.path(RUNS)
    write_json_atomic(out / "results.json", result)
    write_text_atomic(config.path(REPORT), report(result, needs))
    return result


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def report(result: dict, needs: list[dict]) -> str:
    v = result["variants"]
    rows = []
    for name, r in v.items():
        s = r["scores"]
        rows.append(
            f"| {name} | {_pct(s['lookup']['in_context'])} | {_pct(s['lookup']['in_pool'])} | "
            f"{_pct(s['by_id']['in_context'])} | {_pct(s['by_id']['in_pool'])} | "
            f"{s['exploratory']['context_recall']:.3f} | {s['exploratory']['pool_recall']:.3f} |"
        )
    best = v["notes-on.cap4.pin-on"]["scores"]
    q = {n["id"]: n for n in needs}
    missed = "\n".join(
        f"- {i} ({q[i]['lens']}, Stage {q[i]['stage']}): \"{q[i]['question']}\" (gold {', '.join(q[i]['gold'])})"
        for i in best["lookup"]["missed"]
    )
    return (
        "# Retrieval for the atlas chat (atlas-v1)\n\n"
        "A free measurement, with no model calls (D-038, WP5). Each question was searched as asked (no plan), over "
        f"the atlas index built from commit `{str(result['index']['atlas_ref'])[:12]}` "
        f"({result['index']['chunks']} passages). The service's relevance filter then chooses 20 passages from the "
        "60 the search reads; it can't be run free, so the context here is the search's own first 20, and the pool "
        "is the 60 the filter would read. Pinning puts an observation's own passages first when the question names "
        "its id.\n\n"
        "The test set (`eval/atlas/atlas-v1.jsonl`) was written and committed before any number: 20 lookups by "
        "topic without ids (one gold observation each, over all eight lenses and three stages), 5 by id, 10 "
        "exploratory needs with gold sets, and 5 out of scope (not measured here).\n\n"
        "| Variant | Lookups: gold in the 20 | in the 60 | By id: in the 20 | in the 60 | "
        "Exploratory recall, 20 | in 60 |\n|---|---:|---:|---:|---:|---:|---:|\n"
        + "\n".join(rows)
        + "\n\n## Lookups missed by the configured variant (notes on, cap 4, pinning on)\n\n"
        + (missed or "None.")
        + "\n"
    )
