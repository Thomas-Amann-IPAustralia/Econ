"""The reranker in the service path (D-012): the pipeline reorders the first stage's top candidates by the
cross-encoder's scores, a failed reranker keeps the first-stage order visibly, and the Cloud Run app serves
/rerank behind its token. No model files: the reranker is a fake."""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from econ import config, embedder
from econ.answer import pipeline
from econ.reranker import read_safetensors
from econ.retrieval.index import Index
from tests.conftest import FakeEmbedder


class RerankingEmbedder(FakeEmbedder):
    """Scores a passage by whether it mentions 'copyright'; records what it was asked."""

    def __init__(self, fail: bool = False):
        super().__init__()
        self.rr_fail, self.asked = fail, []

    def rerank(self, query, passages, expect_model):
        self.asked.append((query, len(passages), expect_model))
        if self.rr_fail:
            raise TimeoutError("cold")
        return np.array([1.0 if "copyright" in p.lower() else 0.0 for p in passages], dtype=np.float32)


@pytest.fixture
def adopted(monkeypatch):
    rc = config.pipeline().reranking.model_copy(update={"adopted": "ettin-17m", "depth": 50})
    monkeypatch.setattr(
        config,
        "pipeline",
        lambda: config.Pipeline.model_validate(
            {**config._load_yaml("pipeline.yaml"), "reranking": rc.model_dump()}
        ),
    )
    return rc


def test_the_reranker_reorders_the_first_stage(index_dir, adopted):
    emb = RerankingEmbedder()
    svc = pipeline.Services(index=Index(), embedder=emb)
    ev = {e["event"]: e for e in pipeline.run(pipeline.Request(question="patent filings small firms"), svc)}
    r = ev["retrieval"]
    assert r["rerank"]["status"] == "ok" and r["rerank"]["model"] == "ettin-17m"
    assert "copyright" in r["evidence"][0]["text"].lower() and r["evidence"][0]["rerank_score"] == 1.0
    # The reranker saw the question as asked, and the first-stage rank is still on the record.
    assert emb.asked[0][0] == "patent filings small firms" and r["evidence"][0]["merged_rank"] > 1


def test_a_failed_reranker_keeps_the_first_stage_order_visibly(index_dir, adopted):
    svc = pipeline.Services(index=Index(), embedder=RerankingEmbedder(fail=True))
    ev = {e["event"]: e for e in pipeline.run(pipeline.Request(question="patent filings small firms"), svc)}
    r = ev["retrieval"]
    assert r["rerank"]["status"].startswith("unavailable")
    assert r["evidence"][0]["chunk_id"] == "doc-a:0000" and r["evidence"][0]["rerank_score"] is None


def test_without_an_adopted_reranker_nothing_changes(index_dir):
    emb = RerankingEmbedder()
    svc = pipeline.Services(index=Index(), embedder=emb)
    ev = {e["event"]: e for e in pipeline.run(pipeline.Request(question="patent filings small firms"), svc)}
    assert ev["retrieval"]["rerank"]["status"] == "off" and not emb.asked


def test_pasted_headings_reach_the_reranker():
    assert (
        pipeline.rerank_query("Does it agree?", "## GII rank\nx\n## Clusters")
        == "Does it agree? GII rank Clusters"
    )


class FakeReranker:
    def __init__(self, key, model_dir, **kw):
        self.key, self.meta = key, {"revision": "r2", "onnx_sha256": "def"}

    def score(self, query, passages):
        return np.arange(len(passages), dtype=np.float32)


def test_the_service_serves_rerank_behind_its_token(tmp_path, monkeypatch):
    import econ.reranker

    (tmp_path / "e").mkdir()
    (tmp_path / "r").mkdir()
    (tmp_path / "e" / "model.json").write_text(json.dumps({"key": "bge-small"}))
    (tmp_path / "r" / "model.json").write_text(json.dumps({"key": "ettin-17m"}))
    monkeypatch.setenv("ECON_EMBEDDER_DIR", str(tmp_path / "e"))
    monkeypatch.setenv("ECON_RERANKER_DIR", str(tmp_path / "r"))
    monkeypatch.setenv("EMBEDDER_TOKEN", "t0ken")
    monkeypatch.setattr(econ.reranker, "OnnxReranker", FakeReranker)
    c = TestClient(embedder.create_app())
    body = {"query": "q", "passages": ["a", "b", "c"]}
    assert c.post("/rerank", json=body).status_code == 401
    r = c.post("/rerank", json=body, headers={"Authorization": "Bearer t0ken"})
    assert r.status_code == 200 and r.json()["scores"] == [0.0, 1.0, 2.0] and r.json()["model"] == "ettin-17m"
    auth = {"Authorization": "Bearer t0ken"}
    assert c.post("/rerank", json={"query": "q", "passages": ["x" * 5000]}, headers=auth).status_code == 413
    assert c.post("/rerank", json={"query": "q", "passages": ["p"] * 65}, headers=auth).status_code == 422


def test_an_image_without_a_reranker_says_so(tmp_path, monkeypatch):
    (tmp_path / "model.json").write_text(json.dumps({"key": "bge-small"}))
    monkeypatch.setenv("ECON_EMBEDDER_DIR", str(tmp_path))
    monkeypatch.setenv("ECON_RERANKER_DIR", str(tmp_path / "none"))
    monkeypatch.delenv("EMBEDDER_TOKEN", raising=False)
    c = TestClient(embedder.create_app())
    assert c.post("/rerank", json={"query": "q", "passages": ["a"]}).status_code == 404


def test_safetensors_are_read_without_the_library(tmp_path):
    import struct

    w = np.arange(6, dtype=np.float32).reshape(2, 3)
    header = json.dumps(
        {"linear.weight": {"dtype": "F32", "shape": [2, 3], "data_offsets": [0, 24]}}
    ).encode()
    (tmp_path / "m.safetensors").write_bytes(struct.pack("<Q", len(header)) + header + w.tobytes())
    assert np.array_equal(read_safetensors(tmp_path / "m.safetensors")["linear.weight"], w)
