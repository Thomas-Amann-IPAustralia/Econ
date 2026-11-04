"""The atlas chat's capped smoke test (D-038, WP6): 20 of atlas-v1's needs through the full pipeline with the
service's OpenAI models, every event kept for reading, every call metered, the run stopped at its budget (D-037:
up to US$2.00).

Writes eval/runs/atlas-smoke-v1/events.jsonl (every event but drafts, per need) and summary.json (per need: the
outcome, attempts, numbers-check errors, whether the gold observation is cited, coverage, cost and seconds).
"""

from __future__ import annotations

import json
import os
import time

from econ import config, spend
from econ.answer import pipeline
from econ.answer.providers import OpenAIModel
from econ.evalr.atlas import load_needs
from econ.manifest import StageError, write_json_atomic, write_text_atomic

RUN = "eval/runs/atlas-smoke-v1"
BUDGET = 2.00
RESERVE = 0.25  # a pessimistic question, retry included
NEEDS = [
    "a02", "a04", "a06", "a08", "a11", "a13", "a19",  # lookups by topic, over the lenses and stages
    "a21", "a22", "a23",  # by id
    "a26", "a27", "a29", "a33", "a34",  # exploratory
    "a36", "a37", "a38", "a39", "a40",  # out of scope
]  # fmt: skip


def _numbers(err: str) -> bool:
    return "which is not in the sentences" in err or "without citing a sentence" in err


def cited_docs(evs: list[dict]) -> set[str]:
    ev = next((e for e in evs if e["event"] == "retrieval"), {})
    by_n = {x["n"]: x["doc_id"] for x in ev.get("evidence", [])}
    check = [e for e in evs if e["event"] == "check"]
    if not check:
        return set()
    return {
        by_n[c["evidence"]][len("atlas-") :]
        for cl in check[-1]["claims"]
        for c in cl["citations"]
        if c["evidence"] in by_n
    }


def run(embedder, index, *, only: list[str] | None = None, run_dir: str = RUN) -> dict:
    llm = config.service().llm
    prov = next(p for p in llm.providers if p.name == "openai")
    key = os.environ.get(prov.key_env, "")
    if not key:
        raise StageError(f"{prov.key_env} is not set (a placeholder is enough behind the proxy)")
    model = OpenAIModel(prov, key, llm.timeout_seconds)
    svc = pipeline.Services(
        index=index, embedder=embedder, model=model, provider=prov, kb=config.kb("atlas"), kb_name="atlas"
    )
    needs = {n["id"]: n for n in load_needs()}
    out = config.path(run_dir)
    prior = json.loads((out / "summary.json").read_text())["needs"] if (out / "summary.json").exists() else []
    done_ids = {s["id"] for s in prior}
    lines = (out / "events.jsonl").read_text().splitlines() if (out / "events.jsonl").exists() else []
    summary, run_cost = list(prior), sum(s["cost_usd"] or 0 for s in prior)
    for nid in only or NEEDS:
        if nid in done_ids and not only:
            continue
        if run_cost + RESERVE > BUDGET:
            summary.append({"id": nid, "skipped": f"budget: US${run_cost:.4f} spent of US${BUDGET:.2f}"})
            continue
        spend.guard("openai", RESERVE)
        n = needs[nid]
        t = time.time()
        evs = [
            e for e in pipeline.run(pipeline.Request(question=n["question"]), svc) if e["event"] != "draft"
        ]
        done = evs[-1]
        refused = [e["message"] for e in evs if e["event"] == "error" and "HTTP 40" in e.get("message", "")]
        if refused and not done.get("cost_usd"):
            # a refused key (expired, or out of credit): stop, rather than send every need to the same refusal
            raise StageError(f"the model refused the call: {refused[0][:160]}", item=nid)
        for u in done.get("usage", []):
            spend.record(
                model=u["model"],
                purpose=f"atlas-smoke-v1:{nid}",
                usage={k: u[k] for k in ("input", "cached_input", "output", "reasoning")},
                cost_usd=u["cost_usd"],
            )
        run_cost += done.get("cost_usd") or 0
        checks = [e for e in evs if e["event"] == "check"]
        answer = next((e for e in reversed(evs) if e["event"] == "answer"), None)
        cited = cited_docs(evs)
        summary = [s for s in summary if s["id"] != nid] + [
            {
                "id": nid,
                "kind": n["kind"],
                "question": n["question"],
                "outcome": done.get("outcome"),
                "attempts": done.get("attempts"),
                "first_check_passed": bool(checks and checks[0]["passed"]),
                "numbers_errors": [
                    x for c in checks for x in c["errors"] if "which is not in the sentences" in x
                ],
                "other_errors": [
                    x for c in checks for x in c["errors"] if "which is not in the sentences" not in x
                ],
                "coverage": answer["coverage"] if answer else None,
                "gold": n["gold"],
                "gold_cited": sorted(set(n["gold"]) & cited),
                "cited": sorted(cited),
                "pinned": next((e.get("pinned") for e in evs if e["event"] == "retrieval"), None),
                "cost_usd": done.get("cost_usd"),
                "seconds": round(time.time() - t, 1),
                "errors": [e.get("message") for e in evs if e["event"] == "error"],
            }
        ]
        lines = [x for x in lines if json.loads(x)["need"] != nid] + [
            json.dumps({"need": nid, "events": evs}, ensure_ascii=False, default=str)
        ]
        write_text_atomic(out / "events.jsonl", "\n".join(lines) + "\n")
        write_json_atomic(
            out / "summary.json", {"budget_usd": BUDGET, "spent_usd": round(run_cost, 6), "needs": summary}
        )
    return {"spent_usd": round(run_cost, 6), "needs": summary}
