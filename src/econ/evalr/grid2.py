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
    if s.alpha != 0.7:
        base += f"/a{s.alpha:g}"
    if s.rr_input != "text" and s.reranker:
        base += "/noted"
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


def rr_cache(name: str, rr_input: str = "text") -> systems.RerankCache:
    key = systems.cache_key(name, rr_input.split(":")[0], "bf16")
    if key not in _rr:
        _rr[key] = systems.RerankCache(key)
    return _rr[key]


def score_missing(settings: list[systems.System], needs: list[Need]) -> int:
    """Score, locally and free, the reranker pairs these settings need that the caches lack (chunks whose
    text changed, as in the OCR repair of D-022, have none). Returns how many pairs were scored."""
    n_new = 0
    for s in settings:
        if not s.reranker:
            continue
        cache = rr_cache(s.reranker, s.rr_input)
        pairs = []
        for n in needs:
            rq, rows = systems.candidates(s, n)
            pairs += [(rq, systems.passage(r, s.rr_input)) for r in rows[: s.rr_depth]]
        todo = cache.missing(pairs)
        if todo:
            systems.score_pairs(s.reranker, s.rr_input, todo)
            _rr.pop(cache.key, None)
            n_new += len(todo)
    return n_new


def context_rows(s: systems.System, need: Need) -> list[int]:
    rows = systems.rank(s, need, rr_cache(s.reranker, s.rr_input) if s.reranker else None)
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
        elif extra.startswith("a"):
            kw["alpha"] = float(extra[1:])
        elif extra == "noted":
            kw["rr_input"] = "noted:" + ENRICHED.split(":", 1)[1]
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
    score_missing(settings, needs)
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


# --- grid v3: variants of the adopted setting -----------------------------------------------------


def spec_v3() -> dict:
    return yaml.safe_load(config.path("eval/grids/retrieval-v3.yaml").read_text())


def v3_settings() -> list[str]:
    sp = spec_v3()
    base = sp["adopted"]
    q, t, _ = base.split("/")
    v = sp["variants"]
    names = [f"{base}/a{a:g}" for a in v["fusion_weight"]["alpha"]]
    names += [f"{q}/{t}/{rr}/noted" for rr in v["reranker_reads_notes"]["rerankers"]]
    names += [f"{v['answer_shaped_query']['query']}/{t}/none"]
    return names


