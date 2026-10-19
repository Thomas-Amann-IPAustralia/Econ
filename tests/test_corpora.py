"""More than one corpus (D-033): each built and searched apart, merged only after the search.

The second corpus here is placeholder text standing in for the WIPO reports.
"""

from __future__ import annotations

import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from econ import config
from econ.answer import pipeline
from econ.answer.providers import ScriptedModel
from econ.ingest.fetch import owned
from econ.kb.bm25 import BM25
from econ.manifest import stage_name
from econ.retrieval.index import Index
from tests.conftest import CHUNKS, DOCS, FakeEmbedder, build_index
from tests.test_pipeline import PROVIDER, good_answer, rate_all

WIPO_DOCS = {
    "wipo-x-2024": {"title": "Gamma Indicators 2024", "year": 2024, "series": "Gamma series"},
    "wipo-y-2023": {"title": "Delta World Report 2023", "year": 2023, "series": "Delta series"},
}
WIPO_CHUNKS = [
    ("wipo-x-2024", ["Patents worldwide"], "Lorem patent filings worldwide grew among offices, ipsum dolor."),
    ("wipo-x-2024", ["Trade marks worldwide"], "Trade mark class counts rose at most offices, sit amet."),
    ("wipo-y-2023", ["Innovation"], "Design rights and innovation across economies, consectetur elit."),
    ("wipo-y-2023", ["Copyright"], "Copyright industries contribute to output, sed do eiusmod tempor."),
]


@pytest.fixture
def wipo_dir(tmp_path, monkeypatch, index_dir):
    d = build_index(tmp_path / "wipo", WIPO_CHUNKS, WIPO_DOCS, publisher="Gamma Org", corpus="wipo", offset=3)
    monkeypatch.setenv("ECON_INDEX_DIR_WIPO", str(d))
    return d


def both(wipo_dir) -> Index:
    return Index(extra={"wipo": wipo_dir})


def test_a_second_corpus_leaves_the_first_ones_search_unchanged(wipo_dir):
    alone, two = Index(), both(wipo_dir)
    assert two.corpora == ["ipa", "wipo"] and len(two.chunks) == len(CHUNKS) + len(WIPO_CHUNKS)
    emb = FakeEmbedder()
    for q in ("patent filings small firms", "design rights", "copyright registration"):
        qv = emb.embed([q], "fake", 8)
        a, _ = alone.search([q], qv, allowed=alone.allowed())
        b, _ = two.search([q], qv, allowed=two.allowed())  # off: the first corpus only
        assert [(s.row, s.merged_score) for s in a] == [(s.row, s.merged_score) for s in b]
        assert all(two.chunks[s.row]["corpus"] == "ipa" for s in b)
    # Each corpus keeps its own keyword statistics: the first corpus's scores are its own index's.
    own = BM25.build([r["embed_text"] for r in two.chunks[: len(CHUNKS)]])
    assert np.allclose(two.bm25.scores("patent filings")[: len(CHUNKS)], own.scores("patent filings"))
    assert two.bm25.matched_terms("patent filings", len(CHUNKS)) == ["file", "patent"]


def test_corpora_must_share_an_embedder_and_never_share_a_doc_id(wipo_dir, tmp_path):
    clash = build_index(tmp_path / "clash", CHUNKS[:1], {"doc-a": DOCS["doc-a"]})
    with pytest.raises(RuntimeError, match="doc_ids already"):
        Index(extra={"wipo": clash})


def test_selection_keeps_twenty_and_more_only_when_they_are_useful():
    rows = list(range(10))
    ratings = {0: 3, 1: 0, 2: 2, 3: 2, 4: 1, 5: 3, 6: 2, 7: 0, 8: 1, 9: 2}
    # keep_min 3: the three rated highest (3, 3, 2 in search order on ties)...
    assert pipeline.by_rating_upto(rows, ratings, 3, 3, 2) == [0, 5, 2]
    # ...then every further one rated 2 or more, up to keep_max.
    assert pipeline.by_rating_upto(rows, ratings, 3, 10, 2) == [0, 5, 2, 3, 6, 9]
    assert pipeline.by_rating_upto(rows, ratings, 3, 5, 2) == [0, 5, 2, 3, 6]
    # Nothing rated useful beyond the minimum: the minimum, as now.
    assert pipeline.by_rating_upto(rows, {0: 3}, 2, 8, 2) == [0, 1]


