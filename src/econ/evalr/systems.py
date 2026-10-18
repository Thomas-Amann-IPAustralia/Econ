"""Candidate retrieval systems for the judged test set (judged-v1), all free to run.

A system is (query form, index text, first stage, reranker). Every system ranks the same chunks (the
adopted chunking), so one pool of judgments scores them all.

- Query forms: `raw` is the question (plus pasted headings, as the service does without a planner);
  `plan:<name>` is a cached plan's queries; `plan+q:<name>` adds the standalone question to them.
- Index text: `plain` is each chunk's embed_text; `enriched:<name>` puts its context note
  (library/enrich/<name>.jsonl) in front, for BM25 and the dense lane alike.
- First stage: hybrid score fusion per query (alpha, depth), merged across queries by reciprocal rank,
  exactly as `econ.retrieval.index.Index.search` does; `dense` and `bm25` lanes alone are also possible.
- Reranker: a cross-encoder scores (question, passage) for the first stage's top `rr_depth`, and the
  scores alone order them. Scores are cached in eval/cache/rerank/<key>.jsonl.

The context the answer model sees is the top `context` rows with at most `cap` per document.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from econ import config
from econ.answer.pipeline import context_queries
from econ.evalr import plans as plans_mod
from econ.evalr.judged import Need
from econ.evalr.retrieval import load_chunks
from econ.kb import embed
from econ.kb.bm25 import BM25
from econ.retrieval.search import fuse

STRATEGY = "S384-noprefix-nocite"

# Repository and the revision the measurement loaded (the main branch on 2026-10-18).
RERANKERS = {
    "minilm-l6": "cross-encoder/ms-marco-MiniLM-L6-v2",
    "ettin-17m": "cross-encoder/ettin-reranker-17m-v1",
    "ettin-32m": "cross-encoder/ettin-reranker-32m-v1",
    "ettin-68m": "cross-encoder/ettin-reranker-68m-v1",
    "ettin-150m": "cross-encoder/ettin-reranker-150m-v1",
    "gte-mb": "Alibaba-NLP/gte-reranker-modernbert-base",
}
REVISIONS = {
    "minilm-l6": "233902d25c440f23af6f7d6e94d2946bac0bee0a",
    "ettin-17m": "9e4aa35321a6dd1a43ca313f500c4b4f7cfb5cc6",
    "ettin-32m": "b33e5ceb5110773ea9cf5e00c9bedc83a8c2afdd",
    "ettin-68m": "d166fa88ddde3c42bc3ee92f7df476d941c8204a",
    "ettin-150m": "025501c4e0f9bbeb4c5b198318e0089ff061cc14",
    "gte-mb": "f7481e6055501a30fb19d090657df9ec1f79ab2c",
}


@dataclass(frozen=True)
class System:
    name: str
    query: str = "raw"  # raw | plan:<name> | plan+q:<name>
    text: str = "plain"  # plain | enriched:<name>
    lane: str = "hybrid"  # hybrid | dense | bm25
    embedder: str = "arctic-m-v1.5"
    alpha: float = 0.7
    depth: int = 50  # per-query depth before the merge, as in the service
    reranker: str | None = None
    rr_depth: int = 50
    rr_input: str = "text"  # text | titled (document, year and section before the text)
    context: int = 20
    cap: int = 8


@lru_cache
def chunks() -> list[dict]:
    return load_chunks(STRATEGY)


@lru_cache
def index_texts(text: str) -> tuple[str, ...]:
    cs = chunks()
    if text == "plain":
        return tuple(c["embed_text"] for c in cs)
    if text.startswith("enriched:"):
        from econ.kb import enrich

        notes = enrich.load(text.split(":", 1)[1])
        return tuple((notes.get(c["chunk_id"], "") + "\n\n" + c["embed_text"]).strip() for c in cs)
    raise ValueError(text)


@lru_cache
def bm25(text: str) -> BM25:
    return BM25.build(list(index_texts(text)))


@lru_cache
def doc_vecs(embedder: str, text: str) -> np.ndarray:
    return embed.encode(embedder, list(index_texts(text)), kind="doc")


_qcache: dict[tuple[str, str], np.ndarray] = {}


def query_vecs(embedder: str, queries: list[str]) -> np.ndarray:
    missing = [q for q in dict.fromkeys(queries) if (embedder, q) not in _qcache]
    if missing:
        for q, v in zip(missing, embed.encode(embedder, missing, kind="query"), strict=True):
            _qcache[(embedder, q)] = v
    return np.stack([_qcache[(embedder, q)] for q in queries])


def queries_for(need: Need, form: str) -> tuple[str, list[str]]:
    """(the question to rerank against, the search queries)."""
    k = config.service().answer.max_queries
    if form == "raw":
        return need.question, [need.question, *context_queries(need.context, k - 1)]
    kind, name = form.split(":", 1)
    p = plans_mod.load(name)[need.id]
    if kind == "plan":
        return p["standalone"], list(p["queries"])
    if kind == "plan+q":
        qs = [p["standalone"], *[q for q in p["queries"] if q != p["standalone"]]]
        return p["standalone"], qs
    raise ValueError(form)


def prewarm(systems: list[System], needs: list[Need]) -> None:
    """Embed every query the systems will need in one pass per embedder."""
    for emb in {s.embedder for s in systems if s.lane != "bm25"}:
        qs = [q for s in systems if s.embedder == emb for n in needs for q in queries_for(n, s.query)[1]]
        query_vecs(emb, list(dict.fromkeys(qs)))


def first_stage(s: System, queries: list[str]) -> list[tuple[int, float]]:
    """Rows and merged scores, best first; the service's merge (RRF across queries, k=60)."""
    r = config.pipeline().retrieval
    use_d, use_b = s.lane in ("hybrid", "dense"), s.lane in ("hybrid", "bm25")
    qv = query_vecs(s.embedder, queries) if use_d else None
    vecs = doc_vecs(s.embedder, s.text) if use_d else None
    bm = bm25(s.text) if use_b else None
    merged: dict[int, float] = {}
    for qi, q in enumerate(queries):
        hits = fuse(
            vecs @ qv[qi] if use_d else None,
            bm.scores(q) if use_b else None,
            k=s.depth,
            lane_depth=r.lane_depth,
            fusion="score",
            alpha=s.alpha if s.lane == "hybrid" else (1.0 if use_d else 0.0),
            rrf_k=r.rrf_k,
        )
        for h in hits:
            add = 1.0 / (r.rrf_k + h.rank) if len(queries) > 1 else h.score
            merged[h.row] = merged.get(h.row, 0.0) + add
    return sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))


