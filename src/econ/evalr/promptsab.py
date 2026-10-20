"""Grid prompts-wipo-v1 (D-034): the service's prompts before and after rewriting them for two publishers.

Each question runs through the service's own pipeline (econ.answer.pipeline) once per arm, with the arm's
plan, filter and answer prompts swapped into the service config; everything else is as served. Each
answer's usage is metered in the eval ledger under the grid's purpose and the spend caps (econ.spend), and
each arm's rows are saved after every question, so an interrupted run resumes. A judge from another family
then compares the arms' answers pair by pair in both orders (prompt pairwise-v2), and counts misattributed
findings in each.
"""

from __future__ import annotations

import json
import time

import yaml

from econ import config, spend
from econ.answer import pipeline
from econ.evalr import llmcall, metrics
from econ.evalr.pairwise import combine, sign_test, verdict
from econ.manifest import StageError, write_text_atomic

GRID = "prompts-wipo-v1"
JUDGE = "gemini-3.8-flash"
JUDGE_PROMPT = "pairwise-v2"
RESERVE = 0.08  # a question's pessimistic cost, checked against the cap before it starts


def spec() -> dict:
    return yaml.safe_load(config.path(f"eval/grids/{GRID}.yaml").read_text())


def questions() -> list[dict]:
    """The grid's questions with their golds (sampled needs) or narratives (questions for both)."""
    from econ.evalr import testset, wipo
    from econ.kb.chunk import load_elements

    s = spec()["questions"]
    silver = {n.id: n for n in testset.load()}
    els = {d.doc_id: load_elements(d.doc_id) for d in config.sources().documents}
    wneeds = {n.id: n for n in wipo.load(els)}
    out = [
        {"id": i, "group": "ipa", "question": silver[i].question, "golds": silver[i].golds} for i in s["ipa"]
    ]
    out += [
        {"id": i, "group": "wipo", "question": wneeds[i].question, "golds": wneeds[i].golds}
        for i in s["wipo"]
    ]
    out += [
        {"id": q["id"], "group": "both", "question": q["question"], "narrative": q["narrative"]}
        for q in s["both"]
    ]
    return out


def arm_config(arm: dict):
    s = config.service()
    a = s.answer.model_copy(
        update={
            "prompt": arm["answer"],
            "plan_prompt": arm["plan"],
            "filter": s.answer.filter.model_copy(update={"prompt": arm["filter"]}),
        }
    )
    return s.model_copy(update={"answer": a})


def run_path(arm: str):
    return config.path("eval/runs/answers") / f"{GRID}.{arm}.jsonl"


def _rows(arm: str) -> list[dict]:
    p = run_path(arm)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def run_arm(name: str, qs: list[dict], services) -> list[dict]:
    """Answer every question not yet answered under this arm, saving after each."""
    original = config.service
    patched = arm_config(spec()["arms"][name])
    rows = _rows(name)
    done = {r["id"] for r in rows}
    try:
        config.service = lambda: patched  # every config.service() the pipeline makes sees the arm
        for q in qs:
            if q["id"] in done:
                continue
            spend.guard("openai", RESERVE)
            t0 = time.time()
            events = list(pipeline.run(pipeline.Request(question=q["question"]), services))
            ret = next((e for e in events if e["event"] == "retrieval"), None)
            ans = [e for e in events if e["event"] == "answer"]
            checks = [e for e in events if e["event"] == "check"]
            end = next((e for e in events if e["event"] == "done"), {})
            for u in end.get("usage", []):
                spend.record(
                    model=u["model"],
                    purpose=f"{GRID}:{name}",
                    usage={k: u.get(k, 0) for k in ("input", "cached_input", "output", "reasoning")},
                    cost_usd=u["cost_usd"],
                )
            rows.append(
                {
                    "id": q["id"],
                    "arm": name,
                    "prompts": spec()["arms"][name],
                    "question": q["question"],
                    "queries": ret["queries"] if ret else [],
                    "filter": {k: ret["filter"].get(k) for k in ("status", "read", "kept")} if ret else None,
                    "evidence": [
                        {"n": e["n"], "chunk_id": e["chunk_id"], "doc_id": e["doc_id"]}
                        for e in (ret["evidence"] if ret else [])
                    ],
                    "answer": ans[-1] if ans else None,
                    "checks": [{"attempt": c["attempt"], "passed": c["passed"]} for c in checks],
                    "outcome": end.get("outcome"),
                    "cost_usd": end.get("cost_usd"),
                    "seconds": round(time.time() - t0, 1),
                    "errors": [e for e in events if e["event"] == "error"],
                }
            )
            write_text_atomic(
                run_path(name),
                "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows),
            )
            print(f"[{GRID}] {name} {q['id']}: {rows[-1]['outcome']} US${rows[-1]['cost_usd']}", flush=True)
    finally:
        config.service = original
    return rows