def test_interleaving_takes_the_corpora_in_turn():
    assert pipeline.interleave([["a", "b", "c"], ["x"]]) == [(0, 0), (1, 0), (0, 1), (0, 2)]


def test_with_wipo_off_the_question_runs_exactly_as_before(wipo_dir):
    m1, m2 = ScriptedModel(good_answer), ScriptedModel(good_answer)
    req = pipeline.Request(question="patent filings small firms")
    one = list(
        pipeline.run(
            req, pipeline.Services(index=Index(), embedder=FakeEmbedder(), model=m1, provider=PROVIDER)
        )
    )
    two = list(
        pipeline.run(
            req, pipeline.Services(index=both(wipo_dir), embedder=FakeEmbedder(), model=m2, provider=PROVIDER)
        )
    )
    r1 = next(e for e in one if e["event"] == "retrieval")
    r2 = next(e for e in two if e["event"] == "retrieval")
    assert [e["chunk_id"] for e in r1["pool"]] == [e["chunk_id"] for e in r2["pool"]]
    assert r2["corpora"] == ["ipa"]
    # The model saw the same prompts, byte for byte (no publisher attribute, the single-corpus versions).
    assert [(c["system"], c["user"]) for c in m1.calls] == [(c["system"], c["user"]) for c in m2.calls]
    assert "publisher=" not in "".join(c["user"] for c in m2.calls)


def test_with_wipo_on_each_corpus_gives_its_own_passages_and_the_filter_reads_them_all(wipo_dir, monkeypatch):
    s = config.service()
    cc = s.answer.combined.model_copy(update={"read_per_corpus": 6, "keep_min": 2, "keep_max": 4})
    s2 = s.model_copy(update={"answer": s.answer.model_copy(update={"combined": cc})})
    monkeypatch.setattr(pipeline.config, "service", lambda: s2)

    def fn(schema_name, user):
        if schema_name == "grades":  # two essential passages, one useful from each corpus, the rest not
            return rate_all(user, 0, (("Copyright", 3), ("visual appearance", 2), ("class counts", 2)))
        return good_answer(schema_name, user)

    m = ScriptedModel(fn)
    svc = pipeline.Services(index=both(wipo_dir), embedder=FakeEmbedder(), model=m, provider=PROVIDER)
    evs = list(pipeline.run(pipeline.Request(question="copyright and designs", corpora=["wipo"]), svc))
    ev = {e["event"]: e for e in evs}
    assert ev["meta"]["corpora"] == ["ipa", "wipo"] and ev["meta"]["prompt"] == cc.prompt
    r = ev["retrieval"]
    pool = r["pool"]
    # Each corpus's own passages (six and four), taken in turn, each ranked within its own corpus.
    assert [p["corpus"] for p in pool] == ["ipa", "wipo"] * 4 + ["ipa", "ipa"]
    assert [p["search_rank"] for p in pool] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 6]
    assert r["filter"]["read"] == 10
    # The two rated 3, then the ones rated 2 (up to keep_max), in rating order.
    texts = [e["text"] for e in r["evidence"]]
    assert len(texts) == 4 and all("Copyright" in t for t in texts[:2])
    assert {e["corpus"] for e in r["evidence"]} == {"ipa", "wipo"}
    assert next(e for e in r["evidence"] if e["corpus"] == "wipo")["publisher"] == "Gamma Org"
    # The combined prompts, with each passage's publisher named.
    systems = {c["schema_name"]: c["system"] for c in m.calls}
    assert systems["grades"] == pipeline.prompts.load(cc.filter_prompt)
    assert systems["plan"] == pipeline.prompts.load(cc.plan_prompt)
    assert systems["answer"] == pipeline.prompts.load(cc.prompt)
    grades_user = next(c["user"] for c in m.calls if c["schema_name"] == "grades")
    assert 'publisher="Gamma Org"' in grades_user and 'publisher="Test"' in grades_user
    answer_user = next(c["user"] for c in m.calls if c["schema_name"] == "answer")
    assert answer_user.count("<evidence n=") == 4 and 'publisher="Gamma Org"' in answer_user
    assert {t["corpus"] for t in r["traces"]} == {"ipa", "wipo"}


