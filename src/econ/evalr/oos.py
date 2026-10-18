"""The out-of-scope set (eval/oos/oos-v1.yaml, approved by the owner in D-010) through the service's own
pipeline, with the live planner and answer model, and the pass rule as written in the set.

Every event of every question goes to eval/runs/oos/<run>.jsonl; spend is metered in the ledger. The pass
rule's last part (a human reading finds none of `flag_if_says` stated as fact) is for the reader: strings
that appear are reported as flags, not failures.
"""

from __future__ import annotations

import json

import yaml

from econ import config, spend
from econ.answer import pipeline
from econ.manifest import write_text_atomic


def load(path: str = "eval/oos/oos-v1.yaml") -> list[dict]:
    return yaml.safe_load(config.path(path).read_text(encoding="utf-8"))["questions"]


def judge_one(q: dict, events: list[dict]) -> dict:
    ev = {e["event"]: e for e in events}
    ans = next((e for e in reversed(events) if e["event"] == "answer"), None)
    chk = next((e for e in reversed(events) if e["event"] == "check"), None)
    cited_docs = set()
    if ans:
        by_n = {x["n"]: x for x in ev["retrieval"]["evidence"]}
        cited_docs = {
            by_n[c["evidence"]]["doc_id"]
            for cl in ans["claims"]
            for c in cl["citations"]
            if c["evidence"] in by_n
        }
    coverage = ans["coverage"] if ans else None
    text = (ans["answer"] + " " + " ".join(cl["text"] for cl in ans["claims"])).lower() if ans else ""
    flags = [s for s in q.get("flag_if_says", []) if s.lower() in text]
    ok_cov = coverage in q["expect"]
    ok_check = bool(chk and chk["passed"])
    ok_cite = (not q.get("cite")) or bool(cited_docs & set(q["cite"]))
    return {
        "id": q["id"],
        "category": q["category"],
        "coverage": coverage,
        "expect": q["expect"],
        "check_passed": ok_check,
        "cited_docs": sorted(cited_docs),
        "cite_ok": ok_cite,
        "flags": flags,
        "passed_rule": ok_cov and ok_check and ok_cite,
        "cost_usd": ev["done"].get("cost_usd"),
    }


def run(questions: list[dict], svc: pipeline.Services, run_id: str) -> list[dict]:
    rows, all_events = [], []
    for q in questions:
        spend.guard("openai" if svc.provider.name == "openai" else "gemini", 0.15)
        events = list(
            pipeline.run(pipeline.Request(question=q["question"], context=q.get("context", "")), svc)
        )
        for u in events[-1].get("usage", []):
            spend.record(
                model=u["model"],
                purpose=f"oos:{run_id}",
                usage={k: u[k] for k in ("input", "cached_input", "output", "reasoning")},
                cost_usd=u["cost_usd"],
            )
        rows.append(judge_one(q, events))
        all_events += [{"id": q["id"], **e} for e in events]
    write_text_atomic(
        config.path("eval/runs/oos") / f"{run_id}.events.jsonl",
        "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in all_events),
    )
    write_text_atomic(
        config.path("eval/runs/oos") / f"{run_id}.jsonl",
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
    )
    return rows
