"""One question, start to finish, as a stream of events the UI renders as they arrive.

  meta -> plan -> search -> retrieval -> answer -> check -> done     (an answer model and the filter)
  meta -> plan -> retrieval -> answer -> check -> done               (an answer model, no filter)
  meta -> retrieval -> done                                          (evidence-only mode)

- plan: a small model rewrites a follow-up to stand alone and splits a broad question into searches.
  Without a model, the search query is the question (with the previous question when there is history).
- search and the filter (D-018 to D-020): every query is embedded in one call to the Cloud Run embedder;
  if that fails, search runs on the keyword lane alone and the event says so. With the filter, search keeps
  its first 60 passages (the `search` event says so while the filter reads), a small model rates each 0-3,
  and the answer model gets the 20 rated highest. If the filter fails, the search's top 20 go forward and
  the event says why.
- retrieval: `evidence` is exactly what the answer model sees; `pool` is every passage the filter read,
  in search order, with its search rank, its rating and whether it was chosen (a chosen passage's entry is
  brief and names its evidence number `n`; its text is in `evidence`).
- answer and check: a failed check goes back to the model once, with its errors wrapped as data. An
  answer that still fails is returned flagged, never passed silently.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import ValidationError

from econ import config, textcheck
from econ.answer import prompts
from econ.answer.check import check
from econ.answer.providers import Model, ProviderError, Usage
from econ.answer.schema import Answer, Grades, Plan, strict_schema
from econ.kb.bm25 import tokenize
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


def rerank_query(question: str, context: str) -> str:
    """What the reranker compares passages with: the (standalone) question, plus pasted material's headings,
    since a question like "does the knowledge base agree with this?" says nothing about its topic."""
    heads = context_queries(context, 3)
    return " ".join([question, *heads]) if heads else question


def rerank_step(svc: Services, ranked: list, query: str) -> dict:
    """Reorder the first stage's top candidates with the adopted cross-encoder (D-012). If the reranker
    fails, the first-stage order stands and the event says so, as the keyword fallback does for search."""
    rc = config.pipeline().reranking
    if not rc.adopted or not ranked:
        return {"model": None, "status": "off"}
    if not getattr(svc.embedder, "configured", False):
        return {"model": rc.adopted, "status": "not configured; first-stage order"}
    head = ranked[: rc.depth]
    try:
        scores = svc.embedder.rerank(query, [svc.index.chunks[s.row]["text"] for s in head], rc.adopted)
    except Exception as e:  # noqa: BLE001 - any failure keeps the first-stage order, visibly
        return {"model": rc.adopted, "status": f"unavailable ({type(e).__name__}); first-stage order"}
    return {
        "model": rc.adopted,
        "status": "ok",
        "depth": len(head),
        "ranked": svc.index.reorder(ranked, scores, rc.depth),
    }


def evidence_block(n: int, chunk: dict, doc: dict) -> str:
    pages = chunk["pages"]
    pg = f"{pages[0]}" if len(pages) == 1 else f"{pages[0]}-{pages[-1]}"
    section = " > ".join(chunk["section"]) if chunk["section"] else ""
    return (
        f'<evidence n="{n}" document="{defang(doc["title"])}" year="{doc["year"]}" '
        f'section="{defang(section)}" pages="{pg}">\n{defang(chunk["text"])}\n</evidence>'
    )


# --- the relevance filter (D-018 to D-020) ---------------------------------------------------------------


def filter_block(pid: str, chunk: dict, doc: dict) -> str:
    section = " > ".join(chunk["section"]) if chunk["section"] else ""
    return (
        f'<evidence id="{pid}" document="{defang(doc["title"])}" year="{doc["year"]}" '
        f'section="{defang(section)}">\n{defang(chunk["text"])}\n</evidence>'
    )


def filter_user(question: str, blocks: list[str]) -> str:
    """The filter's user message: the question, then the passages (exactly as measured, D-018)."""
    return f"<question>{defang(question)}</question>\n\n" + "\n\n".join(blocks)


def parse_grades(data: object, ids: dict[str, int]) -> dict[int, int] | None:
    """Row -> rating from a filter reply, or None unless it rates every id it was shown exactly once, 0-3."""
    try:
        reply = Grades.model_validate(data)
    except ValidationError:
        return None
    got = [(g.id, g.grade) for g in reply.grades]
    if sorted(i for i, _ in got) != sorted(ids):
        return None
    return {ids[i]: g for i, g in got}


def by_rating(rows: list[int], ratings: dict[int, int], k: int) -> list[int]:
    """Positions in `rows` of the k rated highest; ties keep the search order (the rule measured, D-018)."""
    return sorted(range(len(rows)), key=lambda i: (-ratings.get(rows[i], 0), i))[:k]