def test_a_failed_filter_with_wipo_on_keeps_the_minimum_in_turn(wipo_dir, monkeypatch):
    s = config.service()
    cc = s.answer.combined.model_copy(update={"read_per_corpus": 3, "keep_min": 4, "keep_max": 6})
    s2 = s.model_copy(update={"answer": s.answer.model_copy(update={"combined": cc})})
    monkeypatch.setattr(pipeline.config, "service", lambda: s2)

    def fn(schema_name, user):
        return {"grades": []} if schema_name == "grades" else good_answer(schema_name, user)

    svc = pipeline.Services(
        index=both(wipo_dir), embedder=FakeEmbedder(), model=ScriptedModel(fn), provider=PROVIDER
    )
    ev = {e["event"]: e for e in pipeline.run(pipeline.Request(question="patents", corpora=["wipo"]), svc)}
    r = ev["retrieval"]
    assert r["filter"]["status"].startswith("failed")
    assert [e["corpus"] for e in r["evidence"]] == ["ipa", "wipo", "ipa", "wipo"]


def test_the_service_offers_wipo_only_when_its_index_exists(index_dir, wipo_dir, monkeypatch, tmp_path):
    from econ.service.app import create_app

    on = TestClient(create_app()).get("/api/health").json()["corpora"]
    assert [(c["name"], c["available"]) for c in on] == [("ipa", True), ("wipo", True)]
    assert on[1]["chunks"] == len(WIPO_CHUNKS) and on[1]["documents"] == 2
    monkeypatch.setenv("ECON_INDEX_DIR_WIPO", str(tmp_path / "nothing-here"))
    client = TestClient(create_app())
    assert [c["available"] for c in client.get("/api/health").json()["corpora"]] == [True, False]
    r = client.post("/api/ask?stream=false", json={"question": "patent filings", "corpora": ["wipo"]})
    assert r.status_code == 400 and "wipo" in r.json()["detail"]


def test_the_service_answers_with_wipo_on(wipo_dir):
    from econ.service.app import create_app

    client = TestClient(create_app())
    r = client.post(
        "/api/ask?stream=false", json={"question": "patent filings worldwide", "corpora": ["wipo"]}
    )
    assert r.status_code == 200
    ev = {e["event"]: e for e in r.json()["events"]}
    assert ev["retrieval"]["corpora"] == ["ipa", "wipo"]
    assert {p["corpus"] for p in ev["retrieval"]["pool"]} == {"ipa", "wipo"}


def test_fetch_owns_its_folder_and_the_root_corpus_the_rest():
    keys = ["2015_IP_Report.pdf", "WIPO/wipi-2024.pdf", "WIPO/gii-2025.xlsx", "WIPOX.pdf"]
    assert owned(keys, "WIPO/", ["", "WIPO/"]) == ["WIPO/wipi-2024.pdf", "WIPO/gii-2025.xlsx"]
    assert owned(keys, "", ["WIPO/"]) == ["2015_IP_Report.pdf", "WIPOX.pdf"]


def test_another_corpus_has_its_own_manifests_library_and_registry(monkeypatch):
    assert stage_name("parse") == "parse" and config.library() == config.path("library")
    monkeypatch.setenv("ECON_CORPUS", "wipo")
    assert stage_name("parse") == "wipo/parse"
    assert config.library() == config.path("library/wipo")
    assert config.sources().publisher.startswith("World Intellectual Property Organization")
    assert config.enrichment() == "S384-noprefix-nocite.luna-enrich-wipo-v1"
    assert all(re.match(r"^wipo-", d.doc_id) for d in config.sources().documents)
