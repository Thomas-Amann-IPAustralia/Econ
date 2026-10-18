"""The three measurement stages of a retrieval grid, their choice rules and their reports.

The grid file (eval/grids/<grid>.yaml) holds the settings in rule order, the primary metric, the tie
margin and the baseline. It is committed before any number exists; the decision entry names that commit.
"""

from __future__ import annotations

import json
import time

from econ import config
from econ.evalr import metrics, testset
from econ.evalr.retrieval import Cell, grid_spec, run_dir, save, summarise, vec_stats
from econ.manifest import Run, StageError, write_json_atomic, write_text_atomic

SECONDARY = ["ndcg@10", "mrr@10", "recall@10", "recall@2k_tok", "recall@4k_tok", "recall@8k_tok", "doc_hit@5"]


def choose(names: list[str], dev: dict[str, float], margin: float) -> str:
    """The first setting, in the grid's order, within `margin` of the best dev score."""
    best = max(dev.values())
    return next(n for n in names if dev[n] >= best - margin)


def _choice(grid: str, stage: str) -> dict:
    p = run_dir(grid, stage) / "choice.json"
    if not p.exists():
        raise StageError(f"stage `{stage}` has no choice yet; run it first", item=grid)
    return json.loads(p.read_text())


def _resolve(value, grid: str):
    """Grid values like '@chunking' refer to an earlier stage's choice."""
    if isinstance(value, str) and value.startswith("@"):
        return _choice(grid, value[1:])["chosen"]
    return value


def run_stage(run: Run, grid: str, stage: str) -> dict:
    spec = grid_spec(grid)
    st = spec["stages"][stage]
    needs = testset.load(config.path(spec["testset"]))
    run.counts["needs"] = len(needs)
    run.counts["dev"] = sum(n.split == "dev" for n in needs)
    settings: list[dict] = []
    if stage == "chunking":
        for s in st["strategies"]:
            settings.append({"name": s, "strategy": s, "embedders": st["embedders"], "lane": st["lane"]})
    elif stage == "embedders":
        strategy = _resolve(st["strategy"], grid)
        for e in st["candidates"]:
            settings.append({"name": e, "strategy": strategy, "embedders": [e], "lane": st["lane"]})
    elif stage == "fusion":
        strategy, emb = _resolve(st["strategy"], grid), _resolve(st["embedder"], grid)
        for lane in st["lanes"]:
            settings.append({"name": lane, "strategy": strategy, "embedders": [emb], "lane": lane})
    else:
        raise StageError(f"unknown stage {stage}")

    primary = st["primary"]
    results: dict[str, list[dict]] = {}
    extra: dict[str, dict] = {}
    cells: dict[tuple, Cell] = {}
    for s in settings:
        per_emb = []
        for e in s["embedders"]:
            key = (s["strategy"], e)
            t0 = time.time()
            if key not in cells:
                cells.clear()  # one model in memory at a time
                cells[key] = Cell(s["strategy"], e)
            cell = cells[key]
            rows = cell.score(needs, s["lane"])
            save(grid, stage, f"{s['name']}.{e}.{s['lane']}", rows)
            per_emb.append(rows)
            extra.setdefault(s["name"], {})[e] = {
                "seconds": round(time.time() - t0, 1),
                **vec_stats(cell),
                "chunks": len(cell.chunks),
            }
            # Lanes that ignore the embedder are reported once, under the embedder that ran them.
            print(
                f"[{stage}] {s['name']} / {e} / {s['lane']}: dev {primary} = {summarise(rows, 'dev', primary):.3f}",
                flush=True,
            )
        # Average the metrics over the stage's embedders, need by need.
        avg = []
        for i, r in enumerate(per_emb[0]):
            row = dict(r)
            for m in SECONDARY + [primary]:
                row[m] = metrics.mean([pe[i][m] for pe in per_emb])
            avg.append(row)
        results[s["name"]] = avg

    names = [s["name"] for s in settings]
    dev = {n: summarise(results[n], "dev", primary) for n in names}
    chosen = choose(names, dev, st["margin"])
    choice = {
        "stage": stage,
        "chosen": chosen,
        "primary": primary,
        "margin": st["margin"],
        "dev": dev,
        "baseline": st["baseline"],
        "rule": st["rule"],
    }
    write_json_atomic(run_dir(grid, stage) / "choice.json", choice)
    report = render(grid, stage, spec, st, settings, results, dev, chosen, extra, needs)
    out = config.path(config.pipeline().paths.reports) / f"retrieval-{stage}.md"
    write_text_atomic(out, report)
    run.add_output(out)
    run.counts["settings"] = len(settings)
    return choice