def run_v3(needs: list[Need], judgments: str, latency: dict[str, float]) -> dict:
    sp = spec_v3()
    base = sp["adopted"]
    grades = grades_by_need(judgments)
    rows = {n: evaluate(named(n), needs, grades) for n in [base, *v3_settings()]}
    for n, r in rows.items():
        save_rows("v3", n, r)
    dev = {n: mean_of(r, "ndcg@10", split="dev") for n, r in rows.items()}
    ok = []
    for n in v3_settings():
        rr = named(n).reranker
        fast = rr is None or latency.get(rr, float("inf")) <= 2.5
        if fast and dev[n] > dev[base] + 0.02:
            ok.append(n)
    chosen = max(ok, key=dev.get) if ok else base
    lines = [
        "# Retrieval grid v3: variants of the adopted setting",
        "",
        f"Grid `retrieval-v3` (eval/grids/retrieval-v3.yaml, committed before any number). Adopted setting `{base}`. "
        f"Judgments `{judgments}`, topped up so every variant's top 10 is judged. Rule: {sp['rule']}",
        "",
        f"**Outcome: `{chosen}`**"
        + (" (the adopted setting stays)." if chosen == base else " replaces the adopted setting."),
        "",
        "| Setting | Latency (50 passages) | Dev ndcg@10 | Test ndcg@10 | Test vs adopted [95% CI] | judged@10 | rel_recall@20 (test) |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in [base, *v3_settings()]:
        rr = named(n).reranker
        lt = f"{latency[rr]:.1f} s" if rr and rr in latency else ""
        t = mean_of(rows[n], "ndcg@10", split="test")
        if n == base:
            cmp = "adopted"
        else:
            a, b = paired(rows[base], rows[n], "ndcg@10", split="test")
            c = metrics.compare(a, b)
            cmp = f"{c['diff']:+.3f} [{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}]"
        lines.append(
            f"| `{n}` | {lt} | {_fmt(dev[n])} | {_fmt(t)} | {cmp} | {_fmt(mean_of(rows[n], 'judged@10'))} | "
            f"{_fmt(mean_of(rows[n], 'rel_recall@20', split='test'))} |"
        )
    choice = {
        "stage": "v3",
        "primary": "ndcg@10",
        "chosen": chosen,
        "adopted": base,
        "dev": dev,
        "qualified": ok,
    }
    save_choice("v3", choice)
    return {"choice": choice, "report": "\n".join(lines) + "\n"}


# --- context depth: the adopted ranking at 20, 40 and 60 passages ----------------------------------


def spec_depth() -> dict:
    return yaml.safe_load(config.path("eval/grids/retrieval-depth.yaml").read_text())


def depth_needs(needs: list[Need]) -> list[Need]:
    want = spec_depth()["needs"]
    return [n for n in needs if want == "all" or n.split == want]


def depth_contexts(needs: list[Need]) -> dict[int, dict[str, list[int]]]:
    """Rows of the adopted setting's context at each depth; the per-document cap and the first stage are
    the adopted ones, so each depth extends the one before it."""
    sp = spec_depth()
    base = named(sp["adopted"])
    return {k: {n.id: context_rows(replace(base, context=k), n) for n in needs} for k in sp["depths"]}


def depth_topup_targets(needs: list[Need], grades: dict) -> dict[str, list[str]]:
    """Unjudged passages in the deepest context, per need."""
    deepest = depth_contexts(needs)[max(spec_depth()["depths"])]
    cs = systems.chunks()
    out = {}
    for n in needs:
        miss = sorted({cs[r]["chunk_id"] for r in deepest[n.id]} - set(grades.get(n.id, {})))
        if miss:
            out[n.id] = miss
    return out


def reocr_topup_targets(needs: list[Need], grades: dict) -> dict[str, list[str]]:
    """Unjudged passages in every context a reported number was fully judged on, after the OCR repair
    (D-022) changed the chunks of the two scanned reports: grid v2's final (the baseline and the choice to
    depth 20, test needs), grid v3's variants without a reranker (to depth 10, all needs; the rerankers were
    rejected and their cached scores predate the repair), the depth grid (the adopted ranking to 60, its
    needs) and the served search's ndcg@10 (the adopted setting to depth 10, all needs)."""
    out: dict[str, set[str]] = {n.id: set() for n in needs}
    test = [n for n in needs if n.split == "test"]
    final = [spec()["stage1"]["baseline"], _choice_of("final")["chosen"]]
    v3 = [x for x in v3_settings() if not x.endswith("/noted")]
    parts = [
        topup_targets(test, final, 20, grades),
        topup_targets(needs, [*v3, final[1]], 10, grades),
        depth_topup_targets(depth_needs(needs), grades),
    ]
    for part in parts:
        for nid, cids in part.items():
            out[nid].update(cids)
    return {k: sorted(v) for k, v in out.items() if v}


def per_need_depth(ctx: list[int], k: int, grades: dict[str, int]) -> dict:
    cs = systems.chunks()
    rows = ctx[:k]
    g = [grades.get(cs[r]["chunk_id"]) for r in rows]
    n_rel = sum(1 for x in grades.values() if x >= 2)
    n_rel3 = sum(1 for x in grades.values() if x == 3)
    rel = sum(1 for x in g if x is not None and x >= 2)
    return {
        f"rel_recall@{k}": rel / n_rel if n_rel else None,
        f"rel3_recall@{k}": sum(1 for x in g if x == 3) / n_rel3 if n_rel3 else None,
        f"p@{k}": rel / len(rows) if rows else None,
        f"passages@{k}": len(rows),
        f"tokens@{k}": sum(cs[r]["tokens"] for r in rows),
        f"judged@{k}": sum(1 for x in g if x is not None) / len(rows) if rows else None,
    }


def breadth_rule(rule: str, need: Need, plan: dict) -> int:
    """The context depth a breadth rule gives a need (grid retrieval-depth)."""
    deep, shallow = max(spec_depth()["depths"]), min(spec_depth()["depths"])
    if rule == "oracle":
        return deep if need.family == "explore" else shallow
    if rule == "plan_queries":
        return deep if len(plan["queries"]) >= 2 else shallow
    raise ValueError(rule)


def run_depth(needs: list[Need], judgments: str) -> dict:
    from econ.evalr import plans as plans_mod

    sp = spec_depth()
    depths = sp["depths"]
    needs = depth_needs(needs)
    grades = grades_by_need(judgments)
    ctxs = depth_contexts(needs)
    deepest = max(depths)
    cs = systems.chunks()
    plan = plans_mod.load(sp["adopted"].split("/")[0].split(":", 1)[1])
    rows = []
    for n in needs:
        g = grades.get(n.id, {})
        r = {"need": n.id, "family": n.family, "kind": n.kind, "split": n.split}
        for k in depths:
            r |= per_need_depth(ctxs[deepest][n.id], k, g)
        for rule in sp["breadth_rules"]:
            r[f"depth:{rule}"] = breadth_rule(rule, n, plan[n.id])
        r["n_rel"] = sum(1 for x in g.values() if x >= 2)
        r["context"] = [cs[x]["chunk_id"] for x in ctxs[deepest][n.id]]
        rows.append(r)
    save_rows("depth", f"{sp['adopted']}/ctx{deepest}", rows)

    def band_p(fam: str | None, lo: int, hi: int) -> float:
        rel = tot = 0
        for r in rows:
            if fam and r["family"] != fam:
                continue
            band = r["context"][lo:hi]
            g = grades.get(r["need"], {})
            tot += len(band)
            rel += sum(1 for c in band if g.get(c, 0) >= 2)
        return rel / tot if tot else float("nan")

    fams = [("all", None), ("silver", "silver"), ("explore", "explore")]
    lines = [
        "# Context depth: the adopted ranking at " + ", ".join(map(str, depths)) + " passages",
        "",
        f"Grid `retrieval-depth` (eval/grids/retrieval-depth.yaml, committed before any number). Setting "
        f"`{sp['adopted']}` with its context extended; the first {min(depths)} passages are the served "
        f"context. {len(needs)} {sp['needs']} needs. Judgments `{judgments}`, topped up so the {deepest}-passage "
        f"contexts are fully judged (judged@{deepest} {_fmt(mean_of(rows, f'judged@{deepest}'))}).",
        "",
        "## Evidence reached, by depth",
        "",
        "| Needs | n | Metric | " + " | ".join(f"{k} passages" for k in depths) + " |",
        "|---|---|---|" + "---|" * len(depths),
    ]
    for label, fam in fams:
        where = {} if fam is None else {"family": fam}
        n = sum(1 for r in rows if fam is None or r["family"] == fam)
        for m, name in (
            ("rel_recall", "relevant (grade 2-3) reached"),
            ("rel3_recall", "grade 3 reached"),
            ("p", "precision"),
            ("passages", "passages (mean)"),
            ("tokens", "tokens (mean)"),
        ):
            vals = [mean_of(rows, f"{m}@{k}", **where) for k in depths]
            fmt = (
                (lambda x: f"{x:,.0f}")
                if m == "tokens"
                else (lambda x: f"{x:.1f}")
                if m == "passages"
                else _fmt
            )
            lines.append(f"| {label} | {n} | {name} | " + " | ".join(fmt(v) for v in vals) + " |")
    lines += [
        "",
        "## Precision of each band (grade 2-3 share of the passages added)",
        "",
        "| Needs | "
        + " | ".join(f"{a + 1}-{b}" for a, b in zip([0, *depths[:-1]], depths, strict=True))
        + " |",
        "|---|" + "---|" * len(depths),
    ]
    for label, fam in fams:
        bands = [band_p(fam, a, b) for a, b in zip([0, *depths[:-1]], depths, strict=True)]
        lines.append(f"| {label} | " + " | ".join(_fmt(x) for x in bands) + " |")
    lines += [
        "",
        f"## Gains over {min(depths)} passages (paired, test needs)",
        "",
        "| Needs | Depth | relevant reached: difference [95% CI] |",
        "|---|---|---|",
    ]
    for label, fam in fams:
        for k in depths[1:]:
            sub = [
                r for r in rows if (fam is None or r["family"] == fam) and r[f"rel_recall@{k}"] is not None
            ]
            xa = [r[f"rel_recall@{min(depths)}"] for r in sub]
            xb = [r[f"rel_recall@{k}"] for r in sub]
            c = metrics.compare(xa, xb)
            lines.append(f"| {label} | {k} | {c['diff']:+.3f} [{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}] |")
    lines += [
        "",
        "## Breadth rules: a deeper context only for broad questions",
        "",
        "| Rule | Needs given the deeper context | relevant reached (all) | silver | explore | passages (mean) | tokens (mean) |",
        "|---|---|---|---|---|---|---|",
    ]

    def ruled(rule: str | int, fam: str | None, metric: str) -> float:
        xs = []
        for r in rows:
            if fam and r["family"] != fam:
                continue
            k = rule if isinstance(rule, int) else r[f"depth:{rule}"]
            if r[f"{metric}@{k}"] is not None:
                xs.append(r[f"{metric}@{k}"])
        return metrics.mean(xs)

    for rule in [min(depths), *sp["breadth_rules"], deepest]:
        label = f"always {rule}" if isinstance(rule, int) else f"`{rule}`"
        given = (
            ("none" if rule == min(depths) else "all")
            if isinstance(rule, int)
            else ", ".join(
                f"{sum(1 for r in rows if r['family'] == f and r[f'depth:{rule}'] == deepest)}/"
                f"{sum(1 for r in rows if r['family'] == f)} {f}"
                for f in ("silver", "explore")
            )
        )
        lines.append(
            f"| {label} | {given} | {_fmt(ruled(rule, None, 'rel_recall'))} | {_fmt(ruled(rule, 'silver', 'rel_recall'))} | "
            f"{_fmt(ruled(rule, 'explore', 'rel_recall'))} | {ruled(rule, None, 'passages'):.1f} | {ruled(rule, None, 'tokens'):,.0f} |"
        )
    reach = [r for r in rows if r["family"] == "explore"]
    lines += [
        "",
        "## How to read these numbers",
        "",
        "- Recall is the share of a need's judged grade-2/3 passages in the context. Passages no setting ever "
        "ranked were never judged, so every recall is an upper bound; the top-up found new relevant passages, "
        "so the 20-passage figure is below the one reported in D-013.",
        f"- The per-document cap (8) and the first stage's depth (50 a query) stop some contexts short: "
        f"{sum(1 for r in rows if r[f'passages@{deepest}'] < deepest)} of {len(rows)} needs have fewer than "
        f"{deepest} passages ({sum(1 for r in reach if r[f'passages@{deepest}'] < deepest)} of {len(reach)} exploratory).",
        f"- Exploratory needs with more relevant passages than the deepest context holds: "
        f"{sum(1 for r in reach if r['n_rel'] > deepest)} of {len(reach)}.",
        "- Retrieval only. Whether the answer model uses the extra passages, and what they cost in latency, "
        "needs an end-to-end run.",
    ]
    choice = {
        "stage": "depth",
        "adopted": sp["adopted"],
        "depths": depths,
        "needs": len(rows),
        "judgments": judgments,
    }
    save_choice("depth", choice)
    return {"choice": choice, "rows": rows, "report": "\n".join(lines) + "\n"}
