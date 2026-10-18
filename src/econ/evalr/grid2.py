"""Retrieval grid v2 on the judged test set: the pool, the graded metrics, the stages and the report.

Grid: eval/grids/retrieval-v2.yaml (committed before any judgment). Per-need rows go to
eval/runs/retrieval-v2/<stage>/<setting>.jsonl and the report to reports/retrieval-v2-<stage>.md.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace

import yaml

from econ import config
from econ.evalr import judge, metrics, systems
from econ.evalr.judged import Need
from econ.manifest import write_json_atomic, write_text_atomic

PLAIN, ENRICHED = "plain", "enriched:S384-noprefix-nocite.luna-enrich-v1"


def spec() -> dict:
    return yaml.safe_load(config.path("eval/grids/retrieval-v2.yaml").read_text())


def setting_name(s: systems.System) -> str:
    t = "plain" if s.text == PLAIN else "enriched"
    base = f"{s.query}/{t}/{s.reranker or 'none'}"
    if s.lane != "hybrid":
        base = f"{s.lane}:{base}"
    if s.cap != 8:
        base += f"/cap{s.cap}"
    if s.rr_depth != 50 and s.reranker:
        base += f"/rr{s.rr_depth}"
    return base


def make(query: str, text: str, reranker: str | None, **kw) -> systems.System:
    s = systems.System("", query=query, text=PLAIN if text == "plain" else text, reranker=reranker, **kw)
    return replace(s, name=setting_name(s))


def stage1_settings(include_reference: bool = True) -> list[systems.System]:
    st = spec()["stage1"]
    out = []
    for q in st["query"]:
        for t in st["text"]:
            for rr in st["reranker"]:
                out.append(make(q, t, None if rr == "none" else rr))
    if include_reference:
        # The reference rerankers ran on three first stages only (scratch job, see the progress log).
        for rr in spec()["amendment_1"]["reference_rerankers"]:
            for q, t in (("raw", PLAIN), ("plan:luna-plan-v2", ENRICHED), ("raw", ENRICHED)):
                out.append(make(q, t, rr))
    return out


def complexity(s: systems.System) -> int:
    q = {
        "raw": 0,
        "plan:luna-plan-v1": 0,
        "plan:flashlite-plan-v1": 1,
        "plan:luna-plan-v2": 1,
        "plan+q:luna-plan-v2": 1,
        "plan:flashlite-plan-v2": 2,
    }[s.query]
    return q + (s.text != PLAIN) + (s.reranker is not None)


# --- ranking with cached reranker scores ------------------------------------------------------------


_rr: dict[str, systems.RerankCache] = {}


def rr_cache(name: str) -> systems.RerankCache:
    if name not in _rr:
        _rr[name] = systems.RerankCache(systems.cache_key(name, "text", "bf16"))
    return _rr[name]


def context_rows(s: systems.System, need: Need) -> list[int]:
    rows = systems.rank(s, need, rr_cache(s.reranker) if s.reranker else None)
    return systems.context(s, rows)


# --- the pool ----------------------------------------------------------------------------------------


def pool_systems() -> list[tuple[systems.System, int]]:
    """Every system whose context goes into the pool, with how deep."""
    k = spec()["amendment_1"]["pool_depth"]
    out = [(s, k) for s in stage1_settings()]
    out.append((make("raw", "plain", None, lane="bm25"), k))
    out.append((make("raw", "plain", None, lane="dense"), k))
    return out


def build_pool(needs: list[Need]) -> dict[str, list[int]]:
    pool: dict[str, set[int]] = {n.id: set() for n in needs}
    for s, k in pool_systems():
        for n in needs:
            pool[n.id] |= set(context_rows(s, n)[:k])
    return {nid: sorted(rows) for nid, rows in pool.items()}


# --- graded metrics -----------------------------------------------------------------------------------


def _dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def per_need(ctx: list[int], need: Need, grades: dict[str, int]) -> dict:
    cs = systems.chunks()
    ids = [cs[r]["chunk_id"] for r in ctx]
    g = [grades.get(c) for c in ids]
    gain = [(2**x - 1) if x is not None else 0.0 for x in g]
    ideal = sorted((2**x - 1 for x in grades.values()), reverse=True)
    out: dict[str, float | None] = {}
    for k in (10, 20):
        idcg = _dcg(ideal[:k])
        out[f"ndcg@{k}"] = _dcg(gain[:k]) / idcg if idcg > 0 else None
    n_rel = sum(1 for x in grades.values() if x >= 2)
    rel_in = sum(1 for x in g[:20] if x is not None and x >= 2)
    out["rel_recall@20"] = rel_in / n_rel if n_rel else None
    out["p@20"] = rel_in / max(1, len(ctx[:20]))
    out["judged@10"] = sum(1 for x in g[:10] if x is not None) / max(1, len(ctx[:10]))
    out["judged@20"] = sum(1 for x in g[:20] if x is not None) / max(1, len(ctx[:20]))
    if need.golds:
        m = metrics.per_need([cs[r] for r in ctx], need.golds)
        covered = set().union(*metrics.judge([cs[r] for r in ctx[:20]], need.golds)) if ctx else set()
        out["gold_recall@20"] = len(covered) / len(need.golds)
        out["gold_recall@4k_tok"] = m["recall@4k_tok"]
    else:
        out["gold_recall@20"] = out["gold_recall@4k_tok"] = None
    return out


def grades_by_need(name: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for (nid, cid), g in judge.load(name).items():
        out.setdefault(nid, {})[cid] = g
    return out


def evaluate(s: systems.System, needs: list[Need], grades: dict[str, dict[str, int]]) -> list[dict]:
    rows = []
    for n in needs:
        ctx = context_rows(s, n)
        m = per_need(ctx, n, grades.get(n.id, {}))
        rows.append(
            {
                "need": n.id,
                "family": n.family,
                "kind": n.kind,
                "split": n.split,
                **m,
                "context": [systems.chunks()[r]["chunk_id"] for r in ctx],
            }
        )
    return rows


def mean_of(rows: list[dict], metric: str, **where) -> float:
    xs = [r[metric] for r in rows if r[metric] is not None and all(r[k] == v for k, v in where.items())]
    return metrics.mean(xs)


def paired(a: list[dict], b: list[dict], metric: str, **where) -> tuple[list[float], list[float]]:
    xa, xb = [], []
    for ra, rb in zip(a, b, strict=True):
        if any(ra[k] != v for k, v in where.items()):
            continue
        if ra[metric] is None or rb[metric] is None:
            continue
        xa.append(ra[metric])
        xb.append(rb[metric])
    return xa, xb


def save_rows(stage: str, name: str, rows: list[dict]) -> None:
    p = config.path("eval/runs/retrieval-v2") / stage / (name.replace("/", "__").replace(":", "-") + ".jsonl")
    write_text_atomic(p, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def save_choice(stage: str, choice: dict) -> None:
    write_json_atomic(config.path("eval/runs/retrieval-v2") / stage / "choice.json", choice)


# --- stage 1: the factorial, the choice and the report ---------------------------------------------


def latencies() -> dict[str, float]:
    """Seconds to rerank 50 passages in float32 on this machine's 4 vCPU (eval/runs/retrieval-v2/latency.json)."""
    p = config.path("eval/runs/retrieval-v2/latency.json")
    return json.loads(p.read_text()) if p.exists() else {}


