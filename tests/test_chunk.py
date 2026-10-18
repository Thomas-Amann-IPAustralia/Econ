from econ.config import ChunkStrategy, Document
from econ.evalr import metrics
from econ.evalr.testset import Gold
from econ.kb.chunk import Element, boilerplate, canonical_text, chunk_document, place

DOC = Document(doc_id="doc-a", key="a.pdf", title="Alpha Report", year=2020, series="Test")
LICENCE = "All content in this placeholder publication is provided under a placeholder licence for reuse."


def els(*rows) -> list[Element]:
    out = [
        Element(i, label, text, 1 + i // 3, [{"page": 1 + i // 3, "bbox": [0, i, 10, i + 1]}], level)
        for i, (label, text, level) in enumerate(rows)
    ]
    return place(out)


def body(n: int, word: str) -> str:
    return " ".join(f"{word}{i}." if i % 8 == 7 else f"{word}{i}" for i in range(n))


ELS = [
    ("section_header", "Patents", 1),
    ("text", body(30, "pat"), None),
    ("text", body(30, "pen"), None),
    ("section_header", "Trade marks", 1),
    ("text", body(70, "tm"), None),
    ("text", LICENCE, None),
]


def test_structure_chunks_stay_within_budget_and_sections():
    st = ChunkStrategy(kind="structure", max_tokens=48, min_tokens=5)
    rows = chunk_document(DOC, st, els(*ELS))
    assert all(r["tokens"] <= 48 for r in rows)
    assert all(len({s for s in r["section"]}) <= 1 for r in rows)
    pat = [r for r in rows if r["section"] == ["Patents"]]
    assert pat and all("tm" not in r["text"] for r in pat)
    assert rows[0]["embed_text"].startswith("Alpha Report\nPatents\n\n")


def test_spans_point_into_the_canonical_text():
    e = els(*ELS)
    text = canonical_text(e)
    for st in (
        ChunkStrategy(kind="structure", max_tokens=48),
        ChunkStrategy(kind="fixed", max_tokens=40, overlap_tokens=8, prefix="title"),
    ):
        for r in chunk_document(DOC, st, els(*ELS)):
            for s, t in r["spans"]:
                assert text[s:t].split()[0] in r["text"]


def test_fixed_windows_overlap_and_cover_everything():
    st = ChunkStrategy(kind="fixed", max_tokens=40, overlap_tokens=8, prefix="title")
    rows = chunk_document(DOC, st, els(*ELS))
    assert len(rows) >= 4
    words = set(canonical_text(els(*ELS)).split())
    assert words <= set(" ".join(r["text"] for r in rows).split())


def test_boilerplate_recurring_across_documents_is_skipped_but_keeps_offsets():
    docs = {f"d{i}": els(("text", LICENCE, None), ("text", body(10, f"x{i}"), None)) for i in range(3)}
    skip = boilerplate(docs)
    assert len(skip) == 1
    st = ChunkStrategy(kind="structure", max_tokens=48)
    rows = chunk_document(DOC, st, els(*ELS), skip)
    assert all("placeholder licence" not in r["text"] for r in rows)
    # Offsets still follow the full canonical text, so test-set gold spans don't move.
    full = canonical_text(els(*ELS))
    tm = next(r for r in rows if r["section"] == ["Trade marks"])
    assert full[tm["spans"][0][0] :].startswith("tm0")


def test_metrics_reward_novel_gold_coverage_within_a_token_budget():
    golds = (Gold("doc-a", 0, 100, "x"), Gold("doc-a", 200, 300, "y"))
    ranked = [
        {"doc_id": "doc-a", "spans": [[0, 100]], "tokens": 500},
        {"doc_id": "doc-a", "spans": [[0, 60]], "tokens": 500},  # same gold again: no new gain
        {"doc_id": "doc-a", "spans": [[180, 320]], "tokens": 3500},
    ]
    m = metrics.per_need(ranked, golds)
    assert m["mrr@10"] == 1.0
    assert m["recall@1k_tok"] == 0.5 and m["recall@4k_tok"] == 0.5 and m["recall@8k_tok"] == 1.0
    assert 0.5 < m["ndcg@10"] < 1.0


def test_a_long_table_splits_by_rows_and_repeats_its_header():
    rows = "\n".join(f"| r{i} | v{i} w{i} x{i} |" for i in range(40))
    table = f"Table 9: Placeholder\n\n| row | value |\n|---|---|\n{rows}"
    st = ChunkStrategy(kind="structure", max_tokens=60)
    out = chunk_document(DOC, st, els(("section_header", "Data", 1), ("table", table, None)))
    assert len(out) > 2 and all(
        r["text"].startswith("Table 9: Placeholder\n\n| row | value |\n|---|---|") for r in out
    )
    full = canonical_text(els(("section_header", "Data", 1), ("table", table, None)))
    for r in out:
        s, e = r["spans"][0]
        assert full[s:e] in r["text"]


def test_a_gold_with_alternatives_is_covered_by_any_of_them():
    item = (Gold("doc-a", 0, 100, "x"), Gold("doc-b", 0, 100, "y"))
    m = metrics.per_need([{"doc_id": "doc-b", "spans": [[0, 100]], "tokens": 10}], (item,))
    assert m["recall@10"] == 1.0 and m["doc_hit@5"] == 1.0


def test_definitions_restated_in_body_text_are_not_boilerplate():
    # Front matter recurs on page 1; a definition recurs on page 6 of each document: only the first goes.
    definition = "Copyright is a placeholder unregistered right that protects the expression of an idea here."
    docs = {}
    for i in range(3):
        rows = [("text", LICENCE, None)] + [("text", body(5, f"f{i}{j}"), None) for j in range(15)]
        rows += [("text", definition, None)] + [("text", body(5, f"g{i}{j}"), None) for j in range(9)]
        docs[f"d{i}"] = els(*rows)
    skip = boilerplate(docs)
    assert len(skip) == 1 and "placeholderlicence" in next(iter(skip))