# --- measures ------------------------------------------------------------------------------------------


def cited_ns(row: dict) -> set[int]:
    a = row.get("answer") or {}
    return {c["evidence"] for cl in a.get("claims", []) for c in cl.get("citations", [])}


def gold_measures(row: dict, q: dict, index) -> dict:
    if "golds" not in q:
        return {}
    by_id = {c["chunk_id"]: c for c in index.chunks}
    shown = [by_id[e["chunk_id"]] for e in row["evidence"]]
    cited = [by_id[e["chunk_id"]] for e in row["evidence"] if e["n"] in cited_ns(row)]
    reach = any(metrics.covers(c, g) for c in shown for g in q["golds"])
    used = any(metrics.covers(c, g) for c in cited for g in q["golds"])
    return {"gold_reached": reach, "gold_cited": used}


def wipo_share(row: dict) -> float:
    ev = row["evidence"]
    return sum(e["doc_id"].startswith("wipo-") for e in ev) / len(ev) if ev else 0.0


# --- the judge -----------------------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "misattributed_A": {"type": "integer"},
        "misattributed_B": {"type": "integer"},
        "reason": {"type": "string"},
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
    },
    "required": ["misattributed_A", "misattributed_B", "reason", "winner"],
    "additionalProperties": False,
}


def render(label: str, row: dict, docs: dict) -> str:
    a = row.get("answer")
    if not a:
        return f'<answer label="{label}">(no answer)</answer>'
    pub = {e["n"]: docs[e["doc_id"]] for e in row["evidence"]}
    claims = []
    for i, c in enumerate(a.get("claims", []), 1):
        quotes = " | ".join(
            f"[{q['evidence']}, {pipeline.defang(pub[q['evidence']]['publisher'])}: "
            f"{pipeline.defang(pub[q['evidence']]['title'])}, {pub[q['evidence']]['year']}] "
            f'"{pipeline.defang(q["quote"])}"'
            for q in c["citations"]
        )
        claims.append(f"  claim {i}: {pipeline.defang(c['text'])}\n    quotes: {quotes}")
    gaps = "; ".join(pipeline.defang(g) for g in a.get("gaps", [])) or "(none)"
    return (
        f'<answer label="{label}" coverage="{a["coverage"]}">\n<prose>\n{pipeline.defang(a["answer"])}\n</prose>\n'
        "<claims>\n" + "\n".join(claims) + f"\n</claims>\n<gaps>{gaps}</gaps>\n</answer>"
    )


def judge_calls(q: dict, before: dict, after: dict, docs: dict) -> list[llmcall.Call]:
    system = (config.ROOT / "prompts" / "eval" / f"{JUDGE_PROMPT}.md").read_text(encoding="utf-8")
    narrative = q.get("narrative") or "A direct, accurate answer to the question from the evidence."
    head = (
        f"<question>{pipeline.defang(q['question'])}</question>\n"
        f"<narrative>{pipeline.defang(narrative)}</narrative>\n\n"
    )
    out = []
    for order, (x, y) in (("ab", (before, after)), ("ba", (after, before))):
        out.append(
            llmcall.Call(
                model=JUDGE,
                system=system,
                user=head + render("A", x, docs) + "\n\n" + render("B", y, docs),
                schema=SCHEMA,
                schema_name="preference",
                effort="low",
                max_output_tokens=4000,
                purpose=f"pairwise:{JUDGE_PROMPT}:{JUDGE}",
                tag=f"{q['id']}:{order}",
            )
        )
    return out


