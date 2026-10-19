"""Tracing (D-022): the trace's shape, checked offline with the real Langfuse SDK and an in-memory exporter."""

import itertools
import json

import pytest
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from econ import tracing
from econ.answer import pipeline
from econ.answer.providers import ScriptedModel, Usage
from econ.config import service
from econ.retrieval.index import Index
from tests.conftest import FakeEmbedder
from tests.test_pipeline import PROVIDER, good_answer

_keys = itertools.count()


def make_tracer(exporter=None):
    """A real Langfuse client on its own public key (the SDK keeps one client per key), exporting to memory;
    scores are captured instead of sent."""
    t = tracing.LangfuseTracer(
        public_key=f"pk-test-{next(_keys)}",
        secret_key="sk-test",
        base_url="http://127.0.0.1:9",
        environment="test",
        release="abc123",
        build={"commit": "abc123", "dirty": False},
        exporter=exporter or InMemorySpanExporter(),
    )
    t.scores = []
    t.client.create_score = lambda **kw: t.scores.append(kw)
    return t


def spans(t):
    t.flush()
    return t.exporter.inner.get_finished_spans()


def attr(s, key):
    v = s.attributes.get(key)
    return json.loads(v) if isinstance(v, str) and v[:1] in '{["' else v


def ask(t, question="Did small firms patent more?", **kw):
    svc = pipeline.Services(
        index=Index(), embedder=FakeEmbedder(), model=ScriptedModel(good_answer), provider=PROVIDER, tracer=t
    )
    return list(pipeline.run(pipeline.Request(question=question, session_id="conv-12345678", **kw), svc))


def test_a_question_is_one_trace_with_each_step_typed_and_nested(index_dir):
    t = make_tracer()
    evs = ask(t)
    got = spans(t)
    by_name = {}
    for s in got:
        by_name.setdefault(s.name, []).append(s)
    types = {n: {attr(s, "langfuse.observation.type") for s in ss} for n, ss in by_name.items()}
    assert types == {
        "econ.ask": {"agent"},
        "econ.plan": {"generation"},
        "econ.search": {"retriever"},
        "econ.filter": {"chain"},
        "econ.filter.rate": {"generation"},
        "econ.answer": {"generation"},
        "econ.check": {"evaluator"},
    }
    root = by_name["econ.ask"][0]
    assert root.parent is None and {s.context.trace_id for s in got} == {root.context.trace_id}
    for name in ("econ.plan", "econ.search", "econ.filter", "econ.answer", "econ.check"):
        assert all(s.parent.span_id == root.context.span_id for s in by_name[name])
    filt = by_name["econ.filter"][0]
    assert all(s.parent.span_id == filt.context.span_id for s in by_name["econ.filter.rate"])
    # The session, the trace's name and the build are on every observation, not only the root.
    assert {attr(s, "session.id") for s in got} == {"conv-12345678"}
    assert {attr(s, "langfuse.trace.name") for s in got} == {"econ.ask"}
    assert all(attr(s, "langfuse.observation.metadata.commit") == "abc123" for s in got)
    assert {attr(s, "langfuse.environment") for s in got} == {"test"}
    # The done event names the trace.
    assert evs[-1]["trace_id"] == format(root.context.trace_id, "032x")
    # The trace reads at a glance: the question in, the answer out.
    assert attr(root, "langfuse.observation.input")["question"] == "Did small firms patent more?"
    assert attr(root, "langfuse.observation.output")["coverage"] == "complete"


def test_generations_carry_messages_reply_and_exclusive_usage_with_cost(index_dir):
    t = make_tracer()
    ask(t)
    for s in spans(t):
        if attr(s, "langfuse.observation.type") != "generation":
            continue
        msgs = attr(s, "langfuse.observation.input")
        assert [m["role"] for m in msgs] == ["system", "user"] and msgs[1]["content"]
        assert attr(s, "langfuse.observation.output") is not None
        assert attr(s, "langfuse.observation.model.name") in (PROVIDER.answer_model, PROVIDER.plan_model)
        u = attr(s, "langfuse.observation.usage_details")
        c = attr(s, "langfuse.observation.cost_details")
        assert set(u) == {"input", "input_cached_tokens", "output", "output_reasoning_tokens", "total"}
        assert u["total"] == sum(v for k, v in u.items() if k != "total")
        assert c["total"] == pytest.approx(sum(v for k, v in c.items() if k != "total"))


