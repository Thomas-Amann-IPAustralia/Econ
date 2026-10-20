"""Grid wipo-v1 (D-033): how the WIPO documents enter the index, measured without model calls.

Each variant is a whole corpus (the 24 IP Australia documents plus the WIPO documents, prepared one way),
chunked under the adopted strategy and ranked by the adopted hybrid search, with the question as the only
query. The IP Australia chunks carry their context notes (D-013) as served; the WIPO chunks have none yet
(notes are paid), which favours the IP Australia passages in a mixed ranking.

Variants (eval/grids/wipo-v1.yaml):
- `ipa-only`: today's corpus; the baseline for the IP Australia needs.
- `docling`: the WIPO PDFs as parsed, like every other document.
- `docling-prefix`: as `docling`, with the document title and section path in front of each WIPO chunk for
  search (the prefix the IP Australia chunks dropped in D-005).
- `data`: as `docling`, with the GII's 139 economy-profile pages written from WIPO's data file
  (`econ.ingest.gii`) instead of parsed.
- `docling-tables`: as `docling`, with each profile page's table kept (Docling labels them a document
  index, which the parse leaves out; amendment 1 of the grid).
- `drop`: as `docling`, without the economy-profile pages.

The WIPO test set (eval/testset/wipo-v1.yaml) has two kinds of gold. A `quote` is verbatim text, located in
each variant's own canonical text (a variant that rewrites some pages moves the offsets after them). A
`facts` gold is a figure from an economy profile: a chunk covers it when it is from that document (and
page, if given) and its text holds every listed string, so one gold scores a parsed table and its written
form alike.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from econ import config
from econ.evalr import metrics
from econ.evalr.testset import KINDS, _norm_map, split_of
from econ.kb import embed, enrich
from econ.kb.bm25 import BM25
from econ.kb.chunk import Element, _compact_table, boilerplate, canonical_text, chunk_document, place
from econ.manifest import StageError
from econ.retrieval.search import fuse
from econ.textcheck import normalise

GII = "wipo-gii-2026"
VARIANTS = ("ipa-only", "docling", "docling-prefix", "docling-tables", "data", "drop")
DEPTH = 50


def is_wipo(doc_id: str) -> bool:
    return doc_id.startswith("wipo-")


def _raw_rows(doc_id: str) -> list[dict]:
    p = config.path(config.pipeline().paths.library) / "elements" / f"{doc_id}.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _elements(rows: list[dict]) -> list[Element]:
    els = [Element(r["seq"], r["label"], r["text"], r["page"], r["boxes"], r.get("level")) for r in rows]
    for e in els:
        if e.label == "table":
            e.text = _compact_table(e.text)
    return place(els)


_gii_cache: dict = {}


def gii_profiles() -> tuple[dict[int, list[dict]], set[int]]:
    """The data file's elements for each profile page, and the set of profile pages."""
    if not _gii_cache:
        from econ.ingest import gii

        src = config.sources()
        data = src.data_for(GII)[0]
        raw = config.path(config.pipeline().paths.raw)
        wb = gii.load(raw / data.raw_name)
        pages = gii.profile_pages(raw / src.by_id()[GII].raw_name, wb.economies, range(1, 400))
        sizes = json.loads((config.path(config.pipeline().paths.library) / "parse.json").read_text())[GII]
        sizes = {int(k): v for k, v in sizes["pages"].items()}
        _gii_cache["rep"] = gii.profile_elements(wb, pages, sizes, GII, src.by_id()[GII].year)
        _gii_cache["pages"] = set(pages.values())
    return _gii_cache["rep"], _gii_cache["pages"]


