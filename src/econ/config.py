"""Configuration: YAML files under config/, validated by pydantic. Unknown keys are errors."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- sources -------------------------------------------------------------------------------------


class Document(Strict):
    doc_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    key: str
    title: str
    year: int
    series: str
    authors: list[str] = []
    url: str | None = None


class Sources(Strict):
    bucket: str
    endpoint: str
    publisher: str
    documents: list[Document]

    @model_validator(mode="after")
    def _unique(self) -> Sources:
        for field in ("doc_id", "key"):
            values = [getattr(d, field) for d in self.documents]
            dupes = {v for v in values if values.count(v) > 1}
            if dupes:
                raise ValueError(f"duplicate {field}: {sorted(dupes)}")
        return self

    def by_id(self) -> dict[str, Document]:
        return {d.doc_id: d for d in self.documents}

    def by_key(self) -> dict[str, Document]:
        return {d.key: d for d in self.documents}


# --- pipeline ------------------------------------------------------------------------------------


class Paths(Strict):
    raw: str = "data/raw"
    library: str = "library"
    manifests: str = "manifests"
    reports: str = "reports"
    models: str = "data/models"


class ParseCfg(Strict):
    ocr_min_chars_per_page: int = 100
    ocr_page_share: float = 0.5
    ocr_scale: float = 2.0
    threads: int = 4
    table_structure: bool = True


class ChunkStrategy(Strict):
    kind: Literal["structure", "fixed"]
    max_tokens: int
    overlap_tokens: int = 0
    min_tokens: int = 48
    prefix: Literal["none", "title", "title+section"] = "title+section"


class ChunkingCfg(Strict):
    tokenizer: str
    tokenizer_revision: str
    strategies: dict[str, ChunkStrategy]
    adopted: str | None = None

    @model_validator(mode="after")
    def _adopted_known(self) -> ChunkingCfg:
        if self.adopted is not None and self.adopted not in self.strategies:
            raise ValueError(f"chunking.adopted {self.adopted!r} is not a strategy")
        return self


class Embedder(Strict):
    hf_id: str
    revision: str
    params_m: float
    dim: int
    pooling: Literal["cls", "mean", "last"]
    max_tokens: int = 512
    query_prefix: str = ""
    doc_prefix: str = ""
    licence: str
    onnx_file: str | None = None  # path inside the HF repo, for serving
    onnx_sha256: str | None = None


class EmbeddingCfg(Strict):
    candidates: dict[str, Embedder]
    adopted: str | None = None
    batch_size: int = 32

    @model_validator(mode="after")
    def _adopted_known(self) -> EmbeddingCfg:
        if self.adopted is not None and self.adopted not in self.candidates:
            raise ValueError(f"embedding.adopted {self.adopted!r} is not a candidate")
        return self


class RetrievalCfg(Strict):
    lane_depth: int = 100
    fusion: Literal["score", "rrf"] = "score"
    alpha: float = Field(0.7, ge=0.0, le=1.0)
    rrf_k: int = 60
    context_chunks: int = 20
    per_doc_cap: int = 8


class Pipeline(Strict):
    paths: Paths = Paths()
    parse: ParseCfg = ParseCfg()
    chunking: ChunkingCfg
    embedding: EmbeddingCfg
    retrieval: RetrievalCfg = RetrievalCfg()


# --- service -------------------------------------------------------------------------------------


class EmbedderCfg(Strict):
    url_env: str = "EMBEDDER_URL"
    token_env: str = "EMBEDDER_TOKEN"
    timeout_seconds: float = 8
    cold_timeout_seconds: float = 40


class Provider(Strict):
    name: Literal["openai", "gemini"]
    key_env: str
    base_url: str
    answer_model: str
    answer_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None
    plan_model: str
    plan_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None


class LlmCfg(Strict):
    providers: list[Provider]
    prices_per_mtok: dict[str, tuple[float, float, float]]
    daily_budget_usd: float
    max_output_tokens: int = 3000
    timeout_seconds: float = 90
    query_planning: bool = True

    @model_validator(mode="after")
    def _priced(self) -> LlmCfg:
        for p in self.providers:
            for m in (p.answer_model, p.plan_model):
                if m not in self.prices_per_mtok:
                    raise ValueError(f"no price for model {m!r}")
        return self


class AnswerCfg(Strict):
    prompt: str
    plan_prompt: str
    max_queries: int = 4
    min_quote_words: int = 5
    quote_claim_ratio: float = 0.5
    max_quote_words: int = 80


class LimitsCfg(Strict):
    requests_per_hour_per_client: int = 30
    max_question_chars: int = 2000
    max_context_chars: int = 20000
    max_history_turns: int = 6


class LoggingCfg(Strict):
    record_questions: bool = True


class Service(Strict):
    cors_origins: list[str]
    embedder: EmbedderCfg = EmbedderCfg()
    llm: LlmCfg
    answer: AnswerCfg
    limits: LimitsCfg = LimitsCfg()
    logging: LoggingCfg = LoggingCfg()


# --- loading -------------------------------------------------------------------------------------


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache
def sources() -> Sources:
    return Sources.model_validate(_load_yaml("sources.yaml"))


@lru_cache
def pipeline() -> Pipeline:
    return Pipeline.model_validate(_load_yaml("pipeline.yaml"))


@lru_cache
def service() -> Service:
    return Service.model_validate(_load_yaml("service.yaml"))


def config_hash(*models: BaseModel) -> str:
    """A short hash of resolved config, for manifests and build identity."""
    blob = json.dumps([m.model_dump(mode="json") for m in models], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def path(rel: str) -> Path:
    """Resolve a repo-relative path from config."""
    return ROOT / rel
