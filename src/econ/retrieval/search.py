"""Hybrid search: a dense lane and a BM25 lane, fused. Shared by the measurement and the service.

Score fusion min-max normalises each lane over its own top `lane_depth` results (anything outside a
lane's top list scores 0 in that lane) and takes alpha * dense + (1 - alpha) * bm25. RRF is the
alternative. Every hit keeps both lanes' raw scores and ranks, so the trace can show why it ranked.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class Hit:
    row: int
    score: float
    rank: int
    dense: float | None = None
    dense_rank: int | None = None
    bm25: float | None = None
    bm25_rank: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def top(scores: np.ndarray, k: int, allowed: np.ndarray | None = None) -> np.ndarray:
    s = scores if allowed is None else np.where(allowed, scores, -np.inf)
    k = min(k, int(np.isfinite(s).sum()) if allowed is not None else len(s))
    if k <= 0:
        return np.zeros(0, dtype=np.int64)
    idx = np.argpartition(-s, k - 1)[:k]
    # Stable order: score descending, then row ascending, so ties never reorder between runs.
    return idx[np.lexsort((idx, -s[idx]))]


def _minmax(vals: np.ndarray) -> np.ndarray:
    lo, hi = float(vals.min()), float(vals.max())
    if hi - lo < 1e-12:
        return np.ones_like(vals)
    return (vals - lo) / (hi - lo)


def fuse(
    dense: np.ndarray | None,
    bm25: np.ndarray | None,
    *,
    k: int,
    lane_depth: int = 100,
    fusion: str = "score",
    alpha: float = 0.7,
    rrf_k: int = 60,
    allowed: np.ndarray | None = None,
) -> list[Hit]:
    """Rank rows by one or both lanes. `allowed` filters rows before ranking; it never changes scores."""
    lanes = {}
    if dense is not None:
        lanes["dense"] = (dense, top(dense, lane_depth, allowed))
    if bm25 is not None:
        b_top = top(bm25, lane_depth, allowed)
        b_top = b_top[bm25[b_top] > 0]  # a chunk with none of the query's terms isn't a keyword match
        lanes["bm25"] = (bm25, b_top)
    hits: dict[int, Hit] = {}
    contrib: dict[int, float] = {}
    for name, (scores, order) in lanes.items():
        if len(order) == 0:
            continue
        norm = _minmax(scores[order]) if fusion == "score" else None
        weight = (alpha if name == "dense" else 1 - alpha) if len(lanes) == 2 else 1.0
        for r, row in enumerate(order):
            h = hits.setdefault(int(row), Hit(row=int(row), score=0.0, rank=0))
            setattr(h, name, float(scores[row]))
            setattr(h, f"{name}_rank", r + 1)
            add = weight * float(norm[r]) if fusion == "score" else 1.0 / (rrf_k + r + 1)
            contrib[int(row)] = contrib.get(int(row), 0.0) + add
    ranked = sorted(hits.values(), key=lambda h: (-contrib[h.row], h.row))[:k]
    for i, h in enumerate(ranked):
        h.score = round(contrib[h.row], 6)
        h.rank = i + 1
    return ranked
