"""The serving index (library/index/) and multi-query search over it.

Files, written by `econ index` and committed:
- chunks.jsonl: the adopted strategy's chunks (text, section, pages, boxes, spans);
- vectors.f16.npy: their embeddings from the adopted model's ONNX path, float16, row-aligned;
- bm25.npz and bm25.vocab.json: the keyword index over each chunk's embed_text;
- docs.json: the catalogue (title, year, series, licence, page sizes, chunk counts);
- index.json: the build identity (strategy, model, revision, ONNX hash, file hashes).

A question may become several queries (the plan). Each query is ranked by `fuse`; the per-query lists
are merged by reciprocal rank, and the context takes the top `context_chunks` with at most `per_doc_cap`
from any one document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from econ import config
from econ.kb.bm25 import BM25
from econ.retrieval.search import fuse

INDEX_DIR = "library/index"


@dataclass
class Selected:
    row: int
    merged_score: float
    merged_rank: int
    per_query: dict = field(default_factory=dict)  # query index -> {rank, score, dense, bm25, ...}


class Index:
    def __init__(self, root: Path | None = None):
        import os

        root = root or Path(os.environ.get("ECON_INDEX_DIR") or config.path(INDEX_DIR))
        self.root = root
        self.meta = json.loads((root / "index.json").read_text())
        self.docs = json.loads((root / "docs.json").read_text())
        self.chunks = [
            json.loads(line)
            for line in (root / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        self.vecs = np.load(root / "vectors.f16.npy").astype(np.float32)
        self.bm25 = BM25.load(root / "bm25.npz")
        self.by_id = {c["chunk_id"]: i for i, c in enumerate(self.chunks)}
        if len(self.chunks) != self.vecs.shape[0] or len(self.chunks) != self.bm25.n:
            raise RuntimeError("index files are not row-aligned; rebuild with `econ index`")
        self.doc_of = np.array([c["doc_id"] for c in self.chunks])
        self.year_of = np.array([self.docs[c["doc_id"]]["year"] for c in self.chunks])

    def allowed(
        self, doc_ids: list[str] | None = None, years: tuple[int, int] | None = None
    ) -> np.ndarray | None:
        if not doc_ids and not years:
            return None
        mask = np.ones(len(self.chunks), dtype=bool)
        if doc_ids:
            mask &= np.isin(self.doc_of, doc_ids)
        if years:
            mask &= (self.year_of >= years[0]) & (self.year_of <= years[1])
        return mask

    def search(
        self,
        queries: list[str],
        qvecs: np.ndarray | None,
        *,
        allowed: np.ndarray | None = None,
        depth: int = 50,
    ) -> tuple[list[Selected], list[dict]]:
        """Rank for every query, then merge. Returns the merged list and a trace per query."""
        r = config.pipeline().retrieval
        traces, merged = [], {}
        for qi, q in enumerate(queries):
            dense = self.vecs @ qvecs[qi] if qvecs is not None else None
            bm = self.bm25.scores(q)
            hits = fuse(
                dense,
                bm,
                k=depth,
                lane_depth=r.lane_depth,
                fusion=r.fusion,
                alpha=r.alpha,
                rrf_k=r.rrf_k,
                allowed=allowed,
            )
            traces.append(
                {
                    "query": q,
                    "lanes": ["dense", "bm25"] if dense is not None else ["bm25"],
                    "hits": [h.as_dict() for h in hits[:20]],
                }
            )
            for h in hits:
                s = merged.setdefault(h.row, Selected(h.row, 0.0, 0))
                s.merged_score += 1.0 / (r.rrf_k + h.rank) if len(queries) > 1 else h.score
                s.per_query[qi] = {
                    "rank": h.rank,
                    "score": h.score,
                    "dense": h.dense,
                    "dense_rank": h.dense_rank,
                    "bm25": h.bm25,
                    "bm25_rank": h.bm25_rank,
                }
        ranked = sorted(merged.values(), key=lambda s: (-s.merged_score, s.row))
        for i, s in enumerate(ranked):
            s.merged_rank = i + 1
            s.merged_score = round(s.merged_score, 6)
        return ranked, traces

    def context(self, ranked: list[Selected]) -> list[Selected]:
        r = config.pipeline().retrieval
        out, per_doc = [], {}
        for s in ranked:
            d = self.chunks[s.row]["doc_id"]
            if per_doc.get(d, 0) >= r.per_doc_cap:
                continue
            per_doc[d] = per_doc.get(d, 0) + 1
            out.append(s)
            if len(out) == r.context_chunks:
                break
        return out


class EmbedderClient:
    """Calls the Cloud Run embedder. The first call after a scale-to-zero gets the cold-start timeout."""

    def __init__(self):
        cfg = config.service().embedder
        import os

        self.url = os.environ.get(cfg.url_env, "").rstrip("/")
        self.token = os.environ.get(cfg.token_env, "")
        self.cfg = cfg
        self.last_ok = 0.0
        self.health: dict | None = None

    # Cloud Run scales to zero after some idle minutes, so warmth expires: after a quiet spell the next
    # call gets the cold-start timeout instead of failing over to keywords.
    WARM_FOR = 600

    @property
    def warm(self) -> bool:
        import time

        return time.time() - self.last_ok < self.WARM_FOR

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def ping(self) -> dict | None:
        import time

        import httpx

        if not self.url:
            return None
        try:
            r = httpx.get(
                f"{self.url}/health", headers=self._headers(), timeout=self.cfg.cold_timeout_seconds
            )
            r.raise_for_status()
            self.health = r.json()
            self.last_ok = time.time()
        except httpx.HTTPError as e:
            self.health = {"status": "unavailable", "error": type(e).__name__}
        return self.health

    def embed(self, texts: list[str], expect_model: str, expect_dim: int) -> np.ndarray:
        import httpx

        from econ.embedder import decode

        timeout = self.cfg.timeout_seconds if self.warm else self.cfg.cold_timeout_seconds
        r = httpx.post(
            f"{self.url}/embed",
            json={"texts": texts, "kind": "query"},
            headers=self._headers(),
            timeout=timeout,
        )
        r.raise_for_status()
        d = r.json()
        if d["model"] != expect_model or d["dim"] != expect_dim:
            raise RuntimeError(
                f"embedder serves {d['model']}/{d['dim']}, index expects {expect_model}/{expect_dim}"
            )
        import time

        self.last_ok = time.time()
        return decode(d["vectors_b64"])