def test_reasoning_is_its_own_bucket_never_counted_twice():
    u = Usage(model=PROVIDER.answer_model, input=1000, cached_input=200, output=900, reasoning=300).price()
    f = tracing.usage_fields(u)
    assert f["usage_details"] == {
        "input": 1000,
        "input_cached_tokens": 200,
        "output": 600,
        "output_reasoning_tokens": 300,
        "total": 2100,
    }
    assert f["cost_details"]["total"] == pytest.approx(u.cost_usd)


def test_search_is_a_retriever_with_the_full_result_and_the_check_is_scored(index_dir):
    t = make_tracer()
    evs = ask(t)
    got = {s.name: s for s in spans(t)}
    out = attr(got["econ.search"], "langfuse.observation.output")
    pool = next(e for e in evs if e["event"] == "retrieval")["pool"]
    assert [r["chunk_id"] for r in out] == [p["chunk_id"] for p in pool]
    assert all(r["text"] and r["search_rank"] for r in out)
    check = attr(got["econ.check"], "langfuse.observation.output")
    assert check["passed"] is True
    trace_scores = {s["name"]: s["value"] for s in t.scores if s.get("observation_id") is None}
    assert trace_scores["check_passed"] is True and trace_scores["outcome"] == "passed"
    assert trace_scores["coverage"] == "complete" and trace_scores["attempts"] == 1
    assert {s["name"] for s in t.scores if s.get("observation_id")} == {"check_passed", "claims_verified"}


def test_an_abandoned_stream_still_ends_the_trace_and_says_so(index_dir):
    t = make_tracer()
    svc = pipeline.Services(index=Index(), embedder=FakeEmbedder(), tracer=t)
    gen = pipeline.run(pipeline.Request(question="patent filings small firms"), svc)
    next(gen)
    gen.close()  # the client went away
    root = next(s for s in spans(t) if s.name == "econ.ask")
    assert attr(root, "langfuse.observation.level") == "WARNING"


def test_a_lost_span_is_counted_and_shown(index_dir):
    class Down:
        def export(self, spans):
            return SpanExportResult.FAILURE

        def shutdown(self):
            pass

        def force_flush(self, timeout_millis=0):
            return True

    t = make_tracer(Down())
    svc = pipeline.Services(index=Index(), embedder=FakeEmbedder(), tracer=t)
    list(pipeline.run(pipeline.Request(question="patent filings small firms"), svc))
    t.flush()
    st = t.status()
    assert st["failed"] >= 2 and st["status"] == "spans lost"


def test_people_data_is_masked_and_statistics_are_not():
    m = tracing.mask({"q": "Call 0412 345 678 or (02) 6283 2999, or mail a.b@ipaustralia.gov.au"})
    assert m["q"] == "Call [phone] or [phone], or mail [email]"
    stats = "In 2019, 29,758 standard patents were filed; 2,345,678 in total; IPC 0412 3"
    assert tracing.mask(stats) == stats


def test_metadata_over_langfuses_limit_is_an_error_not_a_silent_drop():
    tracing.check_metadata({"ok": "x" * 200})
    with pytest.raises(ValueError, match="200"):
        tracing.check_metadata({"too_long": "x" * 201})


def test_the_build_identity_fits_langfuses_limits(index_dir):
    meta = tracing.build_identity(Index().meta, PROVIDER)
    assert {"commit", "dirty", "index", "config", "prompts", "models"} <= set(meta)
    assert service().answer.prompt in meta["prompts"]


def test_without_keys_tracing_is_off_visibly_and_required_makes_it_an_error(monkeypatch, index_dir):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    t = tracing.from_env(Index().meta)
    assert t.status() == {"enabled": False, "status": "no keys"}
    scfg = service()
    strict = scfg.model_copy(update={"tracing": scfg.tracing.model_copy(update={"required": True})})
    monkeypatch.setattr(tracing.config, "service", lambda: strict)
    with pytest.raises(RuntimeError, match="no Langfuse keys"):
        tracing.from_env(Index().meta)


def test_the_null_tracer_leaves_the_stream_unchanged_apart_from_a_null_trace_id(index_dir):
    svc = pipeline.Services(index=Index(), embedder=FakeEmbedder())
    evs = list(pipeline.run(pipeline.Request(question="patent filings small firms"), svc))
    assert evs[-1]["event"] == "done" and evs[-1]["trace_id"] is None
