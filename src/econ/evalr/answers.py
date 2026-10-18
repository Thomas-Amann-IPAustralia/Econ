"""End-to-end answers on the judged test set: a retrieval setting's context, the service's answer prompt,
the answer check and its one retry, exactly as `econ.answer.pipeline.run` does them.

Paid replies are cached (eval/cache/llm) and metered; each run is summarised in
eval/runs/answers/<run>.jsonl, one line per need: the evidence shown, every attempt, the check's result.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from econ import config
from econ.answer import pipeline, prompts
from econ.answer.check import check
from econ.answer.schema import Answer, strict_schema
from econ.evalr import grid2, llmcall, systems
from econ.evalr.judged import Need
from econ.manifest import write_text_atomic


def evidence(s: systems.System, need: Need) -> list[dict]:
    docs = {d.doc_id: d for d in config.sources().documents}
    out = []
    for i, r in enumerate(grid2.context_rows(s, need)):
        c = systems.chunks()[r]
        d = docs[c["doc_id"]]
        out.append({"n": i + 1, "chunk": c, "doc": {"title": d.title, "year": d.year}})
    return out


def question_for(s: systems.System, need: Need) -> str:
    """The question the answer model sees: the plan's standalone question when the setting plans."""
    standalone, _ = systems.queries_for(need, s.query)
    return standalone if s.query != "raw" else need.question


def answer_user(s: systems.System, need: Need, ev: list[dict]) -> str:
    blocks = "\n\n".join(pipeline.evidence_block(e["n"], e["chunk"], e["doc"]) for e in ev)
    q = question_for(s, need)
    return (
        pipeline._context_block(need.context) + blocks + f"\n\n<question>\n{pipeline.defang(q)}\n</question>"
    )


def run_need(
    s: systems.System, need: Need, *, model: str, effort: str | None, prompt: str, flex: bool, purpose: str
) -> dict:
    scfg = config.service()
    a = scfg.answer
    ev = evidence(s, need)
    passages = {e["n"]: {"chunk_id": e["chunk"]["chunk_id"], "text": e["chunk"]["text"]} for e in ev}
    base_user = answer_user(s, need, ev)
    errors_prev: list[str] = []
    attempts = []
    for attempt in (1, 2):
        user = base_user
        if errors_prev:
            user += (
                "\n\nYour previous answer failed these checks. Fix them and answer again.\n<errors>\n"
                + pipeline.defang("\n".join(errors_prev))
                + "\n</errors>"
            )
        call = llmcall.Call(
            model=model,
            system=prompts.load(prompt),
            user=user,
            schema=strict_schema(Answer),
            schema_name="answer",
            effort=effort,
            max_output_tokens=scfg.llm.max_output_tokens,
            purpose=purpose,
            tag=need.id,
        )
        rep = llmcall.run_one(call, flex=flex)
        if "error" in rep:
            attempts.append({"attempt": attempt, "error": rep["error"]})
            break
        rec = {
            "attempt": attempt,
            "usage": rep["usage"],
            "cost_usd": rep["cost_usd"],
            "cached": rep["cached"],
        }
        try:
            ans = Answer.model_validate(rep["data"])
        except ValidationError as e:
            errors_prev = [f"the output did not match the answer schema: {str(e)[:300]}"]
            attempts.append({**rec, "schema_error": str(e)[:300]})
            continue
        res = check(
            ans,
            passages,
            min_quote_words=a.min_quote_words,
            quote_claim_ratio=a.quote_claim_ratio,
            max_quote_words=a.max_quote_words,
        )
        attempts.append({**rec, "answer": ans.model_dump(), "check": res.as_dict()})
        if res.passed:
            break
        errors_prev = res.errors
    final = next((x for x in reversed(attempts) if "answer" in x), None)
    outcome = "no_answer" if final is None else ("passed" if final["check"]["passed"] else "flagged")
    return {
        "need": need.id,
        "family": need.family,
        "kind": need.kind,
        "split": need.split,
        "setting": s.name,
        "model": model,
        "prompt": prompt,
        "question": question_for(s, need),
        "evidence": [e["chunk"]["chunk_id"] for e in ev],
        "attempts": attempts,
        "outcome": outcome,
        "coverage": final["answer"]["coverage"] if final else None,
        "cost_usd": round(sum(x.get("cost_usd", 0) for x in attempts if not x.get("cached")), 6),
    }


def run(
    name: str,
    s: systems.System,
    needs: list[Need],
    *,
    model: str,
    effort: str | None,
    prompt: str = "answer-v1",
    flex: bool = True,
    workers: int = 6,
) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(
            ex.map(
                lambda n: run_need(
                    s, n, model=model, effort=effort, prompt=prompt, flex=flex, purpose=f"answer:{name}"
                ),
                needs,
            )
        )
    out = config.path("eval/runs/answers") / f"{name}.jsonl"
    write_text_atomic(out, "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows))
    return rows