def filter_step(svc: Services, question: str, pool: list) -> dict:
    """Rate the pool's passages with the provider's filter model, the config's group size a call, the calls in
    parallel. Any failed or malformed reply drops every rating, so the search order stands, visibly."""
    fc = config.service().answer.filter
    p = svc.provider
    system = prompts.load(fc.prompt)
    calls = []
    for g in range(0, len(pool), fc.group):
        part = pool[g : g + fc.group]
        ids = {f"p{g + i + 1}": s.row for i, s in enumerate(part)}
        blocks = [
            filter_block(pid, svc.index.chunks[row], svc.index.docs[svc.index.chunks[row]["doc_id"]])
            for pid, row in ids.items()
        ]
        calls.append((filter_user(question, blocks), ids))

    def one(call: tuple[str, dict[str, int]]) -> tuple[dict[int, int] | None, Usage | None, str | None]:
        user, ids = call
        try:
            rep = svc.model.generate_json(
                system=system,
                user=user,
                schema=strict_schema(Grades),
                schema_name="grades",
                model=p.filter_model,
                effort=p.filter_effort,
                max_output_tokens=fc.max_output_tokens,
            )
        except ProviderError as e:
            return None, e.usage, str(e)[:160]  # a failed call can still be billed, so it is still metered
        got = parse_grades(rep.data, ids)
        return got, rep.usage, None if got is not None else "a reply did not rate every passage exactly once"

    with ThreadPoolExecutor(max_workers=max(1, len(calls))) as ex:
        results = list(ex.map(one, calls))
    usages = [u for _, u, _ in results if u is not None]
    errors = [e for _, _, e in results if e]
    if errors:
        return {
            "model": p.filter_model,
            "status": f"failed ({errors[0]}); search order kept",
            "usages": usages,
        }
    ratings = {row: g for got, _, _ in results for row, g in got.items()}
    return {"model": p.filter_model, "status": "ok", "usages": usages, "ratings": ratings}


def evidence_view(svc: Services, sel, n: int | None, queries: list[str]) -> dict:
    c = svc.index.chunks[sel.row]
    d = svc.index.docs[c["doc_id"]]
    # Matched terms highlight the passage, so only terms in its own text count (a context note, D-013, can
    # match terms the passage doesn't contain).
    own = set(tokenize(c["text"]))
    terms = sorted({t for q in queries for t in svc.index.bm25.matched_terms(q, sel.row) if t in own})
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
        "rerank_score": sel.rerank_score,
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
    planned = False
    prev = ""
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
                standalone = plan.standalone_question.strip() or question
                queries = (
                    [standalone, *[q for q in qs if q != standalone]]
                    if scfg.answer.plan_keeps_question
                    else qs
                )
                planned = True
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
    # The reranker compares passages with the question as asked (as measured, D-012); in a conversation, with
    # the planner's standalone rewrite, or without a planner, the previous question and this one.
    asked = (standalone if planned else f"{prev} {question}".strip()) if req.history else question
    rerank = rerank_step(svc, ranked, rerank_query(asked, req.context))
    if rerank.get("ranked") is not None:
        ranked = rerank.pop("ranked")
    for tr in traces:
        for h in tr["hits"]:
            h["chunk_id"] = svc.index.chunks[h["row"]]["chunk_id"]
    fc = scfg.answer.filter
    filtering = bool(svc.model and fc and getattr(p, "filter_model", None))
    pool = svc.index.context(ranked, fc.read if filtering else None)
    timings["search"] = round(time.time() - t, 3)

    # --- the relevance filter ------------------------------------------------------------------------
    keep = config.pipeline().retrieval.context_chunks
    ratings: dict[int, int] = {}
    if filtering:
        yield {"event": "search", "candidates": len(ranked), "read": len(pool), "dense": dense_status}
        t = time.time()
        f = filter_step(svc, standalone, pool)
        usages.extend(f.pop("usages"))
        ratings = f.pop("ratings", {})
        timings["filter"] = round(time.time() - t, 2)
        order = by_rating([s.row for s in pool], ratings, keep) if ratings else list(range(len(pool)))[:keep]
        filt = {**f, "read": len(pool), "kept": len(order), "seconds": timings["filter"]}
    else:
        order = list(range(len(pool)))
        reason = (
            "no answer model" if not svc.model else ("off" if not fc else "this provider has no filter model")
        )
        filt = {"model": None, "status": f"off ({reason})", "read": len(pool), "kept": len(pool)}
    chosen = [pool[i] for i in order]
    # Every passage read, with its search rank and rating; the chosen ones are the evidence, numbered in the
    # order the answer model sees them.
    pool_views = [
        {**evidence_view(svc, s, None, queries), "search_rank": i + 1, "filter_grade": ratings.get(s.row)}
        for i, s in enumerate(pool)
    ]
    evidence = []
    for k, i in enumerate(order):
        pool_views[i]["n"] = k + 1
        evidence.append(dict(pool_views[i]))
    # A chosen passage is in full in `evidence`; its pool entry keeps what identifies it and its number.
    brief = ("n", "chunk_id", "doc_id", "title", "year", "section", "pages", "search_rank", "filter_grade")
    pool_views = [{k: v[k] for k in brief} if v["n"] is not None else v for v in pool_views]
    for v in pool_views:
        v["selected"] = v["n"] is not None
    yield {
        "event": "retrieval",
        "queries": queries,
        "dense": dense_status,
        "rerank": rerank,
        "filter": filt,
        "traces": traces,
        "evidence": evidence,
        "pool": pool_views,
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