def choose(settings: list[systems.System], dev: dict[str, float], margin: float, budget: float) -> str:
    lat = latencies()

    def adoptable(s: systems.System) -> bool:
        return s.reranker is None or lat.get(s.reranker, float("inf")) <= budget

    pool = [s for s in settings if adoptable(s) and dev.get(s.name) is not None]
    best = max(dev[s.name] for s in pool)
    near = [s for s in pool if dev[s.name] >= best - margin]
    return min(near, key=lambda s: (complexity(s), -dev[s.name])).name


def _ci(a: list[float], b: list[float]) -> dict:
    return metrics.compare(a, b)


def run_stage1(needs: list[Need], judgments: str) -> dict:
    sp = spec()
    st, am = sp["stage1"], sp["amendment_1"]
    primary = am["primary"]
    grades = grades_by_need(judgments)
    settings = stage1_settings()
    names = [s.name for s in settings]
    rows = {}
    for s in settings:
        rows[s.name] = evaluate(s, needs, grades)
        save_rows("stage1", s.name, rows[s.name])
    dev = {n: mean_of(rows[n], primary, split="dev") for n in names}
    base = st["baseline"]
    chosen = choose(settings, dev, st["margin"], st["latency_budget_s"])
    g = st["guard"]
    guard = {
        "metric": g["metric"],
        "baseline": mean_of(rows[base], g["metric"], split="dev", family=g["family"]),
        "chosen": mean_of(rows[chosen], g["metric"], split="dev", family=g["family"]),
    }
    guard["passed"] = guard["chosen"] >= guard["baseline"] - g["max_drop"]
    choice = {
        "stage": "stage1",
        "primary": primary,
        "chosen": chosen,
        "baseline": base,
        "dev": dev,
        "guard": guard,
        "latency_s": latencies(),
        "judgments": judgments,
    }
    save_choice("stage1", choice)
    return {"choice": choice, "rows": rows, "settings": settings}


