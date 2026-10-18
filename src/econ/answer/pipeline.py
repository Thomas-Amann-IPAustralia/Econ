"""One question, start to finish, as a stream of events the UI renders as they arrive.

  meta -> plan -> retrieval -> answer -> check -> done        (an answer model is configured)
  meta -> retrieval -> done                                    (evidence-only mode)

- plan: a small model rewrites a follow-up to stand alone and splits a broad question into searches.
  Without a model, the search query is the question (with the previous question when there is history).
- retrieval: every query is embedded in one call to the Cloud Run embedder; if that fails, search runs
  on the keyword lane alone and the event says so. The evidence list is exactly what the model sees.
- answer and check: a failed check goes back to the model once, with its errors wrapped as data. An
  answer that still fails is returned flagged, never passed silently.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from pydantic import ValidationError

from econ import config, textcheck
from econ.answer import prompts
from econ.answer.check import check
from econ.answer.providers import Model, ProviderError, Usage
from econ.answer.schema import Answer, Plan, strict_schema
from econ.retrieval.index import EmbedderClient, Index

_TAG = re.compile(r"<\s*(/?)\s*(evidence|context|conversation|question|errors|system|instructions?)\b", re.I)


def defang(text: str) -> str:
    """Stop source text from opening or closing the prompt's blocks."""
    return _TAG.sub(lambda m: f"‹{m.group(1)}{m.group(2)}", text)


@dataclass
class Request:
    question: str
    history: list[dict] = field(default_factory=list)  # [{"role": "user"|"assistant", "text": ...}]
    context: str = ""
    doc_ids: list[str] | None = None
    years: tuple[int, int] | None = None


@dataclass
class Services:
    index: Index
    embedder: EmbedderClient
    model: Model | None = None
    provider: object | None = None


def _history_block(history: list[dict]) -> str:
    turns = config.service().limits.max_history_turns
    lines = [f"{h['role']}: {defang(h['text'][:1500])}" for h in history[-turns:]]
    return "<conversation>\n" + "\n".join(lines) + "\n</conversation>\n\n" if lines else ""


def _context_block(context: str) -> str:
    return f"<context>\n{defang(context)}\n</context>\n\n" if context.strip() else ""


def context_queries(context: str, k: int) -> list[str]:
    """Markdown headings in pasted material, as extra searches (the fallback when no model plans)."""
    heads = []
    for line in context.splitlines():
        m = re.match(r"^#{1,4}\s+(\S.*)$", line.strip())
        if m:
            h = re.sub(r"[*_`]", "", m.group(1)).strip()[:160]
            if h and h not in heads and not textcheck.high(textcheck.scan(h)):
                heads.append(h)
    return heads[:k]


def evidence_block(n: int, chunk: dict, doc: dict) -> str:
    pages = chunk["pages"]
    pg = f"{pages[0]}" if len(pages) == 1 else f"{pages[0]}-{pages[-1]}"
    section = " > ".join(chunk["section"]) if chunk["section"] else ""
    return (
        f'<evidence n="{n}" document="{defang(doc["title"])}" year="{doc["year"]}" '
        f'section="{defang(section)}" pages="{pg}">\n{defang(chunk["text"])}\n</evidence>'
    )


def evidence_view(svc: Services, sel, n: int, queries: list[str]) -> dict:
    c = svc.index.chunks[sel.row]
    d = svc.index.docs[c["doc_id"]]
    terms = sorted({t for q in queries for t in svc.index.bm25.matched_terms(q, sel.row)})
    return {
        "n": n,
        "chunk_id": c["chunk_id"],
        "doc_id": c["doc_id"],
        "title": d["title"],
        "year": d["year"],
        "series": d["series"],
        "licence": d.get("licence"),
        "ocr": d.get("ocr", False),
        "note": d.get("note"),
        "url": d.get("url"),
        "section": c["section"],
        "pages": c["pages"],
        "boxes": c["boxes"],
        "text": c["text"],
        "tokens": c["tokens"],
        "merged_rank": sel.merged_rank,
        "merged_score": sel.merged_score,
        "per_query": {str(k): v for k, v in sel.per_query.items()},
        "matched_terms": terms,
    }


