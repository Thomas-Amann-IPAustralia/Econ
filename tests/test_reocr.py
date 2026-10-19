"""Repairing garbled OCR (D-022): which elements count as garbled, and when a re-read stands."""

from econ.ingest import reocr

VOCAB = reocr.vocabulary(
    [
        "with an average annual application growth of around per cent during china has been the main "
        "driver of this world growth in patent filing margaret river"
    ]
)
CLEAN = "With an average annual application growth of around 23 per cent during 2010-16, China has been the main driver"
GARBLED = "Wi aunh a u o r avo nn ann n anng 2010-16, China has been the main driver"


def row(text, seq=0, label="text"):
    return {"seq": seq, "page": 3, "label": label, "text": text, "boxes": [{"page": 3, "bbox": [1, 2, 3, 4]}]}


def test_garbled_runs_are_found_and_clean_text_is_not():
    assert reocr.garbled_words(GARBLED, VOCAB) >= 3
    assert reocr.garbled_words(CLEAN, VOCAB) == 0
    # Two unknown words in a row (a name) are not a run.
    assert reocr.garbled_words("the main driver Zhang Wei of growth", VOCAB) == 0


def test_a_clean_re_read_replaces_the_garbled_text_and_says_so():
    rows = [row(GARBLED)]
    rep = reocr.repair(rows, VOCAB, lambda page, bbox, v: CLEAN, min_agreement=0.8)
    assert rows[0]["text"] == CLEAN and rows[0]["reocr"] is True
    assert rep[0]["repaired"] and rep[0]["garbled_after"] == 0 and rep[0]["old"] == GARBLED


def test_a_re_read_that_loses_the_paragraph_is_refused():
    rows = [row(GARBLED)]
    rep = reocr.repair(rows, VOCAB, lambda page, bbox, v: "With an average annual", min_agreement=0.8)
    assert rows[0]["text"] == GARBLED and "reocr" not in rows[0]
    assert not rep[0]["repaired"] and rep[0]["agreement"] < 0.8


def test_a_name_that_reads_the_same_is_left_alone():
    text = "the main driver Xq Zv Wb Yk of growth"
    rows = [row(text)]
    rep = reocr.repair(rows, VOCAB, lambda page, bbox, v: text, min_agreement=0.8)
    assert rows[0]["text"] == text and not rep[0]["repaired"]


def test_the_cleanest_acceptable_variant_wins():
    rows = [row(GARBLED)]
    reads = [GARBLED.replace("Wi", "Wo"), CLEAN, CLEAN.replace("With", "Wiith")]
    rep = reocr.repair(rows, VOCAB, lambda page, bbox, v: reads[v], variants=3, min_agreement=0.8)
    assert rows[0]["text"] == CLEAN and rep[0]["reader"] == "rapidocr:1"


def test_the_model_reads_only_what_no_variant_repairs_and_must_pass_the_same_rule():
    asked = []

    def model(page, bbox):
        asked.append(page)
        return CLEAN

    # A reader that fails everywhere, so only the model can repair.
    rows = [row(GARBLED)]
    rep = reocr.repair(
        rows, VOCAB, lambda page, bbox, v: GARBLED, min_agreement=0.8, fallback=model, fallback_name="vision"
    )
    assert rows[0]["text"] == CLEAN and rep[0]["reader"] == "vision" and asked == [3]
    asked.clear()
    rows = [row(GARBLED)]
    reocr.repair(
        rows, VOCAB, lambda page, bbox, v: CLEAN, min_agreement=0.8, fallback=model, fallback_name="vision"
    )
    assert asked == []  # a variant stood, so the model was never asked
    rows = [row(GARBLED)]
    rep = reocr.repair(
        rows,
        VOCAB,
        lambda page, bbox, v: GARBLED,
        min_agreement=0.8,
        fallback=lambda p, b: "With an average",
        fallback_name="vision",
    )
    assert rows[0]["text"] == GARBLED and not rep[0]["repaired"]  # the model's reading lost the paragraph


def test_pure_noise_is_replaced_by_a_clean_reading():
    rows = [row("nddt t d ppe xq")]
    rep = reocr.repair(rows, VOCAB, lambda page, bbox, v: "China has been the main driver", min_agreement=0.8)
    assert rep[0]["agreement"] is None and rep[0]["repaired"]


def test_clean_elements_and_tables_are_never_re_read():
    calls = []

    def reader(page, bbox, v):
        calls.append(page)
        return CLEAN

    rows = [row(CLEAN, 0), row("| Wi | aunh a u o r |", 1, label="table")]
    assert reocr.repair(rows, VOCAB, reader, min_agreement=0.8) == [] and calls == []
