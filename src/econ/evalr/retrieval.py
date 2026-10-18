"""Retrieval measurement: run a grid fixed in eval/grids/ before any number existed, then report.

Each cell is (chunking strategy, embedder, lane). Per-need metrics go to eval/runs/<grid>/<stage>/,
and reports/retrieval-<stage>.md applies the grid's choice rule on dev and reports test.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml

from econ import config
from econ.evalr import metrics
from econ.evalr.testset import Need
from econ.kb import embed
from econ.kb.bm25 import BM25
from econ.manifest import StageError, write_text_atomic
from econ.retrieval.search import fuse

DEPTH = 50  # ranked chunks kept per need: enough for the 8k-token budget at the smallest chunk size


def load_chunks(strategy: str) -> list[dict]:
    p = config.path(config.pipeline().paths.library) / "chunks" / f"{strategy}.jsonl"
    if not p.exists():
        raise StageError(f"no chunks for {strategy}; run `econ chunk`", item=strategy)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def lane_settings(name: str) -> dict:
    """'hybrid' = the configured default; 'dense', 'bm25', 'score-0.5', 'rrf' are named variants."""
    r = config.pipeline().retrieval
    if name == "hybrid":
        return {"use_dense": True, "use_bm25": True, "fusion": r.fusion, "alpha": r.alpha}
    if name == "dense":
        return {"use_dense": True, "use_bm25": False, "fusion": "score", "alpha": 1.0}
    if name == "bm25":
        return {"use_dense": False, "use_bm25": True, "fusion": "score", "alpha": 0.0}
    if name == "rrf":
        return {"use_dense": True, "use_bm25": True, "fusion": "rrf", "alpha": r.alpha}
    if name.startswith("score-"):
        return {"use_dense": True, "use_bm25": True, "fusion": "score", "alpha": float(name.split("-", 1)[1])}
    raise ValueError(name)


class Cell:
    """Everything needed to rank one strategy with one embedder; lanes share the work."""

    def __init__(self, strategy: str, embedder: str | None):
        self.strategy, self.embedder = strategy, embedder
        self.chunks = load_chunks(strategy)
        self.bm25 = BM25.build([c["embed_text"] for c in self.chunks])
        self.vecs = (
            embed.encode(embedder, [c["embed_text"] for c in self.chunks], kind="doc") if embedder else None
        )

    def rank(self, needs: list[Need], lane: str) -> dict[str, list[int]]:
        s = lane_settings(lane)
        r = config.pipeline().retrieval
        qv = (
            embed.encode(self.embedder, [n.question for n in needs], kind="query")
            if s["use_dense"] and self.embedder
            else None
        )
        out = {}
        for i, n in enumerate(needs):
            dense = self.vecs @ qv[i] if qv is not None else None
            bm = self.bm25.scores(n.question) if s["use_bm25"] else None
            hits = fuse(
                dense,
                bm,
                k=DEPTH,
                lane_depth=r.lane_depth,
                fusion=s["fusion"],
                alpha=s["alpha"],
                rrf_k=r.rrf_k,
            )
            out[n.id] = [h.row for h in hits]
        return out

    def score(self, needs: list[Need], lane: str) -> list[dict]:
        ranks = self.rank(needs, lane)
        rows = []
        for n in needs:
            ranked = [self.chunks[i] for i in ranks[n.id]]
            m = metrics.per_need(ranked, n.golds)
            rows.append(
                {
                    "need": n.id,
                    "split": n.split,
                    "kind": n.kind,
                    **m,
                    "top": [c["chunk_id"] for c in ranked[:10]],
                }
            )
        return rows


def run_dir(grid: str, stage: str) -> Path:
    return config.path("eval/runs") / grid / stage


def save(grid: str, stage: str, name: str, rows: list[dict]) -> Path:
    p = run_dir(grid, stage) / f"{name}.jsonl"
    write_text_atomic(p, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    return p


def load_rows(grid: str, stage: str, name: str) -> list[dict]:
    p = run_dir(grid, stage) / f"{name}.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def summarise(rows: list[dict], split: str, metric: str) -> float:
    return metrics.mean([r[metric] for r in rows if r["split"] == split])


def grid_spec(grid: str) -> dict:
    return yaml.safe_load(config.path(f"eval/grids/{grid}.yaml").read_text())


def vec_stats(cell: Cell) -> dict:
    if cell.vecs is None:
        return {}
    norms = np.linalg.norm(cell.vecs, axis=1)
    return {"dim": int(cell.vecs.shape[1]), "norm_min": float(norms.min()), "norm_max": float(norms.max())}