def run(req: Request, svc: Services) -> Iterator[dict]:
    started = time.time()
    scfg = config.service()
    usages: list[Usage] = []
    timings: dict[str, float] = {}
    request_id = uuid.uuid4().hex[:12]
    mode = "answer" if svc.model else "evidence_only"
    p = svc.provider
    yield {
        "event": "meta",
        "request_id": request_id,
        "mode": mode,
        "provider": getattr(p, "name", None),
        "answer_model": getattr(p, "answer_model", None),
        "plan_model": getattr(p, "plan_model", None),
        "index": {k: svc.index.meta[k] for k in ("strategy", "embedder", "revision", "chunks", "built_from")},
        "prompt": scfg.answer.prompt if svc.model else None,
    }

    # --- plan --------------------------------------------------------------------------------------
    t = time.time()
    question = req.question.strip()
    queries = [question]
    standalone = question
    if req.history:
        prev = next((h["text"] for h in reversed(req.history) if h["role"] == "user"), "")
        queries = [f"{prev} {question}".strip()]
    # Without a planner, pasted material still steers the search through its own headings.
    queries += context_queries(req.context, scfg.answer.max_queries - 1)
    if svc.model and scfg.llm.query_planning:
        user = (
            _history_block(req.history)
            + _context_block(req.context)
            + f"<question>\n{defang(question)}\n</question>"
        )
        try:
            rep = svc.model.generate_json(
                system=prompts.load(scfg.answer.plan_prompt),
                user=user,
                schema=strict_schema(Plan),
                schema_name="plan",
                model=p.plan_model,
                effort=p.plan_effort,
                max_output_tokens=scfg.llm.plan_max_output_tokens,
            )
            plan = Plan.model_validate(rep.data)
            usages.append(rep.usage)
            qs = [q.strip() for q in plan.queries if q.strip()][: scfg.answer.max_queries]
            if qs and not any(textcheck.high(textcheck.scan(q)) for q in qs):
                queries, standalone = qs, plan.standalone_question.strip() or question
            yield {
                "event": "plan",
                "standalone_question": standalone,
                "queries": queries,
                "usage": rep.usage.__dict__,
            }
        except (ProviderError, ValidationError) as e:
            if getattr(e, "usage", None):
                usages.append(e.usage)  # a failed call is still billed, so it is still metered
            yield {
                "event": "plan",
                "standalone_question": question,
                "queries": queries,
                "error": f"planning failed, searching the question as asked ({str(e)[:160]})",
            }
    timings["plan"] = round(time.time() - t, 2)

    # --- retrieval -----------------------------------------------------------------------------------
    t = time.time()
    qvecs, dense_status = None, "ok"
    if svc.embedder.configured:
        try:
            qvecs = svc.embedder.embed(queries, svc.index.meta["embedder"], svc.index.vecs.shape[1])
        except Exception as e:  # noqa: BLE001 - any failure degrades to the keyword lane, visibly
            dense_status = f"unavailable ({type(e).__name__}); keyword search only"
    else:
        dense_status = "not configured; keyword search only"
    timings["embed"] = round(time.time() - t, 2)
    t = time.time()
    allowed = svc.index.allowed(req.doc_ids, req.years)
    ranked, traces = svc.index.search(queries, qvecs, allowed=allowed)
    chosen = svc.index.context(ranked)
    evidence = [evidence_view(svc, s, i + 1, queries) for i, s in enumerate(chosen)]
    for tr in traces:
        for h in tr["hits"]:
            h["chunk_id"] = svc.index.chunks[h["row"]]["chunk_id"]
    timings["search"] = round(time.time() - t, 3)
    yield {
        "event": "retrieval",
        "queries": queries,
        "dense": dense_status,
        "traces": traces,
        "evidence": evidence,
        "candidates": len(ranked),
    }

    if not svc.model:
        yield {
            "event": "done",
            "mode": mode,
            "usage": [],
            "cost_usd": 0.0,
            "timings": timings,
            "seconds": round(time.time() - started, 2),
            "request_id": request_id,
        }
        return

    # --- answer and check ----------------------------------------------------------------------------
    passages = {e["n"]: {"chunk_id": e["chunk_id"], "text": e["text"]} for e in evidence}
    blocks = "\n\n".join(
        evidence_block(e["n"], svc.index.chunks[chosen[i].row], svc.index.docs[e["doc_id"]])
        for i, e in enumerate(evidence)
    )
    base_user = (
        _history_block(req.history)
        + _context_block(req.context)
        + blocks
        + f"\n\n<question>\n{defang(standalone)}\n</question>"
    )
    a = scfg.answer
    errors_prev: list[str] = []
    final = None
    for attempt in (1, 2):
        t = time.time()
        user = base_user
        if errors_prev:
            user += (
                "\n\nYour previous answer failed these checks. Fix them and answer again.\n<errors>\n"
                + defang("\n".join(errors_prev))
                + "\n</errors>"
            )
        try:
            rep = svc.model.generate_json(
                system=prompts.load(a.prompt),
                user=user,
                schema=strict_schema(Answer),
                schema_name="answer",
                model=p.answer_model,
                effort=p.answer_effort,
                max_output_tokens=scfg.llm.max_output_tokens,
            )
        except ProviderError as e:
            if e.usage:
                usages.append(e.usage)
            yield {"event": "error", "stage": "answer", "message": str(e)[:300]}
            break
        usages.append(rep.usage)
        timings[f"answer_{attempt}"] = round(time.time() - t, 2)
        try:
            ans = Answer.model_validate(rep.data)
        except ValidationError as e:
            errors_prev = [f"the output did not match the answer schema: {str(e)[:300]}"]
            continue
        res = check(
            ans,
            passages,
            min_quote_words=a.min_quote_words,
            quote_claim_ratio=a.quote_claim_ratio,
            max_quote_words=a.max_quote_words,
        )
        final = (ans, res, attempt)
        yield {"event": "answer", "attempt": attempt, **ans.model_dump()}
        yield {"event": "check", "attempt": attempt, **res.as_dict()}
        if res.passed:
            break
        errors_prev = res.errors

    cost = round(sum(u.cost_usd for u in usages), 6)
    outcome = "no_answer" if final is None else ("passed" if final[1].passed else "flagged")
    yield {
        "event": "done",
        "mode": mode,
        "outcome": outcome,
        "attempts": final[2] if final else 0,
        "usage": [u.__dict__ for u in usages],
        "cost_usd": cost,
        "timings": timings,
        "seconds": round(time.time() - started, 2),
        "request_id": request_id,
    }
