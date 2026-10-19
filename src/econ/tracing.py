"""Tracing to Langfuse (SOP §20.0 and §20.3): one trace per question, one session per conversation.

The trace of a question:

  econ.ask (agent)                       input: the question; output: the answer's prose and coverage
    econ.plan (generation)               the planner's messages, reply, usage and cost
    econ.search (retriever)              the queries and every passage read, with ranks, scores and text
    econ.filter (chain)                  the relevance filter (D-020)
      econ.filter.rate (generation)      one per group of 20 passages, in parallel
    econ.answer (generation)             one per attempt
    econ.check (evaluator)               one per attempt; its results are also scores on the trace

Every observation carries the build that produced it (commit and dirty flag; hashes of the index, the
config and the prompts; the models and efforts), each value checked against Langfuse's 200-character limit.
Usage goes in exclusive buckets (input, input_cached_tokens, output, output_reasoning_tokens) with the cost
of each and an explicit total.

Observations are started from an explicit parent, never from the ambient context: the service streams a
question from a generator that each `next()` may advance on a different thread, and the filter rates in a
thread pool. The client is pinned: keys from the environment under names config gives, the host,
environment, release and sample rate passed explicitly, and its own tracer provider (never the global one).
Exports go through a counting exporter, so a lost span is counted and shown, never silent. Without keys,
tracing is off and says so (`/api/health`, the start-up log); `tracing.required` makes that an error.
A null tracer serves the tests and every caller that doesn't trace.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import threading
from collections.abc import Sequence
from typing import Any

from econ import config

MAX_META = 200  # Langfuse drops metadata values longer than this, silently
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<![\w.])(\+61[\s-]?\d|\(0[2378]\)|0[2-478])(?:[\s-]?\d){7,8}(?![\w.])")


def mask(data: Any = None, **_: Any) -> Any:
    """Email addresses and Australian phone numbers out of everything traced: questions and pasted context
    come from people. Statistics in the reports are never this shape."""
    if isinstance(data, str):
        return _PHONE.sub("[phone]", _EMAIL.sub("[email]", data))
    if isinstance(data, dict):
        return {k: mask(v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask(v) for v in data]
    return data


def check_metadata(meta: dict) -> dict:
    """Metadata as Langfuse keeps it: every value, JSON-encoded, at most 200 characters, or an error."""
    for k, v in meta.items():
        enc = v if isinstance(v, str) else json.dumps(v)
        if len(enc) > MAX_META:
            raise ValueError(f"trace metadata {k!r} is {len(enc)} characters; Langfuse keeps {MAX_META}")
    return meta


def usage_fields(u) -> dict:
    """A provider Usage as Langfuse's exclusive buckets, with each bucket's cost and the total."""
    if u is None:
        return {}
    p_in, p_cached, p_out = config.service().llm.prices_per_mtok[u.model]
    text_out = max(0, u.output - u.reasoning)
    usage = {
        "input": u.input,
        "input_cached_tokens": u.cached_input,
        "output": text_out,
        "output_reasoning_tokens": u.reasoning,
    }
    cost = {
        "input": u.input * p_in / 1e6,
        "input_cached_tokens": u.cached_input * p_cached / 1e6,
        "output": text_out * p_out / 1e6,
        "output_reasoning_tokens": u.reasoning * p_out / 1e6,
    }
    cost = {k: round(v, 8) for k, v in cost.items()}
    cost["total"] = round(sum(cost.values()), 8)
    usage["total"] = sum(usage.values())
    return {"usage_details": usage, "cost_details": cost}


def build_identity(index_meta: dict, provider=None, commit: str | None = None) -> dict:
    """What produced a trace, as short values (SOP §20.0, convention 2)."""
    from econ.answer import prompts
    from econ.manifest import git_state

    scfg = config.service()
    g = git_state()
    files = index_meta.get("files", {})
    lock = json.loads((prompts.PROMPTS / "versions.lock").read_text())
    used = [scfg.answer.prompt, scfg.answer.plan_prompt] + (
        [scfg.answer.filter.prompt] if scfg.answer.filter else []
    )
    meta = {
        "commit": (commit or g["commit"])[:12],
        "dirty": g["dirty"],
        "index": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16],
        "index_built": index_meta.get("built_from", ""),
        "config": config.config_hash(scfg, config.pipeline()),
        "prompts": ",".join(f"{n}@{lock[n]['sha256'][:8]}" for n in used if n in lock),
        "embedder": f"{index_meta.get('embedder')}@{str(index_meta.get('revision', ''))[:8]}",
    }
    if provider is not None:
        models = [
            (provider.answer_model, provider.answer_effort),
            (provider.plan_model, provider.plan_effort),
            (getattr(provider, "filter_model", None), getattr(provider, "filter_effort", None)),
        ]
        meta["models"] = ",".join(f"{m}/{e}" for m, e in models if m)
    return check_metadata(meta)


# --- observations ----------------------------------------------------------------------------------------


class NullObs:
    """An observation that records nothing."""

    trace_id: str | None = None
    id: str | None = None

    def child(self, name: str, as_type: str = "span", **kw: Any) -> NullObs:
        return self

    def update(self, **kw: Any) -> None:
        pass

    def end(self) -> None:
        pass

    def score(self, name: str, value: Any, data_type: str, comment: str | None = None) -> None:
        pass

    def score_trace(self, name: str, value: Any, data_type: str, comment: str | None = None) -> None:
        pass


class Obs(NullObs):
    """A Langfuse observation with the trace's attributes (name, session, tags) set on it, so that every
    observation counts in Langfuse's per-session and per-tag aggregates, not only the root."""

    def __init__(self, inner: Any, trace_attrs: dict, build: dict):
        self.inner, self.trace_attrs, self.build = inner, trace_attrs, build
        self.trace_id, self.id = inner.trace_id, inner.id
        inner._otel_span.set_attributes(trace_attrs)

    def child(self, name: str, as_type: str = "span", **kw: Any) -> Obs:
        kw["metadata"] = {**self.build, **(kw.get("metadata") or {})}
        return Obs(
            self.inner.start_observation(name=name, as_type=as_type, **kw), self.trace_attrs, self.build
        )

    def update(self, **kw: Any) -> None:
        if "metadata" in kw:
            kw["metadata"] = {**self.build, **kw["metadata"]}
        self.inner.update(**kw)

    def end(self) -> None:
        self.inner.end()

    def score(self, name: str, value: Any, data_type: str, comment: str | None = None) -> None:
        self.inner.score(name=name, value=value, data_type=data_type, comment=comment)

    def score_trace(self, name: str, value: Any, data_type: str, comment: str | None = None) -> None:
        self.inner.score_trace(name=name, value=value, data_type=data_type, comment=comment)


