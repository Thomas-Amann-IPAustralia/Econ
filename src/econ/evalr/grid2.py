"""Retrieval grid v2 on the judged test set: the pool, the graded metrics, the stages and the report.

Grid: eval/grids/retrieval-v2.yaml (committed before any judgment). Per-need rows go to
eval/runs/retrieval-v2/<stage>/<setting>.jsonl and the report to reports/retrieval-v2-<stage>.md.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace

import yaml

from econ import config
from econ.evalr import judge, metrics, systems
from econ.evalr.judged import Need
from econ.manifest import write_json_atomic, write_text_atomic

PLAIN, ENRICHED = "plain", "enriched:S384-noprefix-nocite.luna-enrich-v1"


def spec() -> dict:
    return yaml.safe_load(config.path("eval/grids/retrieval-v2.yaml").read_text())


def setting_name(s: systems.System) -> str:
    t = "plain" if s.text == PLAIN else "enriched"
    base = f"{s.query}/{t}/{s.reranker or 'none'}"
    if s.lane != "hybrid":
        base = f"{s.lane}:{base}"
    if s.cap != 8:
        base += f"/cap{s.cap}"
    if s.rr_depth != 50 and s.reranker:
        base += f"/rr{s.rr_depth}"
    return base


def make(query: str, text: str, reranker: str | None, **kw) -> systems.System:
    s = systems.System("", query=query, text=PLAIN if text == "plain" else text, reranker=reranker, **kw)
    return replace(s, name=setting_name(s))


def stage1_settings(include_reference: bool = True) -> list[systems.System]:
    st = spec()["stage1"]
    out = []
    for q in st["query"]:
        for t in st["text"]:
            for rr in st["reranker"]:
                out.append(make(q, t, None if rr == "none" else rr))
    if include_reference:
        # The reference rerankers ran on three first stages only (scratch job, see the progress log).
        for rr in st["reference_rerankers"]:
            for q, t in (("raw", PLAIN), ("plan:luna-plan-v2", ENRICHED), ("raw", ENRICHED)):
                out.append(make(q, t, rr))
    return out


def complexity(s: systems.System) -> int:
    q = {
        "raw": 0,
        "plan:luna-plan-v1": 0,
        "plan:flashlite-plan-v1": 1,
        "plan:luna-plan-v2": 1,
        "plan+q:luna-plan-v2": 1,
        "plan:flashlite-plan-v2": 2,
    }[s.query]
    return q + (s.text != PLAIN) + (s.reranker is not None)


# --- ranking with cached reranker scores ------------------------------------------------------------


_rr: dict[str, systems.RerankCache] = {}


def rr_cache(name: str) -> systems.RerankCache:
    if name not in _rr:
        _rr[name] = systems.RerankCache(systems.cache_key(name, "text", "bf16"))
    return _rr[name]


def context_rows(s: systems.System, need: Need) -> list[int]:
    rows = systems.rank(s, need, rr_cache(s.reranker) if s.reranker else None)
    return systems.context(s, rows)


# --- the pool ----------------------------------------------------------------------------------------


def pool_systems() -> list[tuple[systems.System, int]]:
    """Every system whose context goes into the pool, with how deep."""
    out: list[tuple[systems.System, int]] = []
    for s in stage1_settings():
        deep = s.query in ("raw", "plan:luna-plan-v1") and s.text == PLAIN and s.reranker is None
        out.append((s, 20 if deep else 10))
    out.append((make("raw", "plain", None, lane="bm25"), 10))
    out.append((make("raw", "plain", None, lane="dense"), 10))
    return out


def build_pool(needs: list[Need]) -> dict[str, list[int]]:
    pool: dict[str, set[int]] = {n.id: set() for n in needs}
    for s, k in pool_systems():
        for n in needs:
            pool[n.id] |= set(context_rows(s, n)[:k])
    return {nid: sorted(rows) for nid, rows in pool.items()}


# --- graded metrics -----------------------------------------------------------------------------------


def _dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def per_need(ctx: list[int], need: Need, grades: dict[str, int]) -> dict:
    cs = systems.chunks()
    ids = [cs[r]["chunk_id"] for r in ctx]
    g = [grades.get(c) for c in ids]
    gain = [(2**x - 1) if x is not None else 0.0 for x in g]
    ideal = sorted((2**x - 1 for x in grades.values()), reverse=True)
    out: dict[str, float | None] = {}
    for k in (10, 20):
        idcg = _dcg(ideal[:k])
        out[f"ndcg@{k}"] = _dcg(gain[:k]) / idcg if idcg > 0 else None
    n_rel = sum(1 for x in grades.values() if x >= 2)
    rel_in = sum(1 for x in g[:20] if x is not None and x >= 2)
    out["rel_recall@20"] = rel_in / n_rel if n_rel else None
    out["p@20"] = rel_in / max(1, len(ctx[:20]))
    out["judged@20"] = sum(1 for x in g[:20] if x is not None) / max(1, len(ctx[:20]))
    if need.golds:
        m = metrics.per_need([cs[r] for r in ctx], need.golds)
        covered = set().union(*metrics.judge([cs[r] for r in ctx[:20]], need.golds)) if ctx else set()
        out["gold_recall@20"] = len(covered) / len(need.golds)
        out["gold_recall@4k_tok"] = m["recall@4k_tok"]
    else:
        out["gold_recall@20"] = out["gold_recall@4k_tok"] = None
    return out


def grades_by_need(name: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for (nid, cid), g in judge.load(name).items():
        out.setdefault(nid, {})[cid] = g
    return out


def evaluate(s: systems.System, needs: list[Need], grades: dict[str, dict[str, int]]) -> list[dict]:
    rows = []
    for n in needs:
        ctx = context_rows(s, n)
        m = per_need(ctx, n, grades.get(n.id, {}))
        rows.append(
            {
                "need": n.id,
                "family": n.family,
                "kind": n.kind,
                "split": n.split,
                **m,
                "context": [systems.chunks()[r]["chunk_id"] for r in ctx],
            }
        )
    return rows


def mean_of(rows: list[dict], metric: str, **where) -> float:
    xs = [r[metric] for r in rows if r[metric] is not None and all(r[k] == v for k, v in where.items())]
    return metrics.mean(xs)


def paired(a: list[dict], b: list[dict], metric: str, **where) -> tuple[list[float], list[float]]:
    xa, xb = [], []
    for ra, rb in zip(a, b, strict=True):
        if any(ra[k] != v for k, v in where.items()):
            continue
        if ra[metric] is None or rb[metric] is None:
            continue
        xa.append(ra[metric])
        xb.append(rb[metric])
    return xa, xb


def save_rows(stage: str, name: str, rows: list[dict]) -> None:
    p = config.path("eval/runs/retrieval-v2") / stage / (name.replace("/", "__").replace(":", "-") + ".jsonl")
    write_text_atomic(p, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def save_choice(stage: str, choice: dict) -> None:
    write_json_atomic(config.path("eval/runs/retrieval-v2") / stage / "choice.json", choice)