def gii_docling_rows(index_tables: bool = False) -> list[dict]:
    """The GII's elements as Docling parsed them, from the parse cache: the library's copy has the profile
    pages written from the data file since the grid chose that (D-033). With `index_tables`, each profile
    page's table is kept (Docling labels them a document index, which the parse leaves out)."""
    from docling_core.types.doc import DoclingDocument

    from econ.ingest.parse import elements_from_docling
    from econ.manifest import sha256_file

    pdf = config.path(config.pipeline().paths.raw) / config.sources().by_id()[GII].raw_name
    cache = config.path("data/parsed") / f"{GII}.{sha256_file(pdf)[:16]}.text.json"
    if not cache.exists():
        raise StageError("no Docling cache for the GII; run `econ parse --only wipo-gii-2026`", item=GII)
    pages = gii_profiles()[1] if index_tables else None
    doc = DoclingDocument.model_validate(json.loads(cache.read_text()))
    return elements_from_docling(doc, GII, False, index_tables_on=pages)[0]


def corpus(variant: str) -> dict[str, list[Element]]:
    """Every document's elements under a variant."""
    if variant not in VARIANTS:
        raise ValueError(variant)
    out = {}
    for d in sorted(config.sources().documents, key=lambda d: d.doc_id):
        if is_wipo(d.doc_id) and variant == "ipa-only":
            continue
        rows = _raw_rows(d.doc_id)
        if d.doc_id == GII:
            rows = gii_docling_rows(index_tables=variant == "docling-tables")
        if d.doc_id == GII and variant in ("data", "drop"):
            from econ.ingest import gii

            rep, pages = gii_profiles()
            if variant == "data":
                rows = gii.overlay(rows, rep)
            else:
                rows = [r for r in rows if r["page"] not in pages]
        out[d.doc_id] = _elements(rows)
    return out


def chunks(variant: str) -> tuple[list[dict], dict[str, list[Element]]]:
    st = config.pipeline().chunking.strategies[config.pipeline().chunking.adopted]
    docs = config.sources().by_id()
    els = corpus(variant)
    skip = boilerplate(els)
    rows = []
    for doc_id, e in els.items():
        s = (
            st.model_copy(update={"prefix": "title+section"})
            if variant == "docling-prefix" and is_wipo(doc_id)
            else st
        )
        rows.extend(chunk_document(docs[doc_id], s, e, skip))
    return rows, els


NOTES_V1 = "S384-noprefix-nocite.luna-enrich-v1"  # the notes grid wipo-v1 was measured with


def indexed_texts(rows: list[dict], notes_name: str = NOTES_V1) -> list[str]:
    """What both lanes index: the chunk's context note, if the notes file has one, then the embed_text.
    wipo-v1 used the IP Australia notes only; wipo-v1b (D-034) the notes that cover the WIPO passages."""
    notes = enrich.load(notes_name)
    return [
        (notes[c["chunk_id"]] + "\n\n" + c["embed_text"]).strip()
        if notes.get(c["chunk_id"])
        else c["embed_text"]
        for c in rows
    ]


# --- the WIPO test set ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpanGold:
    doc_id: str
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class FactGold:
    doc_id: str
    page: int | None
    contains: tuple[str, ...]

    def covered_by(self, chunk: dict) -> bool:
        if chunk["doc_id"] != self.doc_id or (self.page is not None and self.page not in chunk["pages"]):
            return False
        text = _squash(chunk["text"])
        return all(_squash(s) in text for s in self.contains)


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", normalise(s)).strip().lower()


@dataclass(frozen=True)
class Need:
    id: str
    kind: str
    question: str
    golds: tuple[tuple, ...]
    split: str
    profile: bool  # a figure from an economy profile


def _locate(norms: dict[str, tuple[str, list[int]]], doc_id: str, quote: str) -> list[SpanGold]:
    q = re.sub(r"\s+", " ", normalise(quote)).strip()
    out = []
    for d in [doc_id, *[x for x in sorted(norms) if x != doc_id]]:
        norm, idx = norms[d]
        i = norm.find(q)
        while i >= 0:
            out.append(SpanGold(d, idx[i], idx[i + len(q) - 1] + 1, quote))
            i = norm.find(q, i + 1)
    return out


