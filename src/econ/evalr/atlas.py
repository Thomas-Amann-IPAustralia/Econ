"""The atlas chat's free retrieval measurement (D-038, WP5): no model calls.

The question is the only query (no plan), and the measure is whether the passages the answer would see come from
the right pages:
- lookups and by-id needs: the share whose gold observations are all among the documents of the 20-passage
  context (search order; the relevance filter can only choose from the pool) and of the 60-passage pool the filter
  reads;
- exploratory needs: the recall of their gold sets in the context and in the pool.

Variants: the code-written context notes on and off (both lanes); `per_doc_cap` 2, 3, 4 and 8; and pinning (D-038)
on and off, which matters only where the question names an id. The notes-off vectors are cached in data/ (ignored).
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


def cached_doc_vectors(texts: list[str], emb) -> np.ndarray:
    """The embedder's document vectors for `texts`, kept in data/cache/atlas (ignored) by a hash of the texts and
    the model, so a measured variant can be indexed without embedding it again."""
    key = hashlib.sha256(("\n\0".join(texts) + f"\0{emb.meta.get('onnx_sha256')}").encode()).hexdigest()[:16]
    p = _cache(f"vectors-{key}.npy")
    if p.exists():
        return np.load(p)
    vecs = emb.encode(texts, kind="doc").astype(np.float32)
    np.save(p, vecs)
    return vecs


def lanes(idx: Index, emb, *, notes: bool) -> tuple[np.ndarray, BM25]:
    """Both lanes over the passage text, with or without its context note in front."""
    texts = [
        ((c.get("context_note") or "") + "\n\n" + c["embed_text"]).strip() if notes else c["embed_text"]
        for c in idx.chunks
    ]
    return cached_doc_vectors(texts, emb), BM25.build(texts)


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
    from econ.ingest import atlas as ingest

    notes = ingest.load_notes()
    for c in idx.chunks:  # the notes from the ingest, whether or not the index holds them
        c["context_note"] = notes[c["chunk_id"]]
    with_notes = lanes(idx, emb, notes=True)
    without = lanes(idx, emb, notes=False)
    variants = {}
    for notes in (True, False):
        idx.vecs, idx.bm25 = with_notes if notes else without
        for cap in (2, 3, 4, 8):
            for pin in (True, False):
                name = f"notes-{'on' if notes else 'off'}.cap{cap}.pin-{'on' if pin else 'off'}"
                got = {n["id"]: retrieve(idx, n, qv[i], cap=cap, pin=pin) for i, n in enumerate(needs)}
                variants[name] = {
                    "scores": score(needs, got),
                    "context": {k: v[0] for k, v in got.items()},
                    "pool": {k: sorted(set(v[1])) for k, v in got.items()},
                }
    result = {
        "testset": TESTSET,
        "index": {k: idx.meta.get(k) for k in ("atlas_ref", "atlas_passages_sha256", "embedder", "chunks")},
        "variants": variants,
    }
    out = config.path(RUNS)
    write_json_atomic(out / "results.json", result)
    write_text_atomic(config.path(REPORT), report(result, needs))
    return result


def _decision(v: dict, adopted: str) -> str:
    s = lambda name: v[name]["scores"]  # noqa: E731
    on = adopted.replace("notes-off", "notes-on")
    caps = {
        c: s(adopted.replace(".cap2.", f".cap{c}."))["exploratory"]["context_recall"] for c in (2, 3, 4, 8)
    }
    return (
        f"Adopted: **{adopted}**. Every variant with pinning finds every lookup's and every by-id need's gold "
        f"pages in the 20 passages ({_pct(s(adopted)['lookup']['in_context'])} and "
        f"{_pct(s(adopted)['by_id']['in_context'])}), so the exploratory needs decide. "
        f"Without the notes, the 60 passages the filter chooses from hold {s(adopted)['exploratory']['pool_recall']:.3f} "
        f"of their gold pages against {s(on)['exploratory']['pool_recall']:.3f} with them, while the search's own first "
        f"20 hold {s(adopted)['exploratory']['context_recall']:.3f} against {s(on)['exploratory']['context_recall']:.3f}. "
        "A note repeats its observation's headline on every passage of the page, so one well-matched page fills more "
        "of the candidates; the service's filter picks from the pool, so the pool's reach matters more. "
        "Recall in the 20 by the cap a page may hold (notes off): "
        + ", ".join(f"{c}: {r:.3f}" for c, r in caps.items())
        + ". Pinning is what finds a named observation and the Stage 3 page that tested it: without it, by-id needs "
        f"fall to {_pct(s(adopted.replace('pin-on', 'pin-off'))['by_id']['in_context'])}. "
        "The test set is small (40 needs, written from the pages, so its words are the pages' words); the smoke "
        "test reads real answers."
    )


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
    acfg, akb = config.atlas(), config.kb("atlas")
    adopted = f"notes-{'on' if acfg.index_notes else 'off'}.cap{akb.per_doc_cap}.pin-{'on' if akb.pin_observations else 'off'}"
    best = v[adopted]["scores"]
    q = {n["id"]: n for n in needs}
    missed = "\n".join(
        f'- {i} ({q[i]["lens"]}, Stage {q[i]["stage"]}): "{q[i]["question"]}" (gold {", ".join(q[i]["gold"])})'
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
        + "\n\n## Decision (free retrieval settings, delegated by D-013's brief; recorded in D-038)\n\n"
        + _decision(v, adopted)
        + f"\n\n## Lookups missed by the configured variant ({adopted})\n\n"
        + (missed or "None.")
        + "\n\n## Exploratory needs, need by need (the configured variant, and with notes)\n\n"
        + "| Need | Gold pages | In the 20 | In the 60 | With notes: in the 20 | in the 60 |\n|---|---:|---:|---:|---:|---:|\n"
        + "\n".join(
            f"| {n['id']}: {n['question']} | {len(n['gold'])} | "
            + " | ".join(
                str(
                    len(
                        set(n["gold"])
                        & set(v[name]["context"][n["id"]] if part == "ctx" else v[name]["pool"][n["id"]])
                    )
                )
                for name in (adopted, adopted.replace("notes-off", "notes-on"))
                for part in ("ctx", "pool")
            )
            + " |"
            for n in needs
            if n["kind"] == "exploratory"
        )
        + "\n"
    )