# --- reranking -------------------------------------------------------------------------------------


def _pair_key(q: str, p: str) -> str:
    return hashlib.sha1(f"{q}\x00{p}".encode()).hexdigest()


class RerankCache:
    def __init__(self, key: str):
        self.key = key
        self.path = config.path("eval/cache/rerank") / f"{key}.jsonl"
        self.scores: dict[str, float] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.scores[d["k"]] = d["s"]

    def missing(self, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        seen, out = set(), []
        for q, p in pairs:
            k = _pair_key(q, p)
            if k not in self.scores and k not in seen:
                seen.add(k)
                out.append((q, p))
        return out

    def add(self, pairs: list[tuple[str, str]], scores) -> None:
        with self.path.open("a") as fh:
            for (q, p), s in zip(pairs, scores, strict=True):
                k = _pair_key(q, p)
                self.scores[k] = float(s)
                fh.write(json.dumps({"k": k, "s": round(float(s), 5)}) + "\n")

    def get(self, q: str, p: str) -> float:
        return self.scores[_pair_key(q, p)]


@lru_cache(maxsize=1)
def _cross_encoder(name: str, dtype: str):
    import torch
    from sentence_transformers import CrossEncoder

    torch.set_num_threads(4)
    kw = {"torch_dtype": torch.bfloat16} if dtype == "bf16" else {}
    return CrossEncoder(
        RERANKERS[name],
        revision=REVISIONS[name],
        device="cpu",
        max_length=512,
        trust_remote_code=False,
        model_kwargs=kw,
    )


def cache_key(reranker: str, rr_input: str, dtype: str) -> str:
    return f"{reranker}.{rr_input}.{dtype}"


def passage(row: int, rr_input: str) -> str:
    c = chunks()[row]
    if rr_input == "text":
        return c["text"]
    d = config.sources().by_id()[c["doc_id"]]
    sec = " > ".join(c["section"]) if c["section"] else ""
    return f"{d.title} ({d.year}). {sec}\n{c['text']}"


def score_pairs(
    reranker: str, rr_input: str, pairs: list[tuple[str, str]], dtype: str = "bf16", log=None
) -> RerankCache:
    cache = RerankCache(cache_key(reranker, rr_input, dtype))
    todo = cache.missing(pairs)
    if todo:
        m = _cross_encoder(reranker, dtype)
        # Longest first keeps padding low.
        todo.sort(key=lambda qp: -len(qp[1]))
        step = 256
        for i in range(0, len(todo), step):
            part = todo[i : i + step]
            cache.add(part, m.predict(part, batch_size=16, show_progress_bar=False))
            if log:
                log(f"{reranker}: {min(i + step, len(todo))}/{len(todo)}")
    return cache


# --- whole systems ---------------------------------------------------------------------------------


def rerank_query(need: Need) -> str:
    """What the reranker compares passages with: the question, plus pasted material's headings when there
    is any (the question alone, "does the knowledge base agree with this?", says nothing about topic).
    The test set has no conversation history, so the question is already standalone."""
    heads = context_queries(need.context, 3)
    return " ".join([need.question, *heads]) if heads else need.question


def candidates(s: System, need: Need) -> tuple[str, list[int]]:
    _, qs = queries_for(need, s.query)
    return rerank_query(need), [row for row, _ in first_stage(s, qs)]


def rank(s: System, need: Need, rr: RerankCache | None = None) -> list[int]:
    """The system's full ranked list (up to the first stage's merged depth)."""
    rq, rows = candidates(s, need)
    if s.reranker:
        head, tail = rows[: s.rr_depth], rows[s.rr_depth :]
        assert rr is not None
        sc = {r: rr.get(rq, passage(r, s.rr_input)) for r in head}
        head = sorted(head, key=lambda r: (-sc[r], r))
        rows = head + tail
    return rows


def context(s: System, rows: list[int]) -> list[int]:
    out, per = [], {}
    cs = chunks()
    for r in rows:
        d = cs[r]["doc_id"]
        if per.get(d, 0) >= s.cap:
            continue
        per[d] = per.get(d, 0) + 1
        out.append(r)
        if len(out) == s.context:
            break
    return out
