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
    # The service loads the atlas's index too when it is built (D-038); these tests use the Econ fixture alone.
    monkeypatch.setenv("ECON_ATLAS_INDEX_DIR", str(tmp_path / "no-atlas-index"))
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


# --- the evidence atlas as a second knowledge base (D-038) ------------------------------------------------------

ATLAS_BASE = "https://example.org/evidence/"


def _atlas_passage(pid, kind, section, text, **kw):
    doc = pid.rsplit(":", 1)[0]
    row = {
        "passage_id": pid,
        "doc_id": doc,
        "kind": kind,
        "observation": None,
        "stage": None,
        "lens": None,
        "lens_name": None,
        "strength": None,
        "chapter": None,
        "title": kw.pop("title", doc),
        "section": section,
        "url": ATLAS_BASE + "#/" + kw.pop("route", doc[len("atlas-") :]),
        "related": kw.pop("related", []),
        "text": text,
    }
    row.update(kw)
    return row


def _obs(pid, oid, stage, strength, section, text, **kw):
    return _atlas_passage(
        pid,
        "observation",
        section,
        text,
        observation=oid,
        stage=stage,
        strength=strength,
        lens="rights",
        lens_name="IP rights",
        chapter="1.2 Lorem section",
        title=f"{oid}: Lorem headline about filing alone",
        route=oid,
        **kw,
    )


ATLAS_PASSAGES = [
    _obs(
        "atlas-B6:0000",
        "B6",
        "2",
        "observational",
        ["Observation B6 (observational)"],
        "Lorem filings made alone were granted 35.8 points less often than with an attorney, ipsum dolor.",
    ),
    _obs(
        "atlas-B6:0001",
        "B6",
        "2",
        "observational",
        ["Key figures"],
        "| Figure | What it is |\n| --- | --- |\n| 35.8 points | the raw gap |\n| 1,149 | applications filed alone |",
    ),
    _obs(
        "atlas-B6:0002",
        "B6",
        "2",
        "observational",
        ["Assumptions and limits"],
        "Sit amet the data do not say why, consectetur adipiscing elit.",
    ),
    _obs(
        "atlas-M1:0000",
        "M1",
        "3",
        "observational",
        ["How this follows from the earlier stages"],
        "Sed do eiusmod tempor: B6 found a gap; Stage 3 held the route and year together.",
    ),
    _obs(
        "atlas-M1:0001",
        "M1",
        "3",
        "observational",
        ["Observation M1 (observational)"],
        "Lorem with the factors held together, 31.2 points of the gap remain (87.2%), magna aliqua.",
    ),
    _obs(
        "atlas-M1:0002",
        "M1",
        "3",
        "observational",
        ["Key figures"],
        "| Figure | What it is |\n| --- | --- |\n| −31.2 points | the gap held together |\n| 41.39% | a share |",
    ),
    _obs(
        "atlas-M1:0003",
        "M1",
        "3",
        "observational",
        ["For analysts: the notebook's own words"],
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.",
    ),
    _atlas_passage(
        "atlas-glossary-median:0000",
        "glossary",
        ["Glossary", "Median"],
        "**Median.** The middle value: half lie below it and half above, lorem ipsum.",
        title="Glossary: Median",
        route="glossary/median",
    ),
    _atlas_passage(
        "atlas-page-limits:0000",
        "page",
        ["What the three stages cannot tell you"],
        "- **Why.** Duis aute irure dolor: an association is not a cause, in reprehenderit.",
        title="Limits and assumptions",
        route="limits",
        related=["M1"],
    ),
]


def atlas_source(tmp_path, passages=None, *, meta_overrides=None):
    """A checkout of the atlas holding `passages` (the fixture by default) and their metadata."""
    import hashlib

    root = tmp_path / "atlas-checkout"
    data = root / "evidence" / "data"
    data.mkdir(parents=True, exist_ok=True)
    rows = ATLAS_PASSAGES if passages is None else passages
    body = "".join(
        json.dumps(dict(sorted(p.items())), ensure_ascii=False, separators=(",", ":")) + "\n" for p in rows
    )
    (data / "passages.jsonl").write_text(body, encoding="utf-8")
    meta = {
        "version": "atlas-passages-v1",
        "built": "2026-11-04",
        "atlas_sha256": "a" * 64,
        "passages_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "passages": len(rows),
        "base": ATLAS_BASE,
        **(meta_overrides or {}),
    }
    (data / "passages.meta.json").write_text(json.dumps(meta))
    return root


@pytest.fixture
def atlas_index_dir(index_dir, tmp_path, monkeypatch):
    """The atlas fixture as a built index (BM25 over note and text, fake vectors), as `econ index --kb atlas`
    writes it."""
    from econ.ingest import atlas

    ps = [atlas.Passage.model_validate(p) for p in ATLAS_PASSAGES]
    chunks = [atlas.to_chunk(p, i, len(p.text.split()), atlas.note(p)) for i, p in enumerate(ps)]
    d = tmp_path / "atlas-index"
    d.mkdir()
    (d / "chunks.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks))
    np.save(d / "vectors.f16.npy", np.stack([_vec(i) for i in range(len(chunks))]).astype(np.float16))
    texts = [(c["context_note"] + "\n\n" + c["embed_text"]).strip() for c in chunks]
    BM25.build(texts).save(d / "bm25.npz")
    by_doc: dict = {}
    for p in ps:
        by_doc.setdefault(p.doc_id, []).append(p)
    (d / "docs.json").write_text(json.dumps({k: atlas.doc_entry(k, v, 2026) for k, v in by_doc.items()}))
    (d / "index.json").write_text(
        json.dumps(
            {
                "kb": "atlas",
                "strategy": "atlas-passages-v1",
                "embedder": "fake",
                "revision": "r",
                "dim": 8,
                "chunks": len(chunks),
                "built_from": "test",
                "onnx_sha256": "x",
                "atlas_ref": "b" * 40,
                "atlas_sha256": "a" * 64,
                "atlas_passages_sha256": "c" * 64,
                "atlas_built": "2026-11-04",
            }
        )
    )
    monkeypatch.setenv("ECON_ATLAS_INDEX_DIR", str(d))
    return d