# --- tracers ---------------------------------------------------------------------------------------------


class NullTracer:
    """Records nothing; the default for every caller that doesn't trace, and for the tests."""

    enabled = False

    def __init__(self, reason: str = "off"):
        self.reason = reason

    def trace(
        self, name: str, *, session_id: str | None = None, tags: Sequence[str] = (), **kw: Any
    ) -> NullObs:
        return NullObs()

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def status(self) -> dict:
        return {"enabled": False, "status": self.reason}


class CountingExporter:
    """An OTel span exporter that counts what it exported and what failed, around the real one."""

    def __init__(self, inner: Any):
        self.inner, self.exported, self.failed, self.lock = inner, 0, 0, threading.Lock()

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            result = self.inner.export(spans)
        except Exception:  # noqa: BLE001 - counted as lost; tracing never fails a question
            result = SpanExportResult.FAILURE
        with self.lock:
            if result == SpanExportResult.SUCCESS:
                self.exported += len(spans)
            else:
                self.failed += len(spans)
        return result

    def shutdown(self):
        return self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


class LangfuseTracer:
    """The Langfuse client, pinned. `exporter` replaces the network exporter (tests: an in-memory one)."""

    enabled = True

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        environment: str,
        release: str,
        build: dict,
        sample_rate: float = 1.0,
        exporter: Any = None,
    ):
        from langfuse import Langfuse
        from langfuse._client.attributes import LangfuseOtelSpanAttributes as A
        from langfuse._version import __version__ as lf_version
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        self.attrs = A
        if exporter is None:
            # The headers the SDK's own exporter sends (langfuse 5.0.2), around a counting wrapper.
            auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
            exporter = OTLPSpanExporter(
                endpoint=f"{base_url.rstrip('/')}/api/public/otel/v1/traces",
                headers={
                    "Authorization": f"Basic {auth}",
                    "x-langfuse-sdk-name": "python",
                    "x-langfuse-sdk-version": lf_version,
                    "x-langfuse-public-key": public_key,
                    "x-langfuse-ingestion-version": "4",
                },
                timeout=10,
            )
        self.exporter = CountingExporter(exporter)
        provider = TracerProvider(resource=Resource.create({A.ENVIRONMENT: environment, A.RELEASE: release}))
        self.client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            environment=environment,
            release=release,
            sample_rate=sample_rate,
            mask=mask,
            tracer_provider=provider,
            span_exporter=self.exporter,
            tracing_enabled=True,
        )
        if not self.client._tracing_enabled:
            raise RuntimeError("the Langfuse client started with tracing switched off")
        self.environment, self.base_url, self.build = environment, base_url, check_metadata(build)

    def trace(self, name: str, *, session_id: str | None = None, tags: Sequence[str] = (), **kw: Any) -> Obs:
        A = self.attrs
        attrs: dict[str, Any] = {A.TRACE_NAME: name}
        if session_id:
            attrs[A.TRACE_SESSION_ID] = session_id
        if tags:
            attrs[A.TRACE_TAGS] = list(tags)
        kw["metadata"] = {**self.build, **(kw.get("metadata") or {})}
        return Obs(self.client.start_observation(name=name, **kw), attrs, self.build)

    def flush(self) -> None:
        self.client.flush()

    def shutdown(self) -> None:
        self.client.shutdown()

    def status(self) -> dict:
        return {
            "enabled": True,
            "status": "ok" if not self.exporter.failed else "spans lost",
            "host": self.base_url,
            "environment": self.environment,
            "exported": self.exporter.exported,
            "failed": self.exporter.failed,
        }


def from_env(index_meta: dict, provider=None, *, environment: str | None = None, commit: str | None = None):
    """The tracer config and the environment ask for: Langfuse with keys, otherwise a null tracer that says
    why. `tracing.required` turns a missing key into an error instead of a quiet null tracer."""
    tc = config.service().tracing
    if not tc.enabled:
        return NullTracer("off in config")
    pk, sk = os.environ.get(tc.public_key_env, "").strip(), os.environ.get(tc.secret_key_env, "").strip()
    if not (pk and sk):
        msg = f"no Langfuse keys ({tc.public_key_env}, {tc.secret_key_env}); tracing is off"
        if tc.required:
            raise RuntimeError(msg)
        print(f"WARNING: {msg}", file=sys.stderr, flush=True)
        return NullTracer("no keys")
    env = environment or os.environ.get(tc.environment_env, "").strip() or tc.default_environment
    build = build_identity(index_meta, provider, commit)
    return LangfuseTracer(
        public_key=pk,
        secret_key=sk,
        base_url=tc.base_url,
        environment=env,
        release=build["commit"],
        build=build,
        sample_rate=tc.sample_rate,
    )
