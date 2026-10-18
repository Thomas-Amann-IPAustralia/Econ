"""A cross-encoder reranker from a repository's own ONNX export, for the Cloud Run service (D-012).

The Ettin rerankers' ONNX files hold only the transformer (its `last_hidden_state`); the score head that
sentence-transformers applies after it (CLS pooling, a dense layer with GELU, LayerNorm, a dense layer to
one logit) is read here from the repository's safetensors files and applied in numpy. `econ
verify-reranker` shows the result matches sentence-transformers.

Needs only numpy, onnxruntime and tokenizers (the `embedder` extra).
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

import numpy as np

from econ import config

HEAD = ("1_Pooling", "2_Dense", "3_LayerNorm", "4_Dense")
FILES = ["tokenizer.json", "config.json", "modules.json", "1_Pooling/config.json"] + [
    f"{d}/{f}" for d in HEAD[1:] for f in ("config.json", "model.safetensors")
]
_DTYPES = {"F32": np.float32, "F16": np.float16, "BF16": None}


def read_safetensors(path: Path) -> dict[str, np.ndarray]:
    """The safetensors format without the library: an 8-byte header length, a JSON header, raw tensors."""
    raw = path.read_bytes()
    (n,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8 : 8 + n])
    out = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        dt = _DTYPES[info["dtype"]]
        a, b = info["data_offsets"]
        out[name] = (
            np.frombuffer(raw[8 + n + a : 8 + n + b], dtype=dt).reshape(info["shape"]).astype(np.float32)
        )
    return out


def _gelu(x: np.ndarray) -> np.ndarray:
    erf = np.vectorize(math.erf, otypes=[np.float64])
    return (0.5 * x * (1.0 + erf(x / math.sqrt(2.0)))).astype(np.float32)


class OnnxReranker:
    def __init__(
        self, key: str, model_dir: Path, *, threads: int | None = None, onnx_name: str = "model.onnx"
    ):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.key = key
        self.spec = config.pipeline().reranking.candidates[key]
        meta = json.loads((model_dir / "model.json").read_text())
        if meta["key"] != key or meta["revision"] != self.spec.revision:
            raise RuntimeError(f"model dir holds {meta['key']}@{meta['revision'][:8]}, expected {key}")
        self.meta = meta
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(self.spec.max_tokens, strategy="longest_first")
        self.tok.enable_padding()
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        so.enable_cpu_mem_arena = False
        self.sess = ort.InferenceSession(str(model_dir / onnx_name), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}
        self.w1 = read_safetensors(model_dir / "2_Dense/model.safetensors")["linear.weight"]
        ln = read_safetensors(model_dir / "3_LayerNorm/model.safetensors")
        self.ln_w, self.ln_b = ln["norm.weight"], ln["norm.bias"]
        d2 = read_safetensors(model_dir / "4_Dense/model.safetensors")
        self.w2, self.b2 = d2["linear.weight"], d2["linear.bias"]

    def _batch(self, query: str, passages: list[str]) -> np.ndarray:
        enc = self.tok.encode_batch([(query, p) for p in passages])
        feed = {
            "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
        }
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
        h = self.sess.run(["last_hidden_state"], feed)[0][:, 0].astype(np.float32)  # CLS pooling
        x = _gelu(h @ self.w1.T)
        mu, var = x.mean(-1, keepdims=True), x.var(-1, keepdims=True)
        x = (x - mu) / np.sqrt(var + 1e-5) * self.ln_w + self.ln_b
        return (x @ self.w2.T + self.b2)[:, 0]

    def score(self, query: str, passages: list[str], batch_size: int = 16) -> np.ndarray:
        """One logit per passage; higher is more relevant. Longest first keeps padding low."""
        order = sorted(range(len(passages)), key=lambda i: -len(passages[i]))
        out = np.empty(len(passages), dtype=np.float32)
        for s in range(0, len(order), batch_size):
            idx = order[s : s + batch_size]
            out[idx] = self._batch(query, [passages[i] for i in idx])
        return out


def fetch_reranker(key: str, dest: Path) -> dict:
    """Download a reranker's ONNX export, tokenizer and head at its pinned revision, checking hashes."""
    from econ.embedder import _download

    spec = config.pipeline().reranking.candidates[key]
    dest.mkdir(parents=True, exist_ok=True)
    digest = _download(spec.hf_id, spec.revision, spec.onnx_file, dest / "model.onnx")
    if spec.onnx_sha256 and digest != spec.onnx_sha256:
        raise SystemExit(f"{key}: model.onnx sha256 {digest} does not match config {spec.onnx_sha256}")
    hashes = {}
    for f in FILES:
        (dest / f).parent.mkdir(parents=True, exist_ok=True)
        hashes[f] = _download(spec.hf_id, spec.revision, f, dest / f)
    meta = {
        "key": key,
        "hf_id": spec.hf_id,
        "revision": spec.revision,
        "onnx_file": spec.onnx_file,
        "onnx_sha256": digest,
        "files_sha256": hashes,
    }
    (dest / "model.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    return meta


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
