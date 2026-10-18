"""The query plan for every need, from a planner model and prompt, exactly as the service would build it.

Plans are cached paid replies (eval/cache/llm) and are summarised in eval/runs/judged-v1/plans/<name>.jsonl:
one line per need with the standalone question and the queries.
"""

from __future__ import annotations

import json

from econ import config, textcheck
from econ.answer import pipeline, prompts
from econ.answer.schema import Plan, strict_schema
from econ.evalr import llmcall
from econ.evalr.judged import Need
from econ.manifest import write_text_atomic


def plan_call(need: Need, *, model: str, prompt: str, effort: str | None) -> llmcall.Call:
    user = (
        pipeline._context_block(need.context) + f"<question>\n{pipeline.defang(need.question)}\n</question>"
    )
    return llmcall.Call(
        model=model,
        system=prompts.load(prompt),
        user=user,
        schema=strict_schema(Plan),
        schema_name="plan",
        effort=effort,
        max_output_tokens=config.service().llm.plan_max_output_tokens,
        purpose=f"plan:{prompt}:{model}",
        tag=need.id,
    )


def queries_of(need: Need, reply: dict) -> tuple[str, list[str]]:
    """The service's rule: up to max_queries non-empty queries, none with a high text-check finding;
    otherwise the question as asked."""
    k = config.service().answer.max_queries
    if "error" in reply:
        return need.question, [need.question]
    plan = Plan.model_validate(reply["data"])
    qs = [q.strip() for q in plan.queries if q.strip()][:k]
    if qs and not any(textcheck.high(textcheck.scan(q)) for q in qs):
        return plan.standalone_question.strip() or need.question, qs
    return need.question, [need.question]


def run(
    needs: list[Need], name: str, *, model: str, prompt: str, effort: str | None, flex: bool
) -> list[dict]:
    calls = [plan_call(n, model=model, prompt=prompt, effort=effort) for n in needs]
    replies = llmcall.run_many(calls, flex=flex, workers=8)
    rows = []
    for n, r in zip(needs, replies, strict=True):
        standalone, qs = queries_of(n, r)
        rows.append({"need": n.id, "standalone": standalone, "queries": qs, "error": r.get("error")})
    out = config.path("eval/runs/judged-v1/plans") / f"{name}.jsonl"
    write_text_atomic(out, "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows))
    return rows


def load(name: str) -> dict[str, dict]:
    p = config.path("eval/runs/judged-v1/plans") / f"{name}.jsonl"
    return {r["need"]: r for r in (json.loads(x) for x in p.read_text().splitlines() if x.strip())}
