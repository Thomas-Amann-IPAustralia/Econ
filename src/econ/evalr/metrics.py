"""Retrieval metrics over gold spans, and paired statistics.

A ranked list of chunks is judged against a need's golds. A chunk *covers* a gold when its spans hold at
least `cover` of the gold's characters. Gains are novelty-based: a chunk earns a gain only for golds no
higher-ranked chunk already covered, so overlapping windows can't count one passage twice.

- recall_at_tokens(T): share of golds covered by the top chunks that fit in T tokens of context. This
  compares chunkings fairly, since a larger chunk costs more of the model's context.
- ndcg@10 (binary, novelty-based), mrr@10, recall@k chunks, doc_hit@5.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

COVER = 0.5


def covers(chunk: dict, gold, cover: float = COVER) -> bool:
    """`gold` is one Gold or a tuple of alternatives, any of which counts."""
    if isinstance(gold, tuple):
        return any(covers(chunk, g, cover) for g in gold)
    if chunk["doc_id"] != gold.doc_id:
        return False
    need = (gold.end - gold.start) * cover
    got = sum(max(0, min(e, gold.end) - max(s, gold.start)) for s, e in chunk["spans"])
    return got >= need


def judge(ranked: Sequence[dict], golds) -> list[set[int]]:
    """For each ranked chunk, the indices of the golds it covers."""
    return [{i for i, g in enumerate(golds) if covers(c, g)} for c in ranked]


def per_need(ranked: Sequence[dict], golds, budgets=(1000, 2000, 4000, 8000)) -> dict:
    hits = judge(ranked, golds)
    n = len(golds)
    out: dict[str, float] = {}
    # Novelty gains.
    seen: set[int] = set()
    gains = []
    for h in hits:
        new = h - seen
        gains.append(1.0 if new else 0.0)
        seen |= h
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:10]))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(n, 10)))
    out["ndcg@10"] = dcg / idcg if idcg else 0.0
    first = next((i for i, h in enumerate(hits[:10]) if h), None)
    out["mrr@10"] = 1.0 / (first + 1) if first is not None else 0.0
    for k in (5, 10, 20):
        cov = set().union(*hits[:k]) if hits[:k] else set()
        out[f"recall@{k}"] = len(cov) / n
    for t in budgets:
        used, cov = 0, set()
        for c, h in zip(ranked, hits, strict=False):
            used += c["tokens"]
            if used > t:
                break
            cov |= h
        out[f"recall@{t // 1000}k_tok"] = len(cov) / n
    gold_docs = {g.doc_id for item in golds for g in (item if isinstance(item, tuple) else (item,))}
    out["doc_hit@5"] = 1.0 if any(c["doc_id"] in gold_docs for c in ranked[:5]) else 0.0
    return out


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap_ci(diffs: Sequence[float], *, reps: int = 10000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(mean([diffs[rng.randrange(n)] for _ in range(n)]) for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def randomisation_p(diffs: Sequence[float], *, reps: int = 10000, seed: int = 11) -> float:
    """Two-sided paired sign-flip test of mean difference = 0."""
    rng = random.Random(seed)
    obs = abs(mean(diffs))
    hits = 0
    for _ in range(reps):
        m = abs(mean([d if rng.random() < 0.5 else -d for d in diffs]))
        hits += m >= obs - 1e-12
    return (hits + 1) / (reps + 1)


def holm(ps: dict[str, float]) -> dict[str, float]:
    order = sorted(ps, key=ps.get)
    m, out, running = len(order), {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * ps[k]))
        out[k] = running
    return out


def compare(a: Sequence[float], b: Sequence[float]) -> dict:
    """Paired comparison of b against a (b - a)."""
    d = [y - x for x, y in zip(a, b, strict=True)]
    lo, hi = bootstrap_ci(d)
    return {"diff": mean(d), "ci": [lo, hi], "p": randomisation_p(d)}


Ranker = Callable[[str], list[dict]]
