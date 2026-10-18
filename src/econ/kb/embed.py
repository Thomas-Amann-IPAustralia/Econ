"""Embedding for measurement and for building the index, with sentence-transformers at pinned revisions.

The service never imports this: queries are embedded by the Cloud Run embedder (econ.embedder), whose
ONNX path is verified against these vectors before adoption (`econ verify-embedder`).
Vectors are cached per (model, revision, text set) under data/cache, since base and large models take
minutes per pass on a CPU.
"""

from __future__ import annotations

import hashlib
import time
from functools import lru_cache

import numpy as np

from econ import config
from econ.config import Embedder


def text_digest(texts: list[str]) -> str:
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode())
        h.update(b"\x00")
    return h.hexdigest()[:16]


@lru_cache(maxsize=2)
def load(key: str):
    import torch
    from sentence_transformers import SentenceTransformer

    e = config.pipeline().embedding.candidates[key]
    torch.set_num_threads(4)
    m = SentenceTransformer(
        e.hf_id,
        revision=e.revision,
        trust_remote_code=False,
        device="cpu",
        cache_folder=str(config.path(config.pipeline().paths.models)),
    )
    m.max_seq_length = min(e.max_tokens, 1024)
    return m


def encode(key: str, texts: list[str], *, kind: str, cache: bool = True) -> np.ndarray:
    """L2-normalised float32 vectors. kind is 'query' or 'doc', which picks the model's prefix."""
    e: Embedder = config.pipeline().embedding.candidates[key]
    pfx = e.query_prefix if kind == "query" else e.doc_prefix
    inputs = [pfx + t for t in texts]
    path = None
    if cache:
        d = config.path("data/cache/embeddings")
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{key}.{e.revision[:12]}.{kind}.{text_digest(inputs)}.npy"
        if path.exists():
            return np.load(path)
    m = load(key)
    started = time.time()
    # Longest first keeps padding low; restore the order after.
    order = sorted(range(len(inputs)), key=lambda i: -len(inputs[i]))
    vecs = m.encode(
        [inputs[i] for i in order],
        batch_size=config.pipeline().embedding.batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)
    out = np.empty_like(vecs)
    out[order] = vecs
    if path is not None:
        np.save(path, out)
        path.with_suffix(".seconds").write_text(f"{time.time() - started:.1f}\n")
    return out
