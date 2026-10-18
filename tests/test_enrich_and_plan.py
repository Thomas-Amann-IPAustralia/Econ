"""D-013 in the service path: the plan keeps the question as a query when configured, context notes stay
out of every view, and highlights only name terms the passage itself contains."""

from __future__ import annotations

import json

from econ import config
from econ.answer import pipeline
from econ.answer.providers import ScriptedModel
from econ.retrieval.index import Index
from tests.conftest import FakeEmbedder

PROVIDER = config.service().llm.providers[0]


def plan_reply(schema_name, user):
    if schema_name == "plan":
        return {
            "standalone_question": "Did small firms patent more?",
            "queries": ["small firm patent filings"],
        }
    return {"coverage": "not_in_kb", "answer": "Not covered.", "claims": [], "gaps": ["everything"]}


def with_answer_cfg(monkeypatch, **kw):
    scfg = config.service()
    ans = scfg.answer.model_copy(update=kw)
    monkeypatch.setattr(config, "service", lambda: scfg.model_copy(update={"answer": ans}))


def test_the_plan_keeps_the_question_when_configured(index_dir, monkeypatch):
    with_answer_cfg(monkeypatch, plan_keeps_question=True)
    svc = pipeline.Services(
        index=Index(), embedder=FakeEmbedder(), model=ScriptedModel(plan_reply), provider=PROVIDER
    )
    ev = {e["event"]: e for e in pipeline.run(pipeline.Request(question="Did small firms patent more?"), svc)}
    assert ev["plan"]["queries"] == ["Did small firms patent more?", "small firm patent filings"]


def test_without_the_flag_the_plan_alone_is_searched(index_dir, monkeypatch):
    with_answer_cfg(monkeypatch, plan_keeps_question=False)
    svc = pipeline.Services(
        index=Index(), embedder=FakeEmbedder(), model=ScriptedModel(plan_reply), provider=PROVIDER
    )
    ev = {e["event"]: e for e in pipeline.run(pipeline.Request(question="Did small firms patent more?"), svc)}
    assert ev["plan"]["queries"] == ["small firm patent filings"]


def test_context_notes_never_reach_a_view_and_highlights_are_the_passages_own(index_dir):
    path = index_dir / "chunks.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    rows[0]["context_note"] = "A note about zebra statistics."
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    svc = pipeline.Services(index=Index(), embedder=FakeEmbedder())
    ev = {
        e["event"]: e
        for e in pipeline.run(pipeline.Request(question="patent filings small firms zebra"), svc)
    }
    for e in ev["retrieval"]["evidence"]:
        assert "context_note" not in e and "zebra" not in e["matched_terms"]

    from fastapi.testclient import TestClient

    from econ.service.app import create_app

    c = TestClient(create_app())
    assert "context_note" not in c.get(f"/api/chunk/{rows[0]['chunk_id']}").json()
