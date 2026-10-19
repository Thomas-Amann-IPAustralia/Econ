"""Citations by sentence (D-026): the splitter, the numbered passages, and claims built by code."""

import re

from econ.answer import cite, pipeline
from econ.answer.providers import ScriptedModel
from econ.answer.schema import AnswerV5
from econ.config import service
from econ.retrieval.index import Index
from tests.conftest import FakeEmbedder
from tests.test_pipeline import PROVIDER, good_answer, with_answer

TEXT = (
    "Lorem ipsum rose 5 per cent, e.g. in dolor sit. Amet consectetur fell (see Fig. 2).\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\nDr. Smith said so. 2021 was a high year."
)


def test_sentences_split_at_ends_and_lines_but_not_abbreviations_or_table_rules():
    got = [TEXT[a:b] for a, b in cite.sentences(TEXT)]
    assert got == [
        "Lorem ipsum rose 5 per cent, e.g. in dolor sit.",
        "Amet consectetur fell (see Fig. 2).",
        "| a | b |",
        "| 1 | 2 |",
        "Dr. Smith said so.",
        "2021 was a high year.",
    ]


def test_numbered_passages_keep_the_text_and_layout():
    body, table = cite.numbered(3, TEXT, lambda s: s)
    assert body.startswith("[3.1] Lorem ipsum") and "\n\n[3.3] | a | b |\n|---|---|\n[3.4] | 1 | 2 |" in body
    assert table[2] == "Amet consectetur fell (see Fig. 2)." and len(table) == 6
    # Without the ids the passage is unchanged.
    assert re.sub(r"\[3\.\d+\] ", "", body) == TEXT


def test_build_turns_sentence_ids_into_claims_with_exact_quotes():
    table = {(1, 1): "Filings rose sharply.", (1, 2): "Small firms led.", (2, 1): "Designs grew."}
    ans = AnswerV5(
        coverage="complete",
        answer="**Filings rose** [1.1][1.2]. Designs grew too [2.1].\n- Again, filings rose [1.2][1.1].",
        gaps=[],
        follow_ups=["Why?"],
    )
    built, errors = cite.build(ans, table)
    assert not errors
    assert built.answer == "**Filings rose** [1]. Designs grew too [2].\n- Again, filings rose [3]."
    assert [c.text for c in built.claims] == ["Filings rose", "Designs grew too", "Again, filings rose"]
    assert [q.quote for q in built.claims[0].citations] == ["Filings rose sharply.", "Small firms led."]
    assert built.follow_ups == ["Why?"]
    # A claim's text never carries another claim's ids.
    two = AnswerV5(coverage="complete", answer="It rose. [1.1] It mattered. [1.2]", gaps=[], follow_ups=[])
    assert [c.text for c in cite.build(two, table)[0].claims] == ["It rose.", "It mattered."]


def test_build_reports_ids_that_were_not_shown_and_bare_markers():
    ans = AnswerV5(coverage="partial", answer="Rose [1.9] and fell [2].", gaps=["x"], follow_ups=[])
    built, errors = cite.build(ans, {(1, 1): "Rose."})
    assert any("[1.9], which was not shown" in e for e in errors)
    assert any("[2]" in e and "[2.1]" in e for e in errors)
    assert built.claims == []


def sentence_answer(schema_name, user):
    if schema_name != "answer":
        return good_answer(schema_name, user)
    n = (
        user.split("patent filings rose sharply among small firms")[0]
        .rsplit('<evidence n="', 1)[1]
        .split('"')[0]
    )
    return {
        "coverage": "complete",
        "answer": f"Small firms filed many more patents [{n}.1].",
        "gaps": [],
        "follow_ups": ["Which industries?"],
    }


def test_answer_v5_end_to_end_quotes_come_from_the_passage(index_dir, monkeypatch):
    with_answer(monkeypatch, prompt="answer-v5", stream_drafts=True)
    m = ScriptedModel(sentence_answer)
    svc = pipeline.Services(index=Index(), embedder=FakeEmbedder(), model=m, provider=PROVIDER)
    evs = list(pipeline.run(pipeline.Request(question="Did small firms patent more?"), svc))
    answer = next(e for e in evs if e["event"] == "answer")
    check = next(e for e in evs if e["event"] == "check")
    assert (
        answer["citations_by"] == "sentence"
        and answer["answer"] == "Small firms filed many more patents [1]."
    )
    quote = answer["claims"][0]["citations"][0]["quote"]
    assert "patent filings rose sharply among small firms" in quote
    assert check["passed"] and check["claims"][0]["citations"][0]["found"] and evs[-1]["outcome"] == "passed"
    # The model saw numbered sentences; the draft streamed the raw ids.
    call = [c for c in m.calls if c["schema_name"] == "answer"][0]["user"]
    assert "] " in call and cite.IDS.search(call)
    assert "".join(e.get("text", "") for e in evs if e["event"] == "draft").endswith(".1].")


def test_answer_v5_retries_when_it_cites_a_sentence_it_was_not_shown(index_dir, monkeypatch):
    with_answer(monkeypatch, prompt="answer-v5", stream_drafts=False)

    def fn(schema_name, user):
        a = sentence_answer(schema_name, user)
        if schema_name == "answer":
            a["answer"] = "Small firms filed more [1.99]."
        return a

    m = ScriptedModel(fn)
    svc = pipeline.Services(index=Index(), embedder=FakeEmbedder(), model=m, provider=PROVIDER)
    evs = list(pipeline.run(pipeline.Request(question="Did small firms patent more?"), svc))
    checks = [e for e in evs if e["event"] == "check"]
    assert len(checks) == 2 and not checks[-1]["passed"] and evs[-1]["outcome"] == "flagged"
    assert "[1.99], which was not shown" in checks[0]["errors"][0]
    assert "<errors>" in [c for c in m.calls if c["schema_name"] == "answer"][1]["user"]


def test_the_served_prompt_is_locked_with_its_schema():
    from econ.answer import prompts

    p = service().answer.prompt
    assert prompts.load(p) and prompts.schema_for(p).__name__ in ("AnswerV3", "AnswerV5")
