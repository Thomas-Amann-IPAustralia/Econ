"""The judged-set tools: the spend guard, cached paid calls, the judge's parser and the graded metrics.

No network: model clients are fakes, and chunks are placeholder text."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from econ import spend
from econ.answer.providers import Reply, Usage
from econ.evalr import grid2, judge, llmcall, systems
from econ.evalr.judged import Need
from econ.manifest import StageError


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    cfg = spend.EvalCfg(
        budgets_usd={"openai": 1.0, "gemini": 1.0},
        cap_fraction=0.9,
        ledger=str(tmp_path / "ledger.jsonl"),
        cache=str(tmp_path / "cache"),
    )
    monkeypatch.setattr(spend, "cfg", lambda: cfg)
    monkeypatch.setattr(
        spend.config, "path", lambda rel: Path(rel) if Path(rel).is_absolute() else tmp_path / rel
    )
    return tmp_path


def test_the_guard_refuses_a_call_that_would_cross_the_cap(ledger):
    spend.record(model="gpt-6-luna", purpose="t", usage={}, cost_usd=0.85)
    spend.guard("openai", 0.04)  # 0.89 fits under 0.9
    with pytest.raises(StageError):
        spend.guard("openai", 0.06)
    spend.guard("gemini", 0.5)  # budgets are per provider


class FakeModel:
    def __init__(self):
        self.calls = 0

    def generate_json(self, **kw):
        self.calls += 1
        return Reply(data={"ok": True}, usage=Usage(model=kw["model"], input=1000, output=100).price())


def test_paid_calls_are_cached_and_metered_once(ledger, monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llmcall, "_client", lambda model, flex: fake)
    c = llmcall.Call(model="gpt-6-luna", system="s", user="u", schema={}, schema_name="x", purpose="t")
    a = llmcall.run_one(c, flex=True)
    b = llmcall.run_one(c, flex=True)
    assert a["data"] == b["data"] == {"ok": True} and not a["cached"] and b["cached"]
    assert fake.calls == 1
    entries = spend.entries()
    assert len(entries) == 1 and entries[0]["mode"] == "flex"
    assert entries[0]["cost_usd"] == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6 * 0.5)


def test_the_judge_parser_reads_both_shapes_and_needs_every_id_once():
    ids = {"p1": "c1", "p2": "c2"}
    assert judge.parse({"data": {"grades": [{"id": "p1", "grade": 3}, {"id": "p2", "grade": 0}]}}, ids) == {
        "c1": 3,
        "c2": 0,
    }
    assert judge.parse({"data": [{"id": "p2", "grade": 1}, {"id": "p1", "grade": 2}]}, ids) == {
        "c1": 2,
        "c2": 1,
    }
    assert judge.parse({"data": [{"id": "p1", "grade": 2}]}, ids) is None  # one missing
    assert judge.parse({"data": [{"id": "p1", "grade": 5}, {"id": "p2", "grade": 1}]}, ids) is None
    assert judge.parse({"error": "x"}, ids) is None


def test_graded_metrics(monkeypatch):
    cs = [{"chunk_id": f"c{i}", "doc_id": "d", "spans": [], "tokens": 10} for i in range(4)]
    monkeypatch.setattr(systems, "chunks", lambda: cs)
    need = Need("n", "explore", "trend", "q", "narr", "dev")
    grades = {"c0": 0, "c1": 3, "c2": 2}  # c3 unjudged
    m = grid2.per_need([1, 2, 0, 3], need, grades)  # ideal order
    assert m["ndcg@10"] == pytest.approx(1.0)
    assert m["rel_recall@20"] == 1.0 and m["p@20"] == 0.5 and m["judged@20"] == 0.75
    worse = grid2.per_need([0, 3, 2, 1], need, grades)
    assert worse["ndcg@10"] < 1.0
    assert grid2.per_need([0], need, {"c0": 0})["ndcg@10"] is None  # nothing relevant: no ideal


def test_the_reranker_sees_pasted_headings_for_context_questions():
    n = Need(
        "n",
        "explore",
        "context",
        "Does the KB agree?",
        "",
        "dev",
        context="## GII ranking\ntext\n## Clusters",
    )
    assert systems.rerank_query(n) == "Does the KB agree? GII ranking Clusters"
    assert systems.rerank_query(Need("m", "silver", "lookup", "Plain q", "", "dev")) == "Plain q"


def test_cache_keys_cover_what_shapes_the_reply():
    a = llmcall.Call(model="m", system="s", user="u", schema={}, schema_name="x")
    assert a.key() != llmcall.Call(model="m", system="s", user="u2", schema={}, schema_name="x").key()
    assert (
        a.key()
        != llmcall.Call(model="m", system="s", user="u", schema={}, schema_name="x", effort="low").key()
    )
    assert (
        a.key()
        == llmcall.Call(model="m", system="s", user="u", schema={}, schema_name="x", tag="other").key()
    )
    json.dumps(a.__dict__)
