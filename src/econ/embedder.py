"""The embedding service: one ONNX model behind a small HTTP API, deployed on Google Cloud Run (D-003).

Three uses of one code path:
- `OnnxEmbedder`: tokenise, run, pool, normalise. The index is built with it too, so a query embedded on
  Cloud Run and a chunk embedded at build time go through identical code.
- `app`: the Cloud Run service. POST /embed, GET /health. A bearer token guards it when EMBEDDER_TOKEN
  is set.
- `python -m econ.embedder fetch-model`: downloads the adopted model's ONNX file and tokenizer at a
  pinned revision, checks their hashes, and writes them where the image expects them. The Dockerfile
  runs it at build time, so a cold start loads from local disk.

Needs only the `embedder` extra (onnxruntime, tokenizers) and the core dependencies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from econ import config
from econ.config import Embedder

MAX_TEXTS = 64
MAX_CHARS = 4000


class OnnxEmbedder:
    def __init__(self, key: str, model_dir: Path, *, threads: int | None = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.key = key
        self.spec: Embedder = config.pipeline().embedding.candidates[key]
        meta = json.loads((model_dir / "model.json").read_text())
        if meta["key"] != key or meta["revision"] != self.spec.revision:
            raise RuntimeError(f"model dir holds {meta['key']}@{meta['revision'][:8]}, expected {key}")
        self.meta = meta
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.max_len = min(self.spec.max_tokens, 1024)
        self.tok.enable_truncation(self.max_len)
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(
            str(model_dir / "model.onnx"), so, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.sess.get_inputs()}
        outs = self.sess.get_outputs()
        self.output = next((o.name for o in outs if o.name == "last_hidden_state"), outs[0].name)

    def _batch(self, texts: list[str]) -> np.ndarray:
        if self.spec.pooling == "last":
            self.tok.enable_padding(direction="left", pad_id=self.tok.token_to_id("<|endoftext|>") or 0)
        else:
            self.tok.enable_padding()
        enc = self.tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        if "position_ids" in self.inputs:
            feed["position_ids"] = np.clip(np.cumsum(mask, axis=1) - 1, 0, None)
        hidden = self.sess.run([self.output], feed)[0]
        if hidden.ndim == 2:  # the export already pooled
            pooled = hidden
        elif self.spec.pooling == "cls":
            pooled = hidden[:, 0]
        elif self.spec.pooling == "mean":
            m = mask[..., None].astype(hidden.dtype)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        else:  # last token; left padding puts it at the end
            pooled = hidden[:, -1]
        pooled = pooled.astype(np.float32)
        return pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)

    def encode(self, texts: list[str], *, kind: str, batch_size: int = 16) -> np.ndarray:
        pfx = self.spec.query_prefix if kind == "query" else self.spec.doc_prefix
        inputs = [pfx + t for t in texts]
        order = sorted(range(len(inputs)), key=lambda i: -len(inputs[i]))
        out = np.empty((len(inputs), self.spec.dim), dtype=np.float32)
        for s in range(0, len(order), batch_size):
            idx = order[s : s + batch_size]
            out[idx] = self._batch([inputs[i] for i in idx])
        return out


# --- model files -----------------------------------------------------------------------------------


def _download(repo: str, revision: str, filename: str, dest: Path) -> str:
    import httpx

    url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
    h = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r, tmp.open("wb") as fh:
        r.raise_for_status()
        for block in r.iter_bytes(1 << 20):
            fh.write(block)
            h.update(block)
    tmp.replace(dest)
    return h.hexdigest()


def fetch_model(key: str, dest: Path) -> dict:
    spec = config.pipeline().embedding.candidates[key]
    if not spec.onnx_file:
        raise SystemExit(f"{key} has no onnx_file in config; export one first (see docs/embedder.md)")
    dest.mkdir(parents=True, exist_ok=True)
    digest = _download(spec.hf_id, spec.revision, spec.onnx_file, dest / "model.onnx")
    if spec.onnx_sha256 and digest != spec.onnx_sha256:
        raise SystemExit(f"{key}: model.onnx sha256 {digest} does not match config {spec.onnx_sha256}")
    _download(spec.hf_id, spec.revision, "tokenizer.json", dest / "tokenizer.json")
    meta = {
        "key": key,
        "hf_id": spec.hf_id,
        "revision": spec.revision,
        "onnx_file": spec.onnx_file,
        "onnx_sha256": digest,
    }
    (dest / "model.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    return meta


# --- the Cloud Run service ------------------------------------------------------------------------


def create_app():
    from fastapi import FastAPI, Header, HTTPException
    from pydantic import BaseModel, Field

    model_dir = Path(os.environ.get("ECON_EMBEDDER_DIR", "/models"))
    key = (
        json.loads((model_dir / "model.json").read_text())["key"]
        if (model_dir / "model.json").exists()
        else None
    )
    state: dict = {}
    token = os.environ.get("EMBEDDER_TOKEN", "")

    def model() -> OnnxEmbedder:
        if "m" not in state:
            t = time.time()
            state["m"] = OnnxEmbedder(key, model_dir)
            state["load_seconds"] = round(time.time() - t, 2)
        return state["m"]

    api = FastAPI(title="econ embedder", docs_url=None, redoc_url=None)

    class EmbedIn(BaseModel):
        texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)
        kind: str = Field(pattern="^(query|doc)$")

    def check(auth: str | None) -> None:
        if token and not hmac.compare_digest(auth or "", f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="unauthorised")

    @api.get("/health")
    def health(authorization: str | None = Header(default=None)) -> dict:
        check(authorization)
        m = model()  # a health check warms the model, so the first real query is fast
        return {
            "status": "ok",
            "model": m.key,
            "revision": m.meta["revision"],
            "dim": m.spec.dim,
            "onnx_sha256": m.meta["onnx_sha256"],
            "load_seconds": state.get("load_seconds"),
        }

    @api.post("/embed")
    def embed(body: EmbedIn, authorization: str | None = Header(default=None)) -> dict:
        check(authorization)
        if any(len(t) > MAX_CHARS for t in body.texts):
            raise HTTPException(status_code=413, detail=f"each text must be under {MAX_CHARS} characters")
        m = model()
        t = time.time()
        vecs = m.encode(body.texts, kind=body.kind)
        return {
            "model": m.key,
            "revision": m.meta["revision"],
            "dim": int(vecs.shape[1]),
            "dtype": "float32",
            "vectors_b64": [base64.b64encode(v.tobytes()).decode() for v in vecs],
            "seconds": round(time.time() - t, 4),
        }

    return api


def __getattr__(name: str):
    # `uvicorn econ.embedder:app` builds the app on first access, so importing this module stays cheap.
    if name == "app":
        return create_app()
    raise AttributeError(name)


def decode(vectors_b64: list[str]) -> np.ndarray:
    return np.stack([np.frombuffer(base64.b64decode(v), dtype=np.float32) for v in vectors_b64])


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "fetch-model":
        args = dict(zip(sys.argv[2::2], sys.argv[3::2], strict=False))
        k = args.get("--model") or config.pipeline().embedding.adopted
        if not k:
            raise SystemExit("no --model given and embedding.adopted is not set")
        print(json.dumps(fetch_model(k, Path(args.get("--dest", "/models"))), indent=2))
    else:
        raise SystemExit("usage: python -m econ.embedder fetch-model [--model KEY] [--dest DIR]")
