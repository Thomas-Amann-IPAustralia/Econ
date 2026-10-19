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
    note: str | None = None  # shown with every passage from the document


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
    reocr: bool = True  # re-read garbled OCR elements from their own boxes (D-022)
    reocr_scales: list[float] = [3.0, 4.0]
    reocr_pads: list[float] = [2.0, 4.0, 8.0]
    reocr_agreement: float = 0.8
    reocr_model: str | None = None  # the vision model for what no crop variant repairs (D-022); null: none
    threads: int = 4
    table_structure: bool = True


class ChunkStrategy(Strict):
    kind: Literal["structure", "fixed"]
    max_tokens: int
    overlap_tokens: int = 0
    min_tokens: int = 48
    prefix: Literal["none", "title", "title+section"] = "title+section"
    drop_citations: bool = False  # leave bibliography entries and citation-only endnotes out (D-007)


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


class Reranker(Strict):
    hf_id: str
    revision: str
    params_m: float
    licence: str
    max_tokens: int = 512
    onnx_file: str = "onnx/model.onnx"
    onnx_sha256: str | None = None


class RerankingCfg(Strict):
    candidates: dict[str, Reranker] = {}
    adopted: str | None = None  # None: no reranker; the first stage's order is the ranking
    depth: int = 50  # first-stage candidates the reranker reorders

    @model_validator(mode="after")
    def _adopted_known(self) -> RerankingCfg:
        if self.adopted is not None and self.adopted not in self.candidates:
            raise ValueError(f"reranking.adopted {self.adopted!r} is not a candidate")
        return self


class RetrievalCfg(Strict):
    lane_depth: int = 100
    fusion: Literal["score", "rrf"] = "score"
    alpha: float = Field(0.7, ge=0.0, le=1.0)
    rrf_k: int = 60
    context_chunks: int = 20
    per_doc_cap: int = 8
    # Context notes (library/enrich/<name>.jsonl) put in front of each chunk's text for BM25 and the dense
    # lane; search-only, never evidence (D-013). None indexes the chunk text alone.
    enrichment: str | None = None


class Pipeline(Strict):
    paths: Paths = Paths()
    parse: ParseCfg = ParseCfg()
    chunking: ChunkingCfg
    embedding: EmbeddingCfg
    retrieval: RetrievalCfg = RetrievalCfg()
    reranking: RerankingCfg = RerankingCfg()


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
    # The relevance filter's model (D-018). None: this provider doesn't filter, and the answer model gets the
    # first stage's top passages (only gpt-6-luna has been measured as the filter).
    filter_model: str | None = None
    filter_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None


class LlmCfg(Strict):
    providers: list[Provider]
    prices_per_mtok: dict[str, tuple[float, float, float]]
    daily_budget_usd: float
    max_output_tokens: int = 3000  # includes reasoning (thinking) tokens on both providers
    plan_max_output_tokens: int = 1500
    timeout_seconds: float = 90
    query_planning: bool = True

    @model_validator(mode="after")
    def _priced(self) -> LlmCfg:
        for p in self.providers:
            for m in (p.answer_model, p.plan_model, p.filter_model):
                if m is not None and m not in self.prices_per_mtok:
                    raise ValueError(f"no price for model {m!r}")
        return self


class FilterCfg(Strict):
    """The relevance filter (D-018, D-020): a small model rates the first `read` passages of the search 0-3,
    `group` a call (the calls run in parallel), and the answer model gets the `retrieval.context_chunks`
    rated highest, ties in search order."""

    prompt: str
    read: int = 60
    group: int = 20
    max_output_tokens: int = 3000


class AnswerCfg(Strict):
    prompt: str
    plan_prompt: str
    filter: FilterCfg | None = None  # None: no filter; the answer model gets the search's top passages
    max_queries: int = 4
    # Search the standalone question as well as the plan's queries (D-013), so a plan that misses can't
    # take the question's own words out of the search.
    plan_keeps_question: bool = False
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


class TracingCfg(Strict):
    """Langfuse (SOP §20.3). Keys come from the environment under these names; the host and the
    environment are explicit, never ambient."""

    enabled: bool = True
    required: bool = False  # true: no keys is an error, not a quiet null tracer
    base_url: str = "https://cloud.langfuse.com"
    public_key_env: str = "LANGFUSE_PUBLIC_KEY"
    secret_key_env: str = "LANGFUSE_SECRET_KEY"
    environment_env: str = "ECON_ENVIRONMENT"
    default_environment: str = "dev"
    sample_rate: float = 1.0


class Service(Strict):
    cors_origins: list[str]
    embedder: EmbedderCfg = EmbedderCfg()
    llm: LlmCfg
    answer: AnswerCfg
    limits: LimitsCfg = LimitsCfg()
    logging: LoggingCfg = LoggingCfg()
    tracing: TracingCfg = TracingCfg()


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
