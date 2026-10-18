"""End-to-end answers v2 (grid answers-v2): the relevance filter's 20 passages against the adopted 20.

Steps, run in this order by `econ eval-answers-v2 --step ...`:
- `answers`: C's answers on the filtered contexts (paid, cached); B is answers-v1's B, reused after checking
  its evidence is still the adopted setting's context.
- `blind`: the exploratory pairs for Claude's blind reading, in a seeded X/Y order; the key is written to a
  separate file, read only by `report`.
- `pairwise`: gemini-3.8-flash's two-order preferences (Batch; paid, cached).
- `report`: grounding, the check, both judges and the rule; reports/answers-v2.md.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace

import yaml

from econ import config
from econ.evalr import answers, grid2, judge, judged, llmcall, metrics, pairwise, systems
from econ.evalr import filter as filt
from econ.evalr.judged import Need
from econ.manifest import write_json_atomic, write_text_atomic

RUNS = "eval/runs/answers"
ADOPTED = "plan+q:luna-plan-v2/enriched/none"
SEED = 20261018


def spec() -> dict:
    return yaml.safe_load(config.path("eval/grids/answers-v2.yaml").read_text())


def needs() -> list[Need]:
    ids = json.loads(config.path(spec()["needs"]).read_text())
    by = {n.id: n for n in judged.load()}
    return [by[i] for i in ids]


def answered(ns: list[Need]) -> tuple[list[Need], list[str]]:
    """The needs both settings answered, and the ids left out because a provider error left either without
    an answer (no_answer; in this run the OpenAI account ran out of credit). A flagged answer is kept."""
    b, c = {r["need"]: r for r in _load("answers-v1.B")}, {r["need"]: r for r in _load("answers-v2.C")}
    out = [n.id for n in ns if "no_answer" in (b[n.id]["outcome"], c[n.id]["outcome"])]
    return [n for n in ns if n.id not in out], out


def _load(name: str) -> list[dict]:
    p = config.path(RUNS) / f"{name}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def filtered_contexts(ns: list[Need]) -> dict[str, list[int]]:
    """C's evidence: the adopted 60-passage context, ordered by filter-v1's saved grades, the first 20."""
    saved = {r["need"]: r for r in _load_filter_rows()}
    deep = replace(grid2.named(ADOPTED), context=60)
    out = {}
    for n in ns:
        rows = grid2.context_rows(deep, n)
        fg = saved[n.id]["filter_grades"]
        out[n.id] = filt.select(rows, fg, 20)
    return out


def _load_filter_rows() -> list[dict]:
    p = config.path("eval/runs/retrieval-v2/filter/filter-v1.jsonl")
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def step_answers() -> dict:
    sp = spec()
    a = sp["answer"]
    ns = needs()
    base = grid2.named(ADOPTED)
    b_rows = {r["need"]: r for r in _load("answers-v1.B")}
    cs = systems.chunks()
    for n in ns:
        now = [cs[r]["chunk_id"] for r in grid2.context_rows(base, n)]
        if b_rows[n.id]["evidence"] != now:
            raise RuntimeError(f"answers-v1's B evidence for {n.id} is no longer the adopted context")
    ctx = filtered_contexts(ns)
    c = answers.run(
        "answers-v2.C",
        base,
        ns,
        model=a["model"],
        effort=a["effort"],
        prompt=a["prompt"],
        flex=a["tier"] == "flex",
        contexts=ctx,
    )
    for r in c:
        r["setting"] = f"filter-v1@20 over {ADOPTED} at 60"
    write_text_atomic(
        config.path(RUNS) / "answers-v2.C.jsonl",
        "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in c),
    )
    return {
        "needs": len(c),
        "passed": sum(r["outcome"] == "passed" for r in c),
        "cost_usd": round(sum(r["cost_usd"] for r in c), 4),
    }


def step_blind() -> dict:
    """Exploratory pairs in a seeded X/Y order, for a blind reading; the key goes to its own file."""
    ns = [n for n in needs() if n.family == "explore"]
    keep = {n.id for n in answered(ns)[0]}
    b, c = {r["need"]: r for r in _load("answers-v1.B")}, {r["need"]: r for r in _load("answers-v2.C")}
    rng = random.Random(SEED)
    key, parts = {}, ["# Blind pairs (answers-v2): which answer better serves the person who asked?", ""]
    for n in ns:
        x_is_b = rng.random() < 0.5  # drawn for every need, so a left-out need doesn't move the others
        if n.id not in keep:
            continue
        x, y = (b[n.id], c[n.id]) if x_is_b else (c[n.id], b[n.id])
        key[n.id] = "B" if x_is_b else "C"
        parts += [
            f"## {n.id}",
            "",
            f"Question: {n.question}",
            "",
            f"Narrative: {n.narrative}",
            "",
            pairwise.render("X", pairwise.final_answer(x)),
            "",
            pairwise.render("Y", pairwise.final_answer(y)),
            "",
        ]
    write_text_atomic(config.path(RUNS) / "answers-v2.blind-pairs.md", "\n".join(parts) + "\n")
    write_json_atomic(config.path(RUNS) / "answers-v2.blind-key.json", key)
    return {"pairs": len(key)}


def step_pairwise() -> dict:
    ns, _ = answered(needs())
    b, c = {r["need"]: r for r in _load("answers-v1.B")}, {r["need"]: r for r in _load("answers-v2.C")}
    model, effort = "gemini-3.8-flash", "low"
    per = {n.id: pairwise.calls(n, b[n.id], c[n.id], model=model, effort=effort) for n in ns}
    flat = [x for v in per.values() for x in v]
    replies = {x.key(): llmcall.cached(x) for x in flat if llmcall.cached(x) is not None}
    todo = [x for x in flat if x.key() not in replies]
    if todo:
        d = judge.poll(judge.submit_batch(todo, "econ-pairwise-answers-v2"), every=30)
        replies |= judge.collect(d, todo)
    rows = []
    for n in ns:
        ab, ba = (pairwise.verdict(replies.get(x.key())) for x in per[n.id])
        res = pairwise.combine(ab, ba)  # first = B (shown as A in order ab), second = C
        rows.append(
            {
                "need": n.id,
                "family": n.family,
                "ab": ab,
                "ba": ba,
                "winner": {"first": "B", "second": "C"}.get(res, res),
                "reason_ab": (replies.get(per[n.id][0].key()) or {}).get("data"),
                "reason_ba": (replies.get(per[n.id][1].key()) or {}).get("data"),
            }
        )
    pairwise.save("answers-v2.pairwise-gemini", rows)
    return {"pairs": len(rows), "missing": sum(r["winner"] == "missing" for r in rows)}


# --- the report ----------------------------------------------------------------------------------


def unblind(verdicts: dict[str, str], key: dict[str, str]) -> dict[str, str]:
    """Blind verdicts (X, Y or tie) to settings, with the key that says which setting X was."""
    other = {"B": "C", "C": "B"}
    return {
        nid: "tie" if v == "tie" else (key[nid] if v == "X" else other[key[nid]])
        for nid, v in verdicts.items()
    }


def grounding(row: dict, need: Need, grades: dict[str, int]) -> dict:
    cs = {c["chunk_id"]: c for c in systems.chunks()}
    final = pairwise.final_answer(row)
    cited = (
        sorted({row["evidence"][q["evidence"] - 1] for cl in final["claims"] for q in cl["citations"]})
        if final
        else []
    )
    rel = [c for c in cited if grades.get(c, 0) >= 2]
    out = {
        "relevant_cited": len(rel),
        "grade3_cited": sum(1 for c in cited if grades.get(c, 0) == 3),
        "share_relevant": len(rel) / len(cited) if cited else None,
        "relevant_docs_cited": len({cs[c]["doc_id"] for c in rel}),
        "claims": len(final["claims"]) if final else 0,
        "words": len(final["answer"].split()) if final else 0,
        "unjudged_cited": sum(1 for c in cited if c not in grades),
        "first_pass": 1.0 if row["attempts"] and row["attempts"][0].get("check", {}).get("passed") else 0.0,
        "passed": 1.0 if row["outcome"] == "passed" else 0.0,
        "gold_cited": None,
    }
    if need.family == "silver" and need.golds:
        covered = set().union(*metrics.judge([cs[c] for c in cited], need.golds)) if cited else set()
        out["gold_cited"] = 1.0 if covered else 0.0
    return out


def step_report() -> dict:
    sp = spec()
    ns, left_out = answered(needs())
    grades = grid2.grades_by_need(grid2.spec_depth()["judgments"])
    b, c = {r["need"]: r for r in _load("answers-v1.B")}, {r["need"]: r for r in _load("answers-v2.C")}
    gb = {n.id: grounding(b[n.id], n, grades.get(n.id, {})) for n in ns}
    gc = {n.id: grounding(c[n.id], n, grades.get(n.id, {})) for n in ns}
    gem = {r["need"]: r for r in _load("answers-v2.pairwise-gemini")}
    key = json.loads((config.path(RUNS) / "answers-v2.blind-key.json").read_text())
    verdicts = json.loads((config.path(RUNS) / "answers-v2.claude-verdicts.json").read_text())
    claude = unblind(verdicts, key)
    fams = [("all", None), ("explore", "explore"), ("silver", "silver")]

    def sub(fam):
        return [n for n in ns if fam is None or n.family == fam]

    fmt = grid2._fmt
    lines = [
        "# End-to-end answers v2: the relevance filter's 20 against the adopted 20",
        "",
        f"Grid `answers-v2` (eval/grids/answers-v2.yaml, committed before any answer on the filtered contexts). "
        f"{len(ns)} test needs (the answers-v1 set). B is the adopted retrieval (`{ADOPTED}`, 20 passages; "
        "answers-v1's B answers, reused). C is the same 60-passage context rated by filter-v1 (D-018), the 20 rated "
        "highest. Both answered by gpt-6.1-sol at medium effort with answer-v1 on the Flex tier, through the check "
        "and its retry.",
        "",
        f"**Deviation from the grid, disclosed:** {len(left_out)} of the 60 needs are left out of both settings "
        f"({', '.join(left_out) or 'none'}): every attempt at C's answer ended in a provider error (HTTP 502, Flex "
        "unavailable, then HTTP 429 `credit_balance_exhausted`: the OpenAI account ran out of credit), so no answer "
        "exists to compare. The owner chose to finish on the rest. No answer that exists was dropped.",
        "",
        "## The check",
        "",
        "| | B | C |",
        "|---|---|---|",
        f"| Passed (after at most one retry) | {sum(int(gb[n.id]['passed']) for n in ns)}/{len(ns)} | "
        f"{sum(int(gc[n.id]['passed']) for n in ns)}/{len(ns)} |",
        f"| Passed first time | {metrics.mean([gb[n.id]['first_pass'] for n in ns]):.3f} | "
        f"{metrics.mean([gc[n.id]['first_pass'] for n in ns]):.3f} |",
    ]
    cov = {
        s: [sum(1 for n in ns if rows[n.id]["coverage"] == k) for k in ("complete", "partial", "not_in_kb")]
        for s, rows in (("B", b), ("C", c))
    }
    lines.append(
        f"| Coverage complete / partial / not_in_kb | {' / '.join(map(str, cov['B']))} | {' / '.join(map(str, cov['C']))} |"
    )
    cost_c = [sum(x.get("cost_usd", 0) for x in c[n.id]["attempts"]) for n in ns]
    cost_b = [sum(x.get("cost_usd", 0) for x in b[n.id]["attempts"]) for n in ns]
    lines += [
        f"| Cost per answer (Flex) | ${metrics.mean(cost_b):.4f} | ${metrics.mean(cost_c):.4f} |",
        "",
        "## Grounding against the judgments",
        "",
        f"Unjudged cited passages: B {sum(gb[n.id]['unjudged_cited'] for n in ns)}, C "
        f"{sum(gc[n.id]['unjudged_cited'] for n in ns)} (every C passage lies in a fully judged 60-passage context).",
        "",
        "| Measure | Needs | B | C | C - B [95% CI] |",
        "|---|---|---|---|---|",
    ]
    measures = [
        ("relevant_cited", "Distinct relevant passages cited (grade 2-3)"),
        ("grade3_cited", "Distinct highly relevant passages cited (grade 3)"),
        ("relevant_docs_cited", "Distinct documents among the relevant passages cited"),
        ("share_relevant", "Share of cited passages that are relevant"),
        ("claims", "Claims per answer"),
        ("words", "Words of prose"),
        ("gold_cited", "Answer cites a silver gold passage"),
    ]
    for m, label in measures:
        for fl, fam in fams:
            if m == "gold_cited" and fam != "silver":
                continue
            pairs = [
                (gb[n.id][m], gc[n.id][m])
                for n in sub(fam)
                if gb[n.id][m] is not None and gc[n.id][m] is not None
            ]
            xa, xb = [p[0] for p in pairs], [p[1] for p in pairs]
            cmp = metrics.compare(xa, xb)
            lines.append(
                f"| {label} | {fl} ({len(pairs)}) | {metrics.mean(xa):.2f} | {metrics.mean(xb):.2f} | "
                f"{cmp['diff']:+.2f} [{cmp['ci'][0]:+.2f}, {cmp['ci'][1]:+.2f}] |"
            )

    def tally(judged: dict[str, str], fam):
        ids = [n.id for n in sub(fam) if n.id in judged]
        w = {k: sum(1 for i in ids if judged[i] == k) for k in ("C", "B", "tie", "split", "missing")}
        return w, pairwise.sign_test(w["C"], w["B"])

    gw = {r: gem[r]["winner"] for r in gem}
    lines += [
        "",
        "## Preference",
        "",
        "gemini-3.8-flash (prompts/eval/pairwise-v1.md) compared each pair blind, once in each order; a preference "
        "counts only when both orders agree (split = they disagreed). Claude read every exploratory pair blind "
        "(seeded X/Y order; verdicts recorded before the key was read). Sign test on wins, two-sided.",
        "",
        "| Judge | Needs | C preferred | B preferred | Tie | Split | p |",
        "|---|---|---|---|---|---|---|",
    ]
    res = {}
    for fl, fam in fams:
        w, p = tally(gw, fam)
        res[fl] = (w, p)
        lines.append(
            f"| Gemini, both orders | {fl} ({len(sub(fam))}) | {w['C']} | {w['B']} | {w['tie']} | {w['split']} | {p:.3f} |"
        )
    w, p = tally(claude, "explore")
    lines.append(
        f"| Claude, blind | explore ({len(claude)}) | {w['C']} | {w['B']} | {w['tie']} | | {p:.3f} |"
    )
    both = [i for i in claude if claude[i] in ("B", "C") and gw.get(i) in ("B", "C")]
    agree = sum(1 for i in both if claude[i] == gw[i])
    lines += [
        "",
        f"Where both judges stated a preference ({len(both)} exploratory pairs), they agreed on {agree}.",
    ]
    (wa, pa), (we, pe), (ws, ps) = res["all"], res["explore"], res["silver"]
    a_ok = (wa["C"] > wa["B"] and pa < 0.05) or (we["C"] > we["B"] and pe < 0.05)
    b_ok = not (ws["B"] > ws["C"] and ps < 0.05)
    pass_b = metrics.mean([gb[n.id]["passed"] for n in ns])
    pass_c = metrics.mean([gc[n.id]["passed"] for n in ns])
    c_ok = pass_c >= pass_b - 0.05
    ok = a_ok and b_ok and c_ok
    lines += [
        "",
        "## The rule",
        "",
        f"Fixed in advance: {sp['rule']}",
        "",
        f"**{'Met: the filter is recommended' if ok else 'Not met: the filter is not recommended on this run'}** "
        f"((a) all {wa['C']}-{wa['B']}, p = {pa:.3f}; exploratory {we['C']}-{we['B']}, p = {pe:.3f}: "
        f"{'met' if a_ok else 'not met'}. (b) silver {ws['C']}-{ws['B']}, p = {ps:.3f}: {'met' if b_ok else 'not met'}. "
        f"(c) pass rates B {fmt(pass_b)}, C {fmt(pass_c)}: {'met' if c_ok else 'not met'}.)",
        "",
        "## What it shows and what it doesn't",
        "",
        "- Only the evidence differs: same needs, answer model, effort, prompt and check.",
        "- The judges see the answers and their verified quotes, not the corpus: they judge how well an answer uses "
        "and reports what it found.",
        "- One answer model at one effort; 60 needs.",
    ]
    out = config.path("reports/answers-v2.md")
    write_text_atomic(out, "\n".join(lines) + "\n")
    summary = {"rule_met": ok, "gemini_all": wa, "gemini_explore": we, "gemini_silver": ws, "claude": w}
    write_json_atomic(config.path(RUNS) / "answers-v2.summary.json", summary)
    return summary