def _fmt(x) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def render_stage1(res: dict, needs: list[Need]) -> str:
    ch, rows, settings = res["choice"], res["rows"], res["settings"]
    primary, base, chosen = ch["primary"], ch["baseline"], ch["chosen"]
    lat = ch["latency_s"]
    test_n = sum(n.split == "test" for n in needs)
    comps, ps = {}, {}
    for s in settings:
        if s.name == base:
            continue
        a, b = paired(rows[base], rows[s.name], primary, split="test")
        comps[s.name] = _ci(a, b)
        ps[s.name] = comps[s.name]["p"]
    adj = metrics.holm(ps)
    order = sorted(settings, key=lambda s: -ch["dev"][s.name])
    lines = [
        "# Retrieval grid v2, stage 1: query plan x enrichment x reranker",
        "",
        f"Grid `retrieval-v2` (eval/grids/retrieval-v2.yaml, with amendment 1), judged test set: {len(needs)} needs, "
        f"{len(needs) - test_n} dev and {test_n} test. Judgments `{ch['judgments']}` (gemini-3.8-flash, 0-3). "
        "Generated by `econ eval-retrieval-v2`.",
        "",
        f"**Chosen on dev: `{chosen}`** ({primary} {ch['dev'][chosen]:.3f}; baseline `{base}` {ch['dev'][base]:.3f}; "
        f"best on dev {max(v for v in ch['dev'].values() if v is not None):.3f}).",
        "",
        f"Guard ({ch['guard']['metric']}, silver dev): baseline {ch['guard']['baseline']:.3f}, chosen "
        f"{ch['guard']['chosen']:.3f}: {'passed' if ch['guard']['passed'] else 'FAILED'}.",
        "",
        "## Every setting, best dev first",
        "",
        f"`{primary}` on dev and test; the test difference from the baseline with its paired bootstrap 95% "
        "interval and a Holm-adjusted paired randomisation p over all settings; judged@10 on test (the share of "
        "the top 10 that was judged); complexity is the number of components added to the service; latency is "
        "seconds to rerank 50 passages in float32 on 4 vCPU.",
        "",
        "| Setting | Cx | Latency | Dev | Test | Test vs baseline | 95% CI | p (Holm) | judged@10 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in order:
        t = mean_of(rows[s.name], primary, split="test")
        j = mean_of(
            rows[s.name], "judged@10" if "judged@10" in rows[s.name][0] else "judged@20", split="test"
        )
        mark = " **(chosen)**" if s.name == chosen else (" (baseline)" if s.name == base else "")
        lt = f"{lat[s.reranker]:.1f}" if s.reranker and s.reranker in lat else ""
        if s.name == base:
            lines.append(
                f"| `{s.name}`{mark} | {complexity(s)} | {lt} | {_fmt(ch['dev'][s.name])} | {_fmt(t)} | | | | {_fmt(j)} |"
            )
        else:
            c = comps[s.name]
            lines.append(
                f"| `{s.name}`{mark} | {complexity(s)} | {lt} | {_fmt(ch['dev'][s.name])} | {_fmt(t)} | {c['diff']:+.3f} | "
                f"[{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}] | {adj[s.name]:.3f} | {_fmt(j)} |"
            )
    sec = ["ndcg@10", "ndcg@20", "rel_recall@20", "p@20", "gold_recall@20", "gold_recall@4k_tok"]
    lines += [
        "",
        "## The chosen setting and the baseline on test, by family",
        "",
        "| Setting | Family | n | " + " | ".join(sec) + " |",
        "|---|---|---|" + "---|" * len(sec),
    ]
    for name in (base, chosen):
        for fam in ("silver", "explore"):
            n = sum(1 for r in rows[name] if r["split"] == "test" and r["family"] == fam)
            vals = [_fmt(mean_of(rows[name], m, split="test", family=fam)) for m in sec]
            lines.append(f"| `{name}` | {fam} | {n} | " + " | ".join(vals) + " |")
    kinds = sorted({r["kind"] for r in rows[base]})
    lines += [
        "",
        f"## `{primary}` by kind (dev and test together)",
        "",
        "| Setting | "
        + " | ".join(f"{k} (n={sum(r['kind'] == k for r in rows[base])})" for k in kinds)
        + " |",
        "|---|" + "---|" * len(kinds),
    ]
    for name in (base, chosen):
        lines.append(
            f"| `{name}` | " + " | ".join(_fmt(mean_of(rows[name], primary, kind=k)) for k in kinds) + " |"
        )
    lines += [
        "",
        "## How to read these numbers",
        "",
        "- Each need's pooled passages (the top 10 of every setting here, plus the judge pilot's top 20 for 12 "
        "needs) were graded 0-3 by gemini-3.8-flash against the need's narrative: 3 directly answers a key part, "
        "2 helps answer part, 1 on topic but no use, 0 not relevant. Claude's blind grades of 100 of those pairs "
        "agreed with the judge at quadratic kappa 0.92.",
        "- `ndcg@10` rewards highly graded passages near the top of the context (gain 2^grade - 1). The ideal "
        "ranking is built from every judged passage of the need, so it is comparable across settings.",
        "- `rel_recall@20` is the share of the need's judged-relevant passages (grade 2 or 3) that reach the "
        "answer model's 20 passages. Unjudged passages count as not relevant, so a setting that surfaces "
        "unjudged passages is understated; judged@10 shows how much.",
        "- `gold_recall@*` uses the silver set's gold spans, the old yardstick, for silver needs only.",
        "- Dev chooses, test reports. With 92 test needs, differences under about 0.03 are hard to separate.",
    ]
    return "\n".join(lines) + "\n"


# --- stage 2 (the per-document cap) and the final report -------------------------------------------


def named(name: str) -> systems.System:
    """Rebuild a setting from its name, e.g. 'plan:luna-plan-v2/enriched/ettin-32m/cap5'."""
    parts = name.split("/")
    q, t, rr = parts[0], parts[1], parts[2]
    kw = {}
    for extra in parts[3:]:
        if extra.startswith("cap"):
            kw["cap"] = int(extra[3:])
        elif extra.startswith("rr"):
            kw["rr_depth"] = int(extra[2:])
    return make(q, PLAIN if t == "plain" else ENRICHED, None if rr == "none" else rr, **kw)


def _choice_of(stage: str) -> dict:
    return json.loads((config.path("eval/runs/retrieval-v2") / stage / "choice.json").read_text())


def run_stage2(needs: list[Need], judgments: str) -> dict:
    sp = spec()
    st2 = sp["stage2"]
    primary = sp["amendment_1"]["primary"]
    base = named(_choice_of("stage1")["chosen"])
    grades = grades_by_need(judgments)
    settings = [replace(base, cap=c, name=setting_name(replace(base, cap=c))) for c in st2["cap"]]
    rows = {s.name: evaluate(s, needs, grades) for s in settings}
    for s in settings:
        save_rows("stage2", s.name, rows[s.name])
    dev = {s.name: mean_of(rows[s.name], primary, split="dev") for s in settings}
    keep = settings[0].name  # cap 8, the configured value
    best = max(dev, key=dev.get)
    chosen = best if dev[best] > dev[keep] + st2["margin"] else keep
    choice = {"stage": "stage2", "primary": primary, "chosen": chosen, "dev": dev, "judgments": judgments}
    save_choice("stage2", choice)
    lines = [
        "# Retrieval grid v2, stage 2: the per-document cap",
        "",
        f"On stage 1's choice `{base.name}`. Rule: {st2['rule']} **Chosen: `{chosen}`.**",
        "",
        f"| Setting | Dev {primary} | Test {primary} | judged@10 (test) | rel_recall@20 (test) |",
        "|---|---|---|---|---|",
    ]
    for s in settings:
        r = rows[s.name]
        lines.append(
            f"| `{s.name}` | {_fmt(dev[s.name])} | {_fmt(mean_of(r, primary, split='test'))} | "
            f"{_fmt(mean_of(r, 'judged@10', split='test'))} | {_fmt(mean_of(r, 'rel_recall@20', split='test'))} |"
        )
    return {"choice": choice, "rows": rows, "report": "\n".join(lines) + "\n"}


def topup_targets(needs: list[Need], names: list[str], depth: int, grades: dict) -> dict[str, list[str]]:
    """Unjudged passages in the top `depth` of the named settings' contexts, per need."""
    out: dict[str, set[str]] = {n.id: set() for n in needs}
    for name in names:
        s = named(name)
        for n in needs:
            for r in context_rows(s, n)[:depth]:
                cid = systems.chunks()[r]["chunk_id"]
                if cid not in grades.get(n.id, {}):
                    out[n.id].add(cid)
    return {k: sorted(v) for k, v in out.items() if v}


def run_final(needs: list[Need], judgments: str) -> dict:
    """The chosen setting against the baseline on test, fully judged to depth 20 (after the top-up)."""
    sp = spec()
    base = sp["stage1"]["baseline"]
    chosen = (
        _choice_of("stage2")["chosen"]
        if (config.path("eval/runs/retrieval-v2/stage2/choice.json")).exists()
        else _choice_of("stage1")["chosen"]
    )
    grades = grades_by_need(judgments)
    a, b = evaluate(named(base), needs, grades), evaluate(named(chosen), needs, grades)
    save_rows("final", base, a)
    save_rows("final", chosen, b)
    ms = ["ndcg@10", "ndcg@20", "rel_recall@20", "p@20", "gold_recall@20", "gold_recall@4k_tok"]
    comps, ps = {}, {}
    for fam in ("all", "silver", "explore"):
        for m in ms:
            where = {"split": "test"} | ({} if fam == "all" else {"family": fam})
            xa, xb = paired(a, b, m, **where)
            if len(xa) < 5:
                continue
            comps[(fam, m)] = (metrics.mean(xa), metrics.mean(xb), metrics.compare(xa, xb), len(xa))
            ps[f"{fam}:{m}"] = comps[(fam, m)][2]["p"]
    adj = metrics.holm(ps)
    lines = [
        "# Retrieval grid v2: the choice against the baseline on test",
        "",
        f"Baseline `{base}` (the service today); chosen `{chosen}`. Judgments `{judgments}`, topped up so both "
        "settings' 20-passage contexts are fully judged on every need.",
        "",
        f"judged@20 on test: baseline {_fmt(mean_of(a, 'judged@20', split='test'))}, chosen {_fmt(mean_of(b, 'judged@20', split='test'))}.",
        "",
        "| Needs | Metric | n | Baseline | Chosen | Difference | 95% CI | p (Holm) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (fam, m), (ma, mb, c, n) in comps.items():
        lines.append(
            f"| {fam} | {m} | {n} | {ma:.3f} | {mb:.3f} | {c['diff']:+.3f} | [{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}] | {adj[f'{fam}:{m}']:.3f} |"
        )
    # Robustness: the stage-1 rule again, on every judgment including the top-up (which raised each need's
    # ideal ranking). The recorded choice stands either way; this shows whether it depended on the pool.
    st = sp["stage1"]
    settings = stage1_settings(include_reference=False)
    dev_all = {x.name: mean_of(evaluate(x, needs, grades), "ndcg@10", split="dev") for x in settings}
    again = choose(settings, dev_all, st["margin"], st["latency_budget_s"])
    top = sorted(dev_all.items(), key=lambda kv: -kv[1])[:5]
    same = again == _choice_of("stage1")["chosen"]
    lines += [
        "",
        "## Robustness: the stage-1 rule on every judgment",
        "",
        f"Re-run on all judgments (pool and top-up), the rule chooses `{again}`"
        + (" (the same setting)." if same else " (a different setting; see the decision log).")
        + " Best five on dev by ndcg@10: "
        + "; ".join(f"`{k}` {v:.3f}" for k, v in top)
        + ".",
    ]
    choice = {
        "stage": "final",
        "primary": "ndcg@20",
        "chosen": chosen,
        "baseline": base,
        "rule_again": again,
        "dev": {chosen: mean_of(b, "ndcg@20", split="dev"), base: mean_of(a, "ndcg@20", split="dev")},
    }
    save_choice("final", choice)
    return {"choice": choice, "report": "\n".join(lines) + "\n"}
