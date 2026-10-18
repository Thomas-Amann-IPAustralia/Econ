"""The Cloud Run embedder app, with the ONNX model replaced by a fake (no model files in CI)."""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from econ import embedder


class FakeOnnx:
    def __init__(self, key, model_dir, **kw):
        self.key = key
        self.meta = {"revision": "r1", "onnx_sha256": "abc"}
        self.spec = type("S", (), {"dim": 4})()

    def encode(self, texts, kind):
        v = np.ones((len(texts), 4), dtype=np.float32) * (1 if kind == "query" else 2)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "model.json").write_text(json.dumps({"key": "bge-small"}))
    monkeypatch.setenv("ECON_EMBEDDER_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDER_TOKEN", "t0ken")
    monkeypatch.setattr(embedder, "OnnxEmbedder", FakeOnnx)
    return TestClient(embedder.create_app())


def test_embed_requires_the_token_and_returns_decodable_vectors(client):
    body = {"texts": ["a question", "another"], "kind": "query"}
    assert client.post("/embed", json=body).status_code == 401
    r = client.post("/embed", json=body, headers={"Authorization": "Bearer t0ken"})
    assert r.status_code == 200, r.text
    d = r.json()
    vecs = embedder.decode(d["vectors_b64"])
    assert vecs.shape == (2, 4) and d["model"] == "bge-small" and d["dim"] == 4


def test_health_warms_the_model(client):
    h = client.get("/health", headers={"Authorization": "Bearer t0ken"}).json()
    assert h["status"] == "ok" and h["revision"] == "r1"


def test_limits(client):
    auth = {"Authorization": "Bearer t0ken"}
    assert (
        client.post("/embed", json={"texts": ["x" * 5000], "kind": "query"}, headers=auth).status_code == 413
    )
    assert client.post("/embed", json={"texts": [], "kind": "query"}, headers=auth).status_code == 422
    assert client.post("/embed", json={"texts": ["x"], "kind": "other"}, headers=auth).status_code == 422
