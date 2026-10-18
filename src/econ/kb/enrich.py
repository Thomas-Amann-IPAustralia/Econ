"""Contextual enrichment of chunks: a short note per chunk that situates it in its document, used only by
search (BM25 and the dense lane), never shown as evidence (SOP §16.2's optional LLM stage).

The note is written by a small model from the chunk, the document's details and outline, its section and
the text just before it. Notes are cached paid replies (eval/cache/llm) and are collected in
library/enrich/<name>.jsonl. A note with a high-severity text-check finding is dropped, and that chunk is
indexed as before.
"""

from __future__ import annotations

import json

from econ import config, textcheck
from econ.answer import pipeline
from econ.evalr import llmcall
from econ.kb.chunk import load_elements
from econ.manifest import write_text_atomic

PROMPT = "enrich-v1"
SCHEMA = {
    "type": "object",
    "properties": {"context": {"type": "string", "description": "One or two sentences, at most 50 words."}},
    "required": ["context"],
    "additionalProperties": False,
}


def outline(doc_id: str, limit_chars: int = 1600) -> str:
    seen, heads = set(), []
    for e in load_elements(doc_id):
        if e.label != "section_header":
            continue
        h = " ".join(e.text.split())
        if len(h) > 90 or h.lower() in seen:
            continue
        seen.add(h.lower())
        heads.append(h)
    out = " | ".join(heads)
    return out[:limit_chars]


def prompt_text() -> str:
    return (config.ROOT / "prompts" / "eval" / f"{PROMPT}.md").read_text(encoding="utf-8")


def calls(chunks: list[dict], *, model: str, effort: str | None) -> list[llmcall.Call]:
    docs = config.sources().by_id()
    outlines = {d: outline(d) for d in {c["doc_id"] for c in chunks}}
    system = prompt_text()
    out = []
    for i, c in enumerate(chunks):
        d = docs[c["doc_id"]]
        prev = chunks[i - 1]["text"][-700:] if i > 0 and chunks[i - 1]["doc_id"] == c["doc_id"] else ""
        section = " > ".join(c["section"]) if c["section"] else ""
        user = (
            f'<document title="{pipeline.defang(d.title)}" year="{d.year}" series="{pipeline.defang(d.series)}">\n'
            f"<outline>\n{pipeline.defang(outlines[c['doc_id']])}\n</outline>\n"
            f'<passage section="{pipeline.defang(section)}" pages="{c["pages"][0]}-{c["pages"][-1]}">\n'
            f"<preceding>\n{pipeline.defang(prev)}\n</preceding>\n"
            f"{pipeline.defang(c['text'])}\n</passage>\n</document>"
        )
        out.append(
            llmcall.Call(
                model=model,
                system=system,
                user=user,
                schema=SCHEMA,
                schema_name="context_note",
                effort=effort,
                max_output_tokens=600,
                purpose=f"enrich:{PROMPT}:{model}",
                tag=c["chunk_id"],
            )
        )
    return out


def run(
    chunks: list[dict], name: str, *, model: str, effort: str | None, flex: bool, workers: int = 12
) -> dict:
    replies = llmcall.run_many(calls(chunks, model=model, effort=effort), flex=flex, workers=workers)
    rows, dropped, failed = [], 0, 0
    for c, r in zip(chunks, replies, strict=True):
        note = ""
        if "error" in r:
            failed += 1
        else:
            note = " ".join(str(r["data"].get("context", "")).split())
            if textcheck.high(textcheck.scan(note)):
                note, dropped = "", dropped + 1
        rows.append({"chunk_id": c["chunk_id"], "context": note})
    out = config.path("library/enrich") / f"{name}.jsonl"
    write_text_atomic(out, "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows))
    return {"chunks": len(rows), "failed": failed, "dropped": dropped, "file": str(out)}


def load(name: str) -> dict[str, str]:
    p = config.path("library/enrich") / f"{name}.jsonl"
    return {
        r["chunk_id"]: r["context"] for r in (json.loads(x) for x in p.read_text().splitlines() if x.strip())
    }
