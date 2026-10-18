import numpy as np

from econ.kb.bm25 import BM25, tokenize
from econ.retrieval.search import fuse

TEXTS = [
    "patent filings by small firms",
    "trade mark filings and the cycle",
    "design rights",
    "patents patents",
]


def test_tokenize_stems_and_drops_stop_words():
    assert tokenize("The Patents were Filed") == ["patent", "file"]


def test_bm25_scores_save_and_load_identically(tmp_path):
    b = BM25.build(TEXTS)
    s = b.scores("patent filings")
    assert s[0] > s[1] > s[2] == 0
    b.save(tmp_path / "b.npz")
    b2 = BM25.load(tmp_path / "b.npz")
    assert np.allclose(s, b2.scores("patent filings"))
    assert b2.matched_terms("patent filings", 0) == ["file", "patent"]


def test_bm25_build_is_deterministic():
    a, b = BM25.build(TEXTS), BM25.build(TEXTS)
    assert a.vocab == b.vocab and np.array_equal(a.weights, b.weights)


def test_fuse_combines_lanes_and_records_both():
    dense = np.array([0.1, 0.9, 0.2, 0.0], dtype=np.float32)
    bm = np.array([3.0, 0.0, 0.0, 1.0], dtype=np.float32)
    hits = fuse(dense, bm, k=4, alpha=0.7)
    assert hits[0].row == 1 and hits[0].dense_rank == 1 and hits[0].bm25 is None
    assert {h.row for h in hits} == {0, 1, 2, 3}
    assert next(h for h in hits if h.row == 0).bm25_rank == 1


def test_a_filter_removes_rows_without_changing_scores():
    dense = np.array([0.1, 0.9, 0.2, 0.0], dtype=np.float32)
    allowed = np.array([True, False, True, True])
    hits = fuse(dense, None, k=4, allowed=allowed)
    assert [h.row for h in hits] == [2, 0, 3]


def test_rrf_and_ties_are_stable():
    dense = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    assert [h.row for h in fuse(dense, None, k=3, fusion="rrf")] == [0, 1, 2]


def test_chunks_without_query_terms_are_not_keyword_hits():
    bm = np.array([0.0, 2.0, 0.0], dtype=np.float32)
    assert [h.row for h in fuse(None, bm, k=3)] == [1]