def _fmt(x: float) -> str:
    return f"{x:.3f}"


def render(grid, stage, spec, st, settings, results, dev, chosen, extra, needs) -> str:
    primary, base = st["primary"], st["baseline"]
    names = [s["name"] for s in settings]
    test_n = sum(n.split == "test" for n in needs)
    lines = [
        f"# Retrieval measurement: {stage}",
        "",
        f"Grid `{grid}` (eval/grids/{grid}.yaml), test set `{spec['testset']}`: {len(needs)} needs, "
        f"{len(needs) - test_n} dev and {test_n} test. Generated by `econ eval-retrieval --stage {stage}`.",
        "",
        f"**Rule (fixed before any number):** {st['rule']}",
        "",
        f"**Chosen on dev: `{chosen}`** ({primary} {_fmt(dev[chosen])}; best on dev {_fmt(max(dev.values()))}).",
        "",
        "## Primary metric",
        "",
        f"`{primary}` by setting, in rule order. The test column compares each setting with the baseline "
        f"`{base}` on the same test needs: the difference, its paired bootstrap 95% interval, and a "
        "Holm-adjusted paired randomisation p-value. An interval that includes 0 is not a gain.",
        "",
        f"| Setting | Dev | Test | Test vs `{base}` | 95% CI | p (Holm) |",
        "|---|---|---|---|---|---|",
    ]
    test_rows = {n: [r for r in results[n] if r["split"] == "test"] for n in names}
    comps, ps = {}, {}
    for n in names:
        if n == base:
            continue
        comps[n] = metrics.compare([r[primary] for r in test_rows[base]], [r[primary] for r in test_rows[n]])
        ps[n] = comps[n]["p"]
    adj = metrics.holm(ps) if ps else {}
    for n in names:
        t = metrics.mean([r[primary] for r in test_rows[n]])
        mark = " **(chosen)**" if n == chosen else ""
        if n == base:
            lines.append(f"| `{n}`{mark} | {_fmt(dev[n])} | {_fmt(t)} | baseline | | |")
        else:
            c = comps[n]
            lines.append(
                f"| `{n}`{mark} | {_fmt(dev[n])} | {_fmt(t)} | {c['diff']:+.3f} | "
                f"[{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}] | {adj[n]:.3f} |"
            )
    lines += [
        "",
        "## All metrics on test",
        "",
        "| Setting | " + " | ".join(SECONDARY) + " |",
        "|---|" + "---|" * len(SECONDARY),
    ]
    for n in names:
        vals = [metrics.mean([r[m] for r in test_rows[n]]) for m in SECONDARY]
        lines.append(f"| `{n}` | " + " | ".join(_fmt(v) for v in vals) + " |")
    kinds = sorted({r["kind"] for r in results[names[0]]})
    lines += [
        "",
        f"## `{primary}` by kind of need (dev and test together)",
        "",
        "| Setting | "
        + " | ".join(f"{k} (n={sum(r['kind'] == k for r in results[names[0]])})" for k in kinds)
        + " |",
        "|---|" + "---|" * len(kinds),
    ]
    for n in names:
        vals = [metrics.mean([r[primary] for r in results[n] if r["kind"] == k]) for k in kinds]
        lines.append(f"| `{n}` | " + " | ".join(_fmt(v) for v in vals) + " |")
    lines += [
        "",
        "## Runs",
        "",
        "| Setting | Embedder | Chunks | Dim | Seconds (embed + rank) |",
        "|---|---|---|---|---|",
    ]
    for n in names:
        for e, x in extra[n].items():
            lines.append(f"| `{n}` | `{e}` | {x['chunks']} | {x.get('dim', '')} | {x['seconds']} |")
    lines += [
        "",
        "## How to read these numbers",
        "",
        "- Each need has one or more gold passages, quoted verbatim from a document. A chunk *covers* a gold "
        "passage when it holds at least half of its characters. Gains are novelty-based: a chunk scores only "
        "for gold passages that no higher-ranked chunk already covered.",
        "- `recall@4k_tok` is the share of a need's gold passages that reach the answer model when the top "
        "chunks fill 4,000 tokens of context. It is fair across chunk sizes; `recall@10` is not, because ten "
        "large chunks hold more text than ten small ones.",
        "- `ndcg@10` rewards finding the gold passages near the top. `doc_hit@5` asks only whether a gold "
        "document appears in the top five.",
        "- The test set is a silver standard: one author (Claude) wrote each question from a passage, so it "
        "measures finding the passage a question was written from. Other passages that also answer it count "
        "as misses, which understates every setting alike. Treat small differences as ties.",
    ]
    return "\n".join(lines) + "\n"