def load(els: dict[str, list[Element]], path: Path | None = None) -> list[Need]:
    """The WIPO set, located in one variant's texts. A quote must be found in its own document in the
    `docling` corpus (the set is written from it); a variant that removed it simply can't find it."""
    path = path or config.path("eval/testset/wipo-v1.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    known = set(config.sources().by_id())
    norms = {d: _norm_map(canonical_text(e)) for d, e in els.items()}
    needs, seen = [], set()
    for n in data["needs"]:
        if n["id"] in seen:
            raise StageError("duplicate need id", item=n["id"])
        seen.add(n["id"])
        if n["kind"] not in KINDS:
            raise StageError(f"unknown kind {n['kind']!r}", item=n["id"])
        golds, profile = [], False
        for g in n["gold"]:
            alts: list = []
            for a in [g, *g.get("alt", [])]:
                if a["doc_id"] not in known:
                    raise StageError(f"unknown doc_id {a['doc_id']!r}", item=n["id"])
                if "facts" in a:
                    profile = True
                    alts.append(FactGold(a["doc_id"], a.get("page"), tuple(a["facts"])))
                else:
                    if len(a["quote"].split()) < 8:
                        raise StageError("gold quote shorter than 8 words", item=n["id"])
                    if a["doc_id"] in els:
                        alts.extend(x for x in _locate(norms, a["doc_id"], a["quote"]) if x not in alts)
            golds.append(tuple(alts))
        needs.append(
            Need(n["id"], n["kind"], n["question"].strip(), tuple(golds), split_of(n["id"]), profile)
        )
    return needs


def check_set(path: Path | None = None) -> dict:
    """Every quote is found in its document as parsed, and every facts gold is covered by some element
    text of the `docling` corpus or the `data` corpus: the set is valid before any ranking."""
    out = {"needs": 0, "missing": []}
    els = corpus("docling")
    norms = {d: _norm_map(canonical_text(e))[0] for d, e in els.items() if is_wipo(d)}
    data = yaml.safe_load((path or config.path("eval/testset/wipo-v1.yaml")).read_text(encoding="utf-8"))
    for n in data["needs"]:
        out["needs"] += 1
        for g in n["gold"]:
            for a in [g, *g.get("alt", [])]:
                q = re.sub(r"\s+", " ", normalise(a.get("quote", ""))).strip()
                if "quote" in a and q not in norms[a["doc_id"]]:
                    out["missing"].append((n["id"], a["quote"][:60]))
    return out


# --- ranking and scoring -------------------------------------------------------------------------------


class Variant:
    def __init__(self, name: str, embedder: str | None = None, notes: str = NOTES_V1):
        self.name = name
        self.embedder = embedder or config.pipeline().embedding.adopted
        self.chunks, self.els = chunks(name)
        texts = indexed_texts(self.chunks, notes)
        self.bm25 = BM25.build(texts)
        self.vecs = self._encode(texts)

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Embedded in groups that variants share (all IP Australia chunks; each WIPO document), so the
        per-list cache in econ.kb.embed serves every variant that leaves a group unchanged."""
        groups: dict[str, list[int]] = {}
        for i, c in enumerate(self.chunks):
            groups.setdefault(c["doc_id"] if is_wipo(c["doc_id"]) else "ipa", []).append(i)
        out = None
        for rows in groups.values():
            v = embed.encode(self.embedder, [texts[i] for i in rows], kind="doc")
            if out is None:
                out = np.zeros((len(texts), v.shape[1]), dtype=np.float32)
            out[rows] = v
        return out

    def rank(self, questions: list[str]) -> list[list[int]]:
        r = config.pipeline().retrieval
        qv = embed.encode(self.embedder, questions, kind="query")
        out = []
        for i, q in enumerate(questions):
            hits = fuse(
                self.vecs @ qv[i],
                self.bm25.scores(q),
                k=DEPTH,
                lane_depth=r.lane_depth,
                fusion=r.fusion,
                alpha=r.alpha,
                rrf_k=r.rrf_k,
            )
            out.append([h.row for h in hits])
        return out

    def score(self, needs) -> list[dict]:
        ranks = self.rank([n.question for n in needs])
        rows = []
        for n, rk in zip(needs, ranks, strict=True):
            ranked = [self.chunks[i] for i in rk]
            m = metrics.per_need(ranked, n.golds)
            top10 = ranked[:10]
            rows.append(
                {
                    "need": n.id,
                    "split": n.split,
                    "kind": n.kind,
                    "profile": getattr(n, "profile", False),
                    **m,
                    "wipo_share@10": sum(is_wipo(c["doc_id"]) for c in top10) / max(1, len(top10)),
                    "top": [c["chunk_id"] for c in top10],
                }
            )
        return rows

    def stats(self) -> dict:
        w = [c for c in self.chunks if is_wipo(c["doc_id"])]
        toks = sorted(c["tokens"] for c in w) or [0]
        return {
            "chunks": len(self.chunks),
            "wipo_chunks": len(w),
            "wipo_median_tokens": toks[len(toks) // 2],
            "gii_chunks": sum(c["doc_id"] == GII for c in w),
            "dim": int(self.vecs.shape[1]),
            "norm_min": float(np.linalg.norm(self.vecs, axis=1).min()),
        }


# --- the grid run and its report -----------------------------------------------------------------------

METRICS = ["ndcg@10", "recall@4k_tok", "recall@20", "mrr@10", "wipo_share@10"]


def _mean(rows: list[dict], m: str, **where) -> float:
    return metrics.mean([r[m] for r in rows if all(r[k] == v for k, v in where.items())])


def run_grid(run, grid: str = "wipo-v1") -> dict:
    """Score every variant on the IP Australia silver set and the WIPO set; write rows and the report."""
    import time

    from econ.evalr import testset
    from econ.evalr.retrieval import grid_spec, save

    spec = grid_spec(grid)
    ipa = testset.load()
    results: dict[str, dict[str, list[dict]]] = {}
    stats: dict[str, dict] = {}
    notes = spec.get("notes", NOTES_V1)
    for name in spec["variants"]:
        t0 = time.time()
        v = Variant(name, notes=notes)
        results[name] = {"ipa": v.score(ipa)}
        if name != "ipa-only":
            results[name]["wipo"] = v.score(load(v.els))
        for s, rows in results[name].items():
            save(grid, "variants", f"{name}.{s}", rows)
        stats[name] = {**v.stats(), "seconds": round(time.time() - t0, 1)}
        print(f"[{grid}] {name}: {stats[name]}", flush=True)
        del v
    choice = choose(results)
    out = config.path(config.pipeline().paths.reports) / f"retrieval-{grid}.md"
    from econ.manifest import write_json_atomic, write_text_atomic

    write_json_atomic(config.path("eval/runs") / grid / "choice.json", choice)
    write_text_atomic(out, render(grid, spec, results, stats, choice))
    run.add_output(out)
    run.counts.update(
        variants=len(results),
        ipa_needs=len(ipa),
        wipo_needs=len(next(r["wipo"] for r in results.values() if "wipo" in r)),
    )
    return choice


def choose(results: dict) -> dict:
    """The grid's two rules, applied as written in eval/grids/wipo-v1.yaml."""
    cands = [n for n in ("docling", "docling-prefix", "docling-tables", "data", "drop") if n in results]
    order = {n: i for i, n in enumerate(["docling", "drop", "docling-prefix", "docling-tables", "data"])}
    dev = {n: _mean(results[n]["wipo"], "ndcg@10", split="dev") for n in cands}
    prof = {n: _mean(results[n]["wipo"], "ndcg@10", split="dev", profile=True) for n in cands}
    nonprof = {n: _mean(results[n]["wipo"], "ndcg@10", split="dev", profile=False) for n in cands}
    best = max(dev.values())
    tied = [n for n in cands if best - dev[n] <= 0.005]
    chosen = min(tied, key=order.get)
    # A profile-only change is preferred to docling when better on the dev profile needs and not worse on
    # the dev non-profile needs by more than 0.02; of two such, the better on the profile needs.
    if chosen == "docling":
        better = [
            n
            for n in ("data", "drop", "docling-tables")
            if n in results
            if prof[n] > prof["docling"] and nonprof["docling"] - nonprof[n] <= 0.02
        ]
        if better:
            chosen = max(better, key=lambda n: (prof[n], -order[n]))
    base = [r["ndcg@10"] for r in results["ipa-only"]["ipa"]]
    mixed = [r["ndcg@10"] for r in results[chosen]["ipa"]]
    c = metrics.compare(base, mixed)
    one_index = c["diff"] >= -0.02 and c["ci"][0] > -0.04
    return {
        "chosen": chosen,
        "dev_ndcg@10": dev,
        "dev_profile_ndcg@10": prof,
        "dev_nonprofile_ndcg@10": nonprof,
        "ipa_ndcg@10_vs_ipa_only": c,
        "one_index": one_index,
    }


def render(grid: str, spec: dict, results: dict, stats: dict, choice: dict) -> str:
    f = lambda x: f"{x:.3f}"  # noqa: E731
    names = list(results)
    wipo_names = [n for n in names if "wipo" in results[n]]
    ipa_rows = results["ipa-only"]["ipa"]
    w0 = results[wipo_names[0]]["wipo"]
    L = [
        f"# Retrieval measurement: the WIPO documents ({grid})",
        "",
        f"Grid `{grid}` (eval/grids/{grid}.yaml). Generated by `econ eval-wipo`. No model calls: the adopted "
        "chunking, embedder and hybrid search, the question as the only query. Context notes: "
        f"`{spec.get('notes', NOTES_V1)}`"
        + (
            " (IP Australia chunks only; WIPO figures are a floor)."
            if spec.get("notes", NOTES_V1) == NOTES_V1
            else "."
        ),
        "",
        f"Needs: {len(ipa_rows)} IP Australia (silver-v1), {len(w0)} WIPO (wipo-v1: "
        f"{sum(r['split'] == 'dev' for r in w0)} dev, {sum(r['split'] == 'test' for r in w0)} test; "
        f"{sum(r['profile'] for r in w0)} economy-profile figures).",
        "",
        f"**Rule 2 (profiles and prefix), chosen on WIPO dev: `{choice['chosen']}`.**",
        "",
        f"**Rule 1 (one index): {'met' if choice['one_index'] else 'not met'}.** IP Australia ndcg@10, "
        f"`{choice['chosen']}` against `ipa-only`: {choice['ipa_ndcg@10_vs_ipa_only']['diff']:+.3f} "
        f"[{choice['ipa_ndcg@10_vs_ipa_only']['ci'][0]:+.3f}, {choice['ipa_ndcg@10_vs_ipa_only']['ci'][1]:+.3f}].",
        "",
        "## The rules (fixed before any number)",
        "",
        f"1. {spec['rules']['one_index']}",
        f"2. {spec['rules']['profiles']}",
        "",
        "## WIPO needs",
        "",
        "| Variant | ndcg@10 dev | ndcg@10 test | profile figures (all) | other needs (all) | recall@4k_tok (all) | recall@20 (all) |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in wipo_names:
        r = results[n]["wipo"]
        L.append(
            f"| `{n}`{' **(chosen)**' if n == choice['chosen'] else ''} | {f(_mean(r, 'ndcg@10', split='dev'))} | "
            f"{f(_mean(r, 'ndcg@10', split='test'))} | {f(_mean(r, 'ndcg@10', profile=True))} | "
            f"{f(_mean(r, 'ndcg@10', profile=False))} | {f(_mean(r, 'recall@4k_tok'))} | {f(_mean(r, 'recall@20'))} |"
        )
    if "docling" in results:
        L += [
            "",
            "Test against `docling` (paired, all WIPO test needs, ndcg@10):",
            "",
            "| Variant | Difference | 95% CI | p |",
            "|---|---|---|---|",
        ]
        base_t = [r["ndcg@10"] for r in results["docling"]["wipo"] if r["split"] == "test"]
        for n in wipo_names:
            if n == "docling":
                continue
            c = metrics.compare(base_t, [r["ndcg@10"] for r in results[n]["wipo"] if r["split"] == "test"])
            L.append(f"| `{n}` | {c['diff']:+.3f} | [{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}] | {c['p']:.3f} |")
    L += [
        "",
        "## IP Australia needs (silver-v1, all 114)",
        "",
        "| Variant | ndcg@10 | vs ipa-only | 95% CI | recall@4k_tok | recall@20 | WIPO share of top 10 |",
        "|---|---|---|---|---|---|---|",
    ]
    base_i = [r["ndcg@10"] for r in ipa_rows]
    for n in names:
        r = results[n]["ipa"]
        if n == "ipa-only":
            cmp = "baseline | "
        else:
            c = metrics.compare(base_i, [x["ndcg@10"] for x in r])
            cmp = f"{c['diff']:+.3f} | [{c['ci'][0]:+.3f}, {c['ci'][1]:+.3f}]"
        L.append(
            f"| `{n}` | {f(_mean(r, 'ndcg@10'))} | {cmp} | {f(_mean(r, 'recall@4k_tok'))} | "
            f"{f(_mean(r, 'recall@20'))} | {f(_mean(r, 'wipo_share@10'))} |"
        )
    kinds = sorted({r["kind"] for r in w0})
    L += [
        "",
        "## WIPO ndcg@10 by document and kind (dev and test together)",
        "",
        "| Variant | " + " | ".join(f"{k} (n={sum(r['kind'] == k for r in w0)})" for k in kinds) + " |",
        "|---|" + "---|" * len(kinds),
    ]
    for n in wipo_names:
        r = results[n]["wipo"]
        L.append(f"| `{n}` | " + " | ".join(f(_mean(r, "ndcg@10", kind=k)) for k in kinds) + " |")
    prefixes = sorted({r["need"].split("-")[0] for r in w0})
    L += ["", "| Variant | " + " | ".join(prefixes) + " |", "|---|" + "---|" * len(prefixes)]
    for n in wipo_names:
        r = results[n]["wipo"]
        L.append(
            f"| `{n}` | "
            + " | ".join(
                f(metrics.mean([x["ndcg@10"] for x in r if x["need"].split("-")[0] == p])) for p in prefixes
            )
            + " |"
        )
    L += [
        "",
        "## Runs",
        "",
        "| Variant | Chunks | WIPO chunks | GII chunks | WIPO median tokens | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for n in names:
        s = stats[n]
        L.append(
            f"| `{n}` | {s['chunks']} | {s['wipo_chunks']} | {s['gii_chunks']} | {s['wipo_median_tokens']} | {s['seconds']} |"
        )
    L += [
        "",
        "## How to read these numbers",
        "",
        "- A `quote` gold is covered by a chunk holding at least half its characters; a `facts` gold (an economy-profile "
        "figure) by a chunk from that page holding the indicator's name and its value.",
        "- `wipo_share@10`: the share of WIPO passages in a need's top 10. For IP Australia needs it shows the "
        "crowding that rule 1 guards against.",
        "- One author (Claude) wrote both test sets from passages, so they measure finding the passage a question "
        "was written from. The WIPO set is small (see the counts above): treat differences under about 0.05 as ties.",
    ]
    return "\n".join(L) + "\n"
