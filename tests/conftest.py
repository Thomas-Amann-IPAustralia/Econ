"""Fixtures: a whitespace tokenizer in place of the Hugging Face one, and a tiny index of placeholder text.

CI has no network and no models, so nothing here downloads. Fixture text is placeholder prose, never
source text.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import numpy as np
import pytest

from econ.kb import tokens
from econ.kb.bm25 import BM25


class WhitespaceTokenizer:
    def encode(self, text, add_special_tokens=False):
        spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        return SimpleNamespace(ids=list(range(len(spans))), offsets=spans)


@pytest.fixture(autouse=True)
def fake_tokenizer(monkeypatch):
    tok = WhitespaceTokenizer()
    monkeypatch.setattr(tokens, "reference", lambda: tok)
    monkeypatch.setattr(tokens, "count", lambda text: len(text.split()) + 2)
    return tok


DOCS = {
    "doc-a": {"title": "Alpha Report 2020", "year": 2020, "series": "Test series"},
    "doc-b": {"title": "Beta Paper 2024", "year": 2024, "series": "Test series"},
}

CHUNKS = [
    (
        "doc-a",
        ["Patents"],
        "Lorem patent filings rose sharply among small firms in the alpha period, ipsum dolor.",
    ),
    (
        "doc-a",
        ["Patents"],
        "Sit amet examination pendency fell after the reform, consectetur adipiscing elit.",
    ),
    (
        "doc-a",
        ["Trade marks"],
        "Trade mark applications track the business cycle closely, sed do eiusmod tempor.",
    ),
    ("doc-b", ["Designs"], "Design rights protect the visual appearance of products, ut labore et dolore."),
    ("doc-b", ["Designs"], "Magna aliqua design registrations grew among manufacturers, ut enim ad minim."),
    (
        "doc-b",
        ["Copyright"],
        "Copyright arises automatically and needs no registration, quis nostrud exercitation.",
    ),
]


def _vec(i: int, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i % dim] = 1.0
    v[(i + 1) % dim] = 0.3
    return v / np.linalg.norm(v)


@pytest.fixture
def index_dir(tmp_path, monkeypatch):
    rows = []
    for i, (doc, section, text) in enumerate(CHUNKS):
        rows.append(
            {
                "chunk_id": f"{doc}:{i:04d}",
                "doc_id": doc,
                "seq": i,
                "text": text,
                "embed_text": f"{DOCS[doc]['title']}\n{' > '.join(section)}\n\n{text}",
                "section": section,
                "headings": [],
                "pages": [i + 1],
                "boxes": [{"page": i + 1, "bbox": [10, 10, 100, 40]}],
                "spans": [[0, len(text)]],
                "elements": [i, i],
                "labels": ["text"],
                "tokens": len(text.split()),
            }
        )
    d = tmp_path / "index"
    d.mkdir()
    (d / "chunks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    np.save(d / "vectors.f16.npy", np.stack([_vec(i) for i in range(len(rows))]).astype(np.float16))
    BM25.build([r["embed_text"] for r in rows]).save(d / "bm25.npz")
    docs = {
        k: {
            **v,
            "doc_id": k,
            "authors": [],
            "url": None,
            "publisher": "Test",
            "licence": "CC BY 4.0",
            "page_count": 9,
            "pages": {},
            "ocr": False,
            "chunks": 3,
            "source_sha256": "x",
        }
        for k, v in DOCS.items()
    }
    (d / "docs.json").write_text(json.dumps(docs))
    (d / "index.json").write_text(
        json.dumps(
            {
                "strategy": "S384",
                "embedder": "fake",
                "revision": "r",
                "dim": 8,
                "chunks": len(rows),
                "built_from": "test",
                "onnx_sha256": "x",
            }
        )
    )
    monkeypatch.setenv("ECON_INDEX_DIR", str(d))
    return d


class FakeEmbedder:
    """Embeds a query as the vector of the fixture chunk whose words it shares most."""

    def __init__(self, fail: bool = False):
        self.configured, self.warm, self.health, self.fail = True, True, {"status": "fake"}, fail
        self.calls = 0

    def embed(self, texts, expect_model, expect_dim):
        self.calls += 1
        if self.fail:
            raise TimeoutError("cold")
        out = []
        for t in texts:
            words = set(t.lower().split())
            best = max(range(len(CHUNKS)), key=lambda i: len(words & set(CHUNKS[i][2].lower().split())))
            out.append(_vec(best))
        return np.stack(out)

    def ping(self):
        return self.health