def judged(q: dict, before: dict, after: dict, docs: dict) -> dict:
    ab, ba = llmcall.run_many(judge_calls(q, before, after, docs), workers=2)
    pref = combine(verdict(ab), verdict(ba))  # 'first' = before
    pref = {"first": "before", "second": "after"}.get(pref, pref)

    def mis(reply: dict, label: str):
        d = reply.get("data") if reply else None
        return d.get(f"misattributed_{label}") if isinstance(d, dict) else None

    return {
        "preference": pref,
        "misattributed": {
            # In order ab, A is before; in order ba, A is after. Each count is the larger of the two readings.
            "before": max(x for x in (mis(ab, "A"), mis(ba, "B"), 0) if x is not None),
            "after": max(x for x in (mis(ab, "B"), mis(ba, "A"), 0) if x is not None),
        },
        "reasons": [
            (ab.get("data") or {}).get("reason") if isinstance(ab.get("data"), dict) else None,
            (ba.get("data") or {}).get("reason") if isinstance(ba.get("data"), dict) else None,
        ],
    }


# --- the whole grid ------------------------------------------------------------------------------------


def run_grid(run, services) -> dict:
    qs = questions()
    out = {}
    for name in spec()["arms"]:
        out[name] = {r["id"]: r for r in run_arm(name, qs, services)}
    missing = [q["id"] for q in qs for a in out if q["id"] not in out[a]]
    if missing:
        raise StageError("questions without an answer", item=missing[0])
    docs = services.index.docs
    rows = []
    for q in qs:
        b, a = out["before"][q["id"]], out["after"][q["id"]]
        j = judged(q, b, a, docs)
        rows.append(
            {
                "id": q["id"],
                "group": q["group"],
                "question": q["question"],
                **{
                    arm: {
                        "outcome": r["outcome"],
                        "first_time": bool(r["checks"] and r["checks"][0]["passed"]),
                        "coverage": (r["answer"] or {}).get("coverage"),
                        "claims": len((r["answer"] or {}).get("claims", [])),
                        "wipo_share": wipo_share(r),
                        "cost_usd": r["cost_usd"],
                        "seconds": r["seconds"],
                        **gold_measures(r, q, services.index),
                    }
                    for arm, r in (("before", b), ("after", a))
                },
                **j,
            }
        )
    p = config.path("eval/runs/answers") / f"{GRID}.judged.jsonl"
    write_text_atomic(p, "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows))
    report = render_report(rows, out, qs)
    rp = config.path(config.pipeline().paths.reports) / f"{GRID}.md"
    write_text_atomic(rp, report)
    run.add_output(p)
    run.add_output(rp)
    s = summary(rows)
    run.counts.update(questions=len(qs), **{k: v for k, v in s.items() if not isinstance(v, dict)})
    return s


def summary(rows: list[dict]) -> dict:
    def n(arm, key):
        return sum(bool(r[arm].get(key)) for r in rows)

    wins = sum(r["preference"] == "after" for r in rows)
    losses = sum(r["preference"] == "before" for r in rows)
    s = {
        "passed_first_time": {a: n(a, "first_time") for a in ("before", "after")},
        "passed": {a: sum(r[a]["outcome"] == "passed" for r in rows) for a in ("before", "after")},
        "gold_reached": {a: n(a, "gold_reached") for a in ("before", "after")},
        "gold_cited": {a: n(a, "gold_cited") for a in ("before", "after")},
        "misattributed": {a: sum(r["misattributed"][a] for r in rows) for a in ("before", "after")},
        "preferences": {
            "after": wins,
            "before": losses,
            "tie": sum(r["preference"] == "tie" for r in rows),
            "split": sum(r["preference"] == "split" for r in rows),
        },
        "sign_test_p": sign_test(wins, losses),
        "cost_usd": {a: round(sum(r[a]["cost_usd"] or 0 for r in rows), 4) for a in ("before", "after")},
    }
    s["recommend_after"] = (
        s["passed"]["after"] >= s["passed"]["before"] - 1
        and s["gold_reached"]["after"] >= s["gold_reached"]["before"]
        and s["misattributed"]["after"] <= s["misattributed"]["before"]
        and losses <= wins
    )
    return s


def render_report(rows: list[dict], out: dict, qs: list[dict]) -> str:
    s = summary(rows)
    g = spec()
    L = [
        "# The prompts before and after rewriting them for two publishers (D-034)",
        "",
        f"Grid `{GRID}` (eval/grids/{GRID}.yaml, committed before any answer). Generated by "
        "`econ eval-prompts-wipo`. 13 questions, each answered once under each arm through the service's own "
        "pipeline on the index with the WIPO documents; judge "
        f"{JUDGE} ({JUDGE_PROMPT}), both orders, blind to the arm. Answers: `eval/runs/answers/{GRID}.*.jsonl`.",
        "",
        f"- **before**: {g['arms']['before']}",
        f"- **after**: {g['arms']['after']}",
        "",
        f"**Rule (fixed before any answer):** {g['rule']}",
        "",
        f"**Outcome: {'recommend after' if s['recommend_after'] else 'do not recommend after'}.**",
        "",
        "| Over 13 questions | before | after |",
        "|---|---|---|",
        f"| Passed the check first time | {s['passed_first_time']['before']} | {s['passed_first_time']['after']} |",
        f"| Passed (after the retry) | {s['passed']['before']} | {s['passed']['after']} |",
        f"| Gold reached the 20 passages (8 sampled needs) | {s['gold_reached']['before']} | {s['gold_reached']['after']} |",
        f"| Gold cited (8 sampled needs) | {s['gold_cited']['before']} | {s['gold_cited']['after']} |",
        f"| Misattributions counted by the judge | {s['misattributed']['before']} | {s['misattributed']['after']} |",
        f"| Agreed preferences | {s['preferences']['before']} | {s['preferences']['after']} |",
        f"| Cost | US${s['cost_usd']['before']} | US${s['cost_usd']['after']} |",
        "",
        f"Ties {s['preferences']['tie']}, split verdicts {s['preferences']['split']}; two-sided sign test p = "
        f"{s['sign_test_p']:.3f}.",
        "",
        "## By question",
        "",
        "| Question | Group | Outcome (before / after) | WIPO share of the 20 | Gold reached / cited | Misattributed | Preferred |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        b, a = r["before"], r["after"]
        gold = (
            f"{'yes' if b.get('gold_reached') else 'no'}/{'yes' if b.get('gold_cited') else 'no'} → "
            f"{'yes' if a.get('gold_reached') else 'no'}/{'yes' if a.get('gold_cited') else 'no'}"
            if "gold_reached" in b
            else ""
        )
        L.append(
            f"| {r['question']} | {r['group']} | {b['outcome']} / {a['outcome']} | "
            f"{b['wipo_share']:.2f} → {a['wipo_share']:.2f} | {gold} | "
            f"{r['misattributed']['before']} → {r['misattributed']['after']} | {r['preference']} |"
        )
    L += ["", "## The answers", ""]
    for q in qs:
        L += [f"### {q['question']}", ""]
        for arm in ("before", "after"):
            row = out[arm][q["id"]]
            a = row.get("answer") or {}
            L += [
                f"**{arm}** ({a.get('coverage', 'no answer')}, {len(a.get('claims', []))} claims, "
                f"{row['outcome']}, {row['seconds']} s)",
                "",
                a.get("answer", "(no answer)"),
                "",
            ]
        j = next(r for r in rows if r["id"] == q["id"])
        L += [f"*Judge:* {j['preference']}. " + " / ".join(x for x in j["reasons"] if x), ""]
    return "\n".join(L) + "\n"
