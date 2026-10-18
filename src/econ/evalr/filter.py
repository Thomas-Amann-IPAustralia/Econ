"""A relevance filter (grid retrieval-filter): a small model rates the 60-passage context and the answer
model gets the best 20.

The filter sees what the service would have: the plan's standalone question and each passage with its
document, year and section, in rank order, at most GROUP a call (a need's calls would run in parallel).
It never sees the judge's narrative, and it is from another family than the judge. Replies are cached paid
calls (econ.evalr.llmcall); the rows go to eval/runs/retrieval-v2/filter/ and the report to
reports/retrieval-filter.md.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import replace

import yaml

from econ import config
from econ.answer import pipeline
from econ.evalr import grid2, judge, llmcall, metrics, systems
from econ.evalr.judged import Need

PROMPT = "filter-v1"


def spec() -> dict:
    return yaml.safe_load(config.path("eval/grids/retrieval-filter.yaml").read_text())


def calls_for(need: Need, rows: list[int], question: str, f: dict) -> list[tuple[llmcall.Call, dict]]:
    """Calls for one need, each with its map from local passage id to chunk id."""
    docs = config.sources().by_id()
    cs = systems.chunks()
    system = (config.ROOT / "prompts" / "eval" / f"{PROMPT}.md").read_text(encoding="utf-8")
    out = []
    for g in range(0, len(rows), f["group"]):
        part = rows[g : g + f["group"]]
        ids = {f"p{g + i + 1}": cs[r]["chunk_id"] for i, r in enumerate(part)}
        blocks = []
        for pid, r in zip(ids, part, strict=True):
            c, d = cs[r], docs[cs[r]["doc_id"]]
            sec = " > ".join(c["section"]) if c["section"] else ""
            blocks.append(
                f'<evidence id="{pid}" document="{pipeline.defang(d.title)}" year="{d.year}" '
                f'section="{pipeline.defang(sec)}">\n{pipeline.defang(c["text"])}\n</evidence>'
            )
        user = f"<question>{pipeline.defang(question)}</question>\n\n" + "\n\n".join(blocks)
        call = llmcall.Call(
            model=f["model"],
            system=system,
            user=user,
            schema=judge.SCHEMA,
            schema_name="grades",
            effort=f["effort"],
            max_output_tokens=3000,
            purpose=f"filter:{PROMPT}:{f['model']}",
            tag=need.id,
        )
        out.append((call, ids))
    return out


def select(rows: list[int], fgrades: dict[str, int] | None, k: int) -> list[int]:
    """The primary rule: by filter grade, ties by rank; the first k. No grades: the first-stage order."""
    if fgrades is None:
        return rows[:k]
    cs = systems.chunks()
    order = sorted(range(len(rows)), key=lambda i: (-fgrades.get(cs[rows[i]]["chunk_id"], 0), i))
    return [rows[i] for i in order[:k]]


def select_useful(rows: list[int], fgrades: dict[str, int] | None, cap: int) -> list[int]:
    """The secondary rule: passages the filter grades 2-3, in rank order, up to `cap`."""
    if fgrades is None:
        return rows[:20]
    cs = systems.chunks()
    return [r for r in rows if fgrades.get(cs[r]["chunk_id"], 0) >= 2][:cap]


def quadratic_kappa(a: list[int], b: list[int], k: int = 4) -> float:
    n = len(a)
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        obs[x][y] += 1
    ra = [sum(obs[i]) for i in range(k)]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = [[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]
    o = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k)) / n
    e = sum(w[i][j] * ra[i] * rb[j] for i in range(k) for j in range(k)) / (n * n)
    return 1 - o / e if e else float("nan")


def doc_coverage(ctx: list[int], grades: dict[str, int]) -> float | None:
    cs = systems.chunks()
    by_id = {c["chunk_id"]: c for c in cs}
    rel_docs = {by_id[c]["doc_id"] for c, g in grades.items() if g >= 2}
    got = {cs[r]["doc_id"] for r in ctx if grades.get(cs[r]["chunk_id"], 0) >= 2}
    return len(got) / len(rel_docs) if rel_docs else None


def _timed(client, c: llmcall.Call) -> float:
    """Seconds for one standard-tier call, metered; NaN if the provider refuses it."""
    from econ.answer.providers import ProviderError

    t0 = time.time()
    try:
        rep = client.generate_json(
            system=c.system,
            user=c.user,
            schema=c.schema,
            schema_name=c.schema_name,
            model=c.model,
            effort=c.effort,
            max_output_tokens=c.max_output_tokens,
        )
    except ProviderError as e:
        if e.usage:
            llmcall._meter(replace(c, purpose=c.purpose + ":latency"), e.usage, False)
        return float("nan")
    llmcall._meter(replace(c, purpose=c.purpose + ":latency"), rep.usage, False)
    return time.time() - t0


def latency_probe(calls: list[list[llmcall.Call]]) -> list[float]:
    """Standard-tier seconds for each need's filter step (the slowest of its calls, run in parallel).
    Calls go to the provider directly, not through the cache (the cache key ignores the tier), and are
    metered like any other paid call. A need with a refused call is left out."""
    from concurrent.futures import ThreadPoolExecutor

    from econ import spend

    out = []
    for group in calls:
        for c in group:
            spend.guard(spend.provider_of(c.model), llmcall.estimate(c))
        client = llmcall._client(group[0].model, flex=False)
        with ThreadPoolExecutor(max_workers=len(group)) as ex:
            secs = list(ex.map(lambda c, cl=client: _timed(cl, c), group))
        if not any(math.isnan(x) for x in secs):
            out.append(max(secs))
    return out


def run(needs: list[Need], judgments: str, *, probe: int) -> dict:
    sp, f = spec(), spec()["filter"]
    needs = [n for n in needs if n.split == sp["needs"]]
    grades = grid2.grades_by_need(judgments)
    base = grid2.named("plan+q:luna-plan-v2/enriched/none")
    deep = replace(base, context=60)
    cs = systems.chunks()
    per: dict[str, tuple[list[int], list[tuple[llmcall.Call, dict]]]] = {}
    for n in needs:
        rows = grid2.context_rows(deep, n)
        question, _ = systems.queries_for(n, base.query)
        per[n.id] = (rows, calls_for(n, rows, question, f))
    flat = [c for _, cl in per.values() for c, _ in cl]
    replies = llmcall.run_many(flat, flex=f["tier"] == "flex", workers=8)
    by_key = {c.key(): r for c, r in zip(flat, replies, strict=True)}

    out_rows, pairs_judge, pairs_filter, failed, cost = [], [], [], 0, 0.0
    for n in needs:
        rows, cl = per[n.id]
        g = grades.get(n.id, {})
        fg: dict[str, int] | None = {}
        for c, ids in cl:
            rep = by_key[c.key()]
            cost += rep.get("cost_usd", 0.0) if not rep.get("cached") else 0.0
            got = judge.parse(rep, ids) if "error" not in rep else None
            if got is None:
                fg = None
                break
            fg |= got
        if fg is None:
            failed += 1
        else:
            for cid, x in fg.items():
                if cid in g:
                    pairs_judge.append(g[cid])
                    pairs_filter.append(x)
        settings = {
            "adopted@20": rows[:20],
            "adopted@40": rows[:40],
            "adopted@60": rows,
            "oracle@20": select(rows, {cs[r]["chunk_id"]: g.get(cs[r]["chunk_id"], 0) for r in rows}, 20),
            "filter@20": select(rows, fg, 20),
            "filter-useful@40": select_useful(rows, fg, 40),
        }
        rec = {
            "need": n.id,
            "family": n.family,
            "kind": n.kind,
            "split": n.split,
            "filter_failed": fg is None,
        }
        for name, ctx in settings.items():
            m = grid2.per_need(ctx, n, g)
            rec[f"{name}:rel_recall"] = (
                sum(1 for r in ctx if g.get(cs[r]["chunk_id"], 0) >= 2) / sum(1 for x in g.values() if x >= 2)
                if any(x >= 2 for x in g.values())
                else None
            )
            n3 = sum(1 for x in g.values() if x == 3)
            rec[f"{name}:rel3_recall"] = (
                sum(1 for r in ctx if g.get(cs[r]["chunk_id"], 0) == 3) / n3 if n3 else None
            )
            rec[f"{name}:doc_coverage"] = doc_coverage(ctx, g)
            rec[f"{name}:ndcg@10"] = m["ndcg@10"]
            rec[f"{name}:ndcg@20"] = m["ndcg@20"]
            rec[f"{name}:p"] = (
                sum(1 for r in ctx if g.get(cs[r]["chunk_id"], 0) >= 2) / len(ctx) if ctx else None
            )
            rec[f"{name}:passages"] = len(ctx)
            rec[f"{name}:tokens"] = sum(cs[r]["tokens"] for r in ctx)
        rec["filter_grades"] = None if fg is None else dict(sorted(fg.items()))
        out_rows.append(rec)
    grid2.save_rows("filter", "filter-v1", out_rows)

    probe_needs = sorted(needs, key=lambda n: n.id)[:: max(1, len(needs) // probe)][:probe] if probe else []
    lat = latency_probe([[c for c, _ in per[n.id][1]] for n in probe_needs]) if probe_needs else []
    flex_seconds = [
        max(by_key[c.key()].get("usage", {}).get("seconds", 0.0) for c, _ in per[n.id][1]) for n in needs
    ]
    kappa = quadratic_kappa(pairs_judge, pairs_filter) if pairs_judge else float("nan")
    tp = sum(1 for a, b in zip(pairs_judge, pairs_filter, strict=True) if a >= 2 and b >= 2)
    prec = tp / max(1, sum(1 for b in pairs_filter if b >= 2))
    recl = tp / max(1, sum(1 for a in pairs_judge if a >= 2))
    summary = {
        "stage": "filter",
        "needs": len(needs),
        "failed_needs": failed,
        "kappa": kappa,
        "precision_2plus": prec,
        "recall_2plus": recl,
        "latency_standard_s": lat,
        "latency_flex_s_median": statistics.median(flex_seconds) if flex_seconds else None,
        "cost_usd_new": round(cost, 6),
    }
    grid2.save_choice("filter", summary)
    return {"summary": summary, "rows": out_rows, "report": render(out_rows, summary, sp)}


def _mean(rows: list[dict], key: str, fam: str | None) -> float:
    return metrics.mean([r[key] for r in rows if r[key] is not None and (fam is None or r["family"] == fam)])


def render(rows: list[dict], s: dict, sp: dict) -> str:
    fmt = grid2._fmt
    names = ["adopted@20", "filter@20", "oracle@20", "adopted@40", "filter-useful@40", "adopted@60"]
    label = {
        "adopted@20": "Adopted, 20 passages (served today)",
        "filter@20": "**Filter, 60 read, 20 passed**",
        "oracle@20": "Oracle filter (the judge's grades), 60 to 20",
        "adopted@40": "Adopted, 40 passages",
        "filter-useful@40": "Filter: passages it grades 2-3, up to 40",
        "adopted@60": "Adopted, 60 passages",
    }
    lat = s["latency_standard_s"]
    lines = [
        "# A relevance filter: 60 passages read, the best 20 passed",
        "",
        "Grid `retrieval-filter` (eval/grids/retrieval-filter.yaml, committed before any filter call). Filter "
        f"`{PROMPT}` on {sp['filter']['model']} ({sp['filter']['effort']} effort) over the adopted setting's "
        f"60-passage contexts (fully judged), {s['needs']} test needs; {s['failed_needs']} kept the first-stage "
        "order after a failed filter call.",
        "",
        f"Rule fixed in advance: {sp['worth_an_end_to_end_test_if']}",
        "",
    ]
    for fam, title in ((None, "All test needs"), ("explore", "Exploratory"), ("silver", "Silver lookups")):
        n = sum(1 for r in rows if fam is None or r["family"] == fam)
        lines += [
            f"## {title} (n = {n})",
            "",
            "| Context | relevant reached | grade 3 reached | relevant documents | ndcg@10 | precision | passages | tokens |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for nm in names:
            lines.append(
                f"| {label[nm]} | {fmt(_mean(rows, nm + ':rel_recall', fam))} | {fmt(_mean(rows, nm + ':rel3_recall', fam))} | "
                f"{fmt(_mean(rows, nm + ':doc_coverage', fam))} | {fmt(_mean(rows, nm + ':ndcg@10', fam))} | "
                f"{fmt(_mean(rows, nm + ':p', fam))} | {_mean(rows, nm + ':passages', fam):.1f} | "
                f"{_mean(rows, nm + ':tokens', fam):,.0f} |"
            )
        lines.append("")
    lines += [
        "## The filter against the adopted 20 (paired, 95% bootstrap interval)",
        "",
        "| Needs | Metric | Difference | 95% CI | p |",
        "|---|---|---|---|---|",
    ]
    for fam in (None, "explore", "silver"):
        for m in ("rel_recall", "doc_coverage", "ndcg@10"):
            sub = [
                r
                for r in rows
                if (fam is None or r["family"] == fam)
                and r[f"adopted@20:{m}"] is not None
                and r[f"filter@20:{m}"] is not None
            ]
            c = metrics.compare([r[f"adopted@20:{m}"] for r in sub], [r[f"filter@20:{m}"] for r in sub])
            lines.append(
                f"| {fam or 'all'} | {m} | {c['diff']:+.3f} | [{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}] | {c['p']:.3f} |"
            )
    ex = _mean(rows, "filter@20:rel_recall", "explore")
    si = _mean(rows, "filter@20:rel_recall", "silver")
    med = statistics.median(lat) if lat else float("nan")
    ok = ex >= 0.59 and si >= 0.765 - 0.02 and med <= 5.0
    lines += [
        "",
        "## Agreement and cost",
        "",
        f"- The filter's grades against the judge's, on every passage it read: quadratic kappa {s['kappa']:.2f}; "
        f"of the passages the filter grades 2-3, {s['precision_2plus']:.0%} the judge grades 2-3; of the judge's "
        f"2-3 passages, the filter grades {s['recall_2plus']:.0%} 2-3.",
        f"- Latency of the filter step at the standard tier ({len(lat)} needs, a need's calls in parallel): median "
        f"{med:.1f} s, slowest {max(lat) if lat else float('nan'):.1f} s. At the Flex tier the median was "
        f"{s['latency_flex_s_median'] or float('nan'):.1f} s.",
        f"- Spend on this run: ${s['cost_usd_new']:.3f} for the Flex filter calls, plus the standard-tier probe "
        "(in the ledger, purpose `filter:...:latency`).",
        "",
        f"**Against the rule: {'met' if ok else 'not met'}** (exploratory {ex:.3f} against 0.59; silver {si:.3f} "
        f"against 0.745; median latency {med:.1f} s against 5 s).",
        "",
        "## How to read these numbers",
        "",
        "- Every passage in these contexts is judged, so recall here is exact for the passages the search found; "
        "relevant passages no setting ever ranked are not counted.",
        "- The oracle filter uses the judge's own grades, so it is the ceiling for this design, not a result.",
        "- Retrieval only: whether answers use the better 20 needs an end-to-end run.",
    ]
    return "\n".join(lines) + "\n"
