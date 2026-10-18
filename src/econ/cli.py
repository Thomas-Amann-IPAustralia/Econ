"""The `econ` command line. One command per stage, plus measurement, the service and tools."""

from __future__ import annotations

import sys
from functools import wraps

import typer

from econ import config
from econ.manifest import StageError, run

app = typer.Typer(add_completion=False, no_args_is_help=True, help="IP Australia economics knowledge base.")


def loud(fn):
    """Fail loudly: exit code 2, a one-line cause, the item's id and the report to read."""

    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except StageError as e:
            msg = f"error: {e.cause}"
            if e.item:
                msg += f" [item: {e.item}]"
            if e.report:
                msg += f" (see {e.report})"
            typer.echo(msg, err=True)
            sys.exit(2)

    return wrapper


def _hash() -> str:
    return config.config_hash(config.sources(), config.pipeline())


@app.command()
@loud
def fetch() -> None:
    """Copy the corpus from R2 into data/raw and reconcile it with config/sources.yaml."""
    from econ.ingest.fetch import fetch as _fetch

    with run("fetch", _hash()) as r:
        _fetch(r)
    typer.echo(f"fetch passed: {r.counts}")


@app.command()
@loud
def sweep() -> None:
    """Security sweep of the raw PDFs (active content, text checks)."""
    from econ.ingest.sweep import sweep as _sweep

    with run("sweep", _hash()) as r:
        _sweep(r)
    typer.echo(f"sweep passed: {r.counts}")


@app.command()
@loud
def parse(
    workers: int = typer.Option(1, help="Parallel worker processes."),
    only: list[str] = typer.Option(None, help="Parse only these doc_ids (for probes; not a full run)."),
) -> None:
    """Parse PDFs into layout elements with page and box provenance (Docling)."""
    from econ.ingest.parse import parse as _parse

    with run("parse", _hash(), workers=workers, only=only or []) as r:
        _parse(r, workers=workers, only=only)
    typer.echo(f"parse passed: {r.counts}")


@app.command()
@loud
def chunk(
    strategy: list[str] = typer.Option(None, help="Strategies to build (default: all in config)."),
) -> None:
    """Chunk the parsed elements under one or more strategies into library/chunks/<strategy>.jsonl."""
    import json as _json

    from econ.kb.chunk import boilerplate, chunk_document, load_elements
    from econ.manifest import require_upstream, write_text_atomic

    cfg = config.pipeline().chunking
    names = strategy or list(cfg.strategies)
    with run("chunk", _hash(), strategies=names) as r:
        r.upstream["parse"] = require_upstream("parse")["run_id"]
        lib = config.path(config.pipeline().paths.library)
        docs = sorted(config.sources().documents, key=lambda d: d.doc_id)
        elements = {d.doc_id: load_elements(d.doc_id) for d in docs}
        skip = boilerplate(elements)
        r.counts["boilerplate_paragraphs"] = len(skip)
        for name in names:
            st = cfg.strategies[name]
            rows = []
            for doc in docs:
                rows.extend(chunk_document(doc, st, load_elements(doc.doc_id), skip))
            over = [c["chunk_id"] for c in rows if c["tokens"] > st.max_tokens]
            if over:
                raise StageError(f"{len(over)} chunk(s) over the {st.max_tokens}-token budget", item=over[0])
            out = lib / "chunks" / f"{name}.jsonl"
            write_text_atomic(
                out, "".join(_json.dumps(c, sort_keys=True, ensure_ascii=False) + "\n" for c in rows)
            )
            r.add_output(out)
            toks = sorted(c["tokens"] for c in rows)
            r.counts[name] = {
                "chunks": len(rows),
                "median_tokens": toks[len(toks) // 2],
                "max_tokens": toks[-1],
                "total_tokens": sum(toks),
            }
    typer.echo(f"chunk passed: {r.counts}")


@app.command("eval-retrieval")
@loud
def eval_retrieval(
    stage: str = typer.Option(..., help="chunking | embedders | fusion"),
    grid: str = typer.Option("retrieval-v1", help="Grid file under eval/grids/."),
) -> None:
    """Run one stage of a committed retrieval grid on the silver test set (no API calls)."""
    from econ.evalr.stages import run_stage

    with run("eval-retrieval", _hash(), grid=grid, stage=stage) as r:
        choice = run_stage(r, grid, stage)
    typer.echo(
        f"{stage}: chosen {choice['chosen']} (dev {choice['primary']} = {choice['dev'][choice['chosen']]:.3f})"
    )


@app.command("eval-retrieval-v2")
@loud
def eval_retrieval_v2(
    stage: str = typer.Option("stage1", help="stage1 | stage2 | final | depth"),
    judgments: str = typer.Option("judged-v1", help="Judgments file under eval/judgments/."),
) -> None:
    """Grid retrieval-v2 on the judged test set (no API calls; reads cached plans, notes and reranker scores)."""
    from econ.evalr import grid2, judged
    from econ.manifest import write_text_atomic

    with run("eval-retrieval-v2", _hash(), stage=stage, judgments=judgments) as r:
        needs = judged.load()
        r.counts["needs"] = len(needs)
        if stage == "stage1":
            res = grid2.run_stage1(needs, judgments)
            out = config.path("reports/retrieval-v2-stage1.md")
            write_text_atomic(out, grid2.render_stage1(res, needs))
            r.add_output(out)
            ch = res["choice"]
            r.counts.update(settings=len(res["settings"]), chosen=ch["chosen"])
        elif stage in ("stage2", "final", "depth"):
            res = {"stage2": grid2.run_stage2, "final": grid2.run_final, "depth": grid2.run_depth}[stage](
                needs, judgments
            )
            out = config.path(
                "reports/retrieval-depth.md" if stage == "depth" else f"reports/retrieval-v2-{stage}.md"
            )
            write_text_atomic(out, res["report"])
            r.add_output(out)
            ch = res["choice"]
        else:
            raise StageError(f"unknown stage {stage}")
    if stage == "depth":
        typer.echo(f"depth: {ch['needs']} needs at depths {ch['depths']}; report {out}")
        return
    typer.echo(f"{stage}: chosen {ch['chosen']} ({ch['primary']} dev {ch['dev'][ch['chosen']]:.3f})")


@app.command("eval-filter")
@loud
def eval_filter(
    judgments: str = typer.Option("judged-v1", help="Judgments file under eval/judgments/."),
    probe: int = typer.Option(12, help="Needs whose filter step is re-run at the standard tier for latency."),
) -> None:
    """Grid retrieval-filter: a small model rates the 60-passage context (paid, cached, metered calls)."""
    from econ.evalr import filter as filt
    from econ.evalr import judged
    from econ.manifest import write_text_atomic

    with run("eval-filter", _hash(), judgments=judgments, probe=probe) as r:
        res = filt.run(judged.load(), judgments, probe=probe)
        out = config.path("reports/retrieval-filter.md")
        write_text_atomic(out, res["report"])
        r.add_output(out)
        r.counts.update({k: v for k, v in res["summary"].items() if k != "latency_standard_s"})
    s = res["summary"]
    typer.echo(
        f"filter: {s['needs']} needs, {s['failed_needs']} failed, kappa {s['kappa']:.2f}; report {out}"
    )


@app.command("eval-answers-v2")
@loud
def eval_answers_v2(
    step: str = typer.Option(..., help="answers | blind | pairwise | report (in that order)"),
) -> None:
    """Grid answers-v2: the relevance filter's 20 passages against the adopted 20, end to end."""
    from econ.evalr import answers2

    steps = {
        "answers": answers2.step_answers,
        "blind": answers2.step_blind,
        "pairwise": answers2.step_pairwise,
        "report": answers2.step_report,
    }
    if step not in steps:
        raise StageError(f"unknown step {step}")
    with run("eval-answers-v2", _hash(), step=step) as r:
        res = steps[step]()
        r.counts.update({k: v for k, v in res.items() if isinstance(v, int | float | bool | str)})
    typer.echo(f"answers-v2 {step}: {res}")


@app.command()
@loud
def index(
    model_dir: str = typer.Option("", help="Directory with the model's ONNX files (fetched if empty)."),
    strategy: str = typer.Option("", help="A chunking strategy other than the adopted one (a named option)."),
    embedder: str = typer.Option("", help="An embedder other than the adopted one (a named option)."),
    out: str = typer.Option(
        "library/index", help="Where to write; only the adopted build belongs in library/index."
    ),
) -> None:
    """Build the serving index from the adopted strategy and embedder (or named ones), via ONNX."""
    import json as _json

    import numpy as np

    from econ.embedder import OnnxEmbedder, fetch_model
    from econ.evalr.retrieval import load_chunks
    from econ.kb.bm25 import BM25
    from econ.manifest import require_upstream, sha256_file, write_json_atomic, write_text_atomic

    cfg = config.pipeline()
    strategy, key = strategy or cfg.chunking.adopted, embedder or cfg.embedding.adopted
    if not strategy or not key:
        raise StageError("chunking.adopted and embedding.adopted must be set in config/pipeline.yaml")
    if out == "library/index" and (strategy != cfg.chunking.adopted or key != cfg.embedding.adopted):
        raise StageError("a non-adopted build must go elsewhere: pass --out")
    with run("index", _hash(), strategy=strategy, embedder=key, out=out) as r:
        r.upstream["chunk"] = require_upstream("chunk")["run_id"]
        from pathlib import Path

        mdir = Path(model_dir) if model_dir else config.path(cfg.paths.models) / "onnx" / key
        if not (mdir / "model.json").exists():
            fetch_model(key, mdir)
        emb = OnnxEmbedder(key, mdir, threads=4)
        chunks = load_chunks(strategy)
        texts = [c["embed_text"] for c in chunks]
        enrichment = cfg.retrieval.enrichment
        notes_sha = None
        if enrichment:
            # D-013: each chunk's context note goes in front of its text, for both lanes; it is stored
            # beside the chunk as `context_note` and never shown as evidence.
            from econ.kb import enrich

            notes = enrich.load(enrichment)
            missing = [c["chunk_id"] for c in chunks if c["chunk_id"] not in notes]
            if missing:
                raise StageError(
                    f"{len(missing)} chunk(s) have no context note in {enrichment}", item=missing[0]
                )
            for c in chunks:
                c["context_note"] = notes[c["chunk_id"]]
            texts = [(c["context_note"] + "\n\n" + c["embed_text"]).strip() for c in chunks]
            notes_sha = sha256_file(config.path("library/enrich") / f"{enrichment}.jsonl")[:16]
        vecs = emb.encode(texts, kind="doc")
        out = config.path(out)
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / "vectors.f16.npy", vecs.astype(np.float16))
        bm = BM25.build(texts)
        bm.save(out / "bm25.npz")
        write_text_atomic(
            out / "chunks.jsonl",
            "".join(_json.dumps(c, sort_keys=True, ensure_ascii=False) + "\n" for c in chunks),
        )
        parse = _json.loads((config.path(cfg.paths.library) / "parse.json").read_text())
        counts: dict[str, int] = {}
        for c in chunks:
            counts[c["doc_id"]] = counts.get(c["doc_id"], 0) + 1
        docs = {}
        for d in sorted(config.sources().documents, key=lambda d: d.doc_id):
            p = parse[d.doc_id]
            docs[d.doc_id] = {
                "doc_id": d.doc_id,
                "title": d.title,
                "year": d.year,
                "series": d.series,
                "authors": d.authors,
                "url": d.url,
                "note": d.note,
                "publisher": config.sources().publisher,
                "licence": p.get("licence"),
                "page_count": p["page_count"],
                "pages": p["pages"],
                "ocr": p["ocr"],
                "chunks": counts.get(d.doc_id, 0),
                "source_sha256": p["source_sha256"],
            }
        write_json_atomic(out / "docs.json", docs)
        files = ["chunks.jsonl", "vectors.f16.npy", "bm25.npz", "bm25.vocab.json", "docs.json"]
        meta = {
            "strategy": strategy,
            "embedder": key,
            "hf_id": emb.spec.hf_id,
            "revision": emb.spec.revision,
            "onnx_sha256": emb.meta["onnx_sha256"],
            "dim": int(vecs.shape[1]),
            "chunks": len(chunks),
            "enrichment": enrichment,
            "enrichment_sha256": notes_sha,
            "built_from": r.upstream["chunk"],
            "files": {f: sha256_file(out / f)[:16] for f in files},
        }
        write_json_atomic(out / "index.json", meta)
        for f in [*files, "index.json"]:
            r.add_output(out / f)
        r.counts.update(chunks=len(chunks), dim=int(vecs.shape[1]))
    typer.echo(f"index passed: {r.counts}")


@app.command("verify-embedder")
@loud
def verify_embedder(
    url: str = typer.Option(
        "", help="Also check a live embedder (e.g. the Cloud Run URL); token from EMBEDDER_TOKEN."
    ),
    sample: int = typer.Option(300, help="Chunks to compare."),
) -> None:
    """Show that the serving path ranks as measured: ONNX vs sentence-transformers, float16 vs float32,
    and optionally the live service vs local ONNX. Writes reports/embedder-verification.md."""
    import os

    import numpy as np

    from econ.embedder import OnnxEmbedder
    from econ.evalr import metrics, testset
    from econ.kb import embed
    from econ.manifest import write_text_atomic
    from econ.retrieval.index import EmbedderClient, Index

    idx = Index()
    key = idx.meta["embedder"]
    with run("verify-embedder", _hash(), url=url, sample=sample) as r:
        needs = testset.load()
        qs = [n.question for n in needs]
        onnx = OnnxEmbedder(key, config.path(config.pipeline().paths.models) / "onnx" / key, threads=4)
        q_onnx = onnx.encode(qs, kind="query")
        q_st = embed.encode(key, qs, kind="query")
        rows = list(range(0, len(idx.chunks), max(1, len(idx.chunks) // sample)))[:sample]
        texts = [idx.indexed_text(i) for i in rows]
        d_st = embed.encode(key, texts, kind="doc", cache=False)
        cos_q = (q_onnx * q_st).sum(1)
        cos_d = (idx.vecs[rows] * d_st).sum(1)

        def ranked(qv):
            from econ.retrieval.search import fuse

            rc = config.pipeline().retrieval
            out = []
            for i, n in enumerate(needs):
                hits = fuse(
                    idx.vecs @ qv[i],
                    idx.bm25.scores(n.question),
                    k=50,
                    lane_depth=rc.lane_depth,
                    fusion=rc.fusion,
                    alpha=rc.alpha,
                    rrf_k=rc.rrf_k,
                )
                out.append([h.row for h in hits])
            return out

        r_onnx, r_st = ranked(q_onnx), ranked(q_st)
        overlap = [len(set(a[:10]) & set(b[:10])) / 10 for a, b in zip(r_onnx, r_st, strict=True)]
        nd_onnx = [
            metrics.per_need([idx.chunks[i] for i in rk], n.golds)["ndcg@10"]
            for rk, n in zip(r_onnx, needs, strict=True)
        ]
        nd_st = [
            metrics.per_need([idx.chunks[i] for i in rk], n.golds)["ndcg@10"]
            for rk, n in zip(r_st, needs, strict=True)
        ]
        lines = [
            "# Embedder verification",
            "",
            f"Model `{key}` ({idx.meta['hf_id']} @ {idx.meta['revision'][:12]}), ONNX sha256 "
            f"`{idx.meta['onnx_sha256'][:16]}`. Index: {len(idx.chunks)} chunks, float16. "
            f"Generated by `econ verify-embedder`.",
            "",
            "| Check | Result |",
            "|---|---|",
            f"| Query vectors, ONNX vs sentence-transformers ({len(qs)} test questions): cosine | "
            f"min {cos_q.min():.5f}, mean {cos_q.mean():.5f} |",
            f"| Chunk vectors, index (ONNX, float16) vs sentence-transformers (float32), {len(rows)} chunks: cosine | "
            f"min {cos_d.min():.5f}, mean {cos_d.mean():.5f} |",
            f"| Top-10 overlap, ONNX vs sentence-transformers queries (hybrid lane) | mean {np.mean(overlap):.3f}, "
            f"min {min(overlap):.1f} |",
            f"| ndcg@10, all needs: ONNX queries / sentence-transformers queries | {np.mean(nd_onnx):.4f} / "
            f"{np.mean(nd_st):.4f} |",
        ]
        if url:
            os.environ["EMBEDDER_URL"] = url
            client = EmbedderClient()
            t0 = __import__("time").time()
            live = client.embed(qs[:32], key, idx.vecs.shape[1])
            secs = __import__("time").time() - t0
            cos_live = (live * q_onnx[:32]).sum(1)
            lines.append(
                f"| Live service vs local ONNX (32 questions): cosine | min {cos_live.min():.5f} "
                f"({secs:.2f}s for the batch, including any cold start) |"
            )
            r.counts["live_min_cosine"] = float(cos_live.min())
        out = config.path(config.pipeline().paths.reports) / "embedder-verification.md"
        write_text_atomic(out, "\n".join(lines) + "\n")
        r.add_output(out)
        r.counts.update(
            query_min_cosine=float(cos_q.min()),
            doc_min_cosine=float(cos_d.min()),
            top10_overlap=float(np.mean(overlap)),
        )
    typer.echo("\n".join(lines))


@app.command("verify-search")
@loud
def verify_search(
    plans: str = typer.Option("luna-plan-v2", help="Cached plans standing in for the live planner."),
    setting: str = typer.Option(
        "", help="The measured setting to match (default: grid retrieval-v2's choice)."
    ),
) -> None:
    """Show that the served search reproduces the measured one (SOP §19): the serving index (ONNX, float16),
    ONNX query vectors and the service's query rule, fed by cached plans, against the measurement path,
    on every judged need. Writes reports/search-verification.md."""
    import json as _json

    import numpy as np

    from econ.answer.pipeline import context_queries
    from econ.evalr import grid2, judged
    from econ.evalr import plans as plans_mod
    from econ.manifest import write_text_atomic
    from econ.retrieval.index import Index

    idx = Index()
    key = idx.meta["embedder"]
    setting = (
        setting or _json.loads(config.path("eval/runs/retrieval-v2/final/choice.json").read_text())["chosen"]
    )
    with run("verify-search", _hash(), plans=plans, setting=setting) as r:
        needs = judged.load()
        grades = grid2.grades_by_need("judged-v1")
        emb = _LocalEmbedder(key)
        cached = plans_mod.load(plans)
        a_cfg = config.service().answer
        s = grid2.named(setting)
        o10, o20, nd_serve, nd_meas = [], [], [], []
        for n in needs:
            p = cached[n.id]
            if setting.startswith("raw"):
                qs = [n.question, *context_queries(n.context, a_cfg.max_queries - 1)]
            else:
                qs = list(p["queries"])[: a_cfg.max_queries]
                if a_cfg.plan_keeps_question:
                    qs = [p["standalone"], *[q for q in qs if q != p["standalone"]]]
            ranked, _ = idx.search(qs, emb.embed(qs, key, idx.vecs.shape[1]))
            served = [idx.chunks[x.row]["chunk_id"] for x in idx.context(ranked)]
            measured = [grid2.systems.chunks()[x]["chunk_id"] for x in grid2.context_rows(s, n)]
            o10.append(len(set(served[:10]) & set(measured[:10])) / 10)
            o20.append(len(set(served[:20]) & set(measured[:20])) / 20)
            rows = {c["chunk_id"]: i for i, c in enumerate(grid2.systems.chunks())}
            nd_serve.append(grid2.per_need([rows[c] for c in served], n, grades.get(n.id, {}))["ndcg@10"])
            nd_meas.append(grid2.per_need([rows[c] for c in measured], n, grades.get(n.id, {}))["ndcg@10"])
        lines = [
            "# Search verification",
            "",
            f"Serving index `{idx.meta['strategy']}` + `{idx.meta['embedder']}` (ONNX `{idx.meta['onnx_sha256'][:16]}`, "
            f"float16), context notes `{idx.meta.get('enrichment')}`; query rule from config/service.yaml "
            f"(plan_keeps_question={a_cfg.plan_keeps_question}), fed by the cached plans `{plans}`; against the "
            f"measured setting `{setting}` (sentence-transformers, float32). {len(needs)} judged needs. "
            "Generated by `econ verify-search`.",
            "",
            "| Check | Result |",
            "|---|---|",
            f"| Top-10 overlap, served vs measured context | mean {np.mean(o10):.3f}, min {min(o10):.1f} |",
            f"| Top-20 overlap | mean {np.mean(o20):.3f}, min {min(o20):.2f} |",
            f"| ndcg@10 (judged), served / measured | {np.mean(nd_serve):.4f} / {np.mean(nd_meas):.4f} |",
            f"| Needs whose top 10 differ at all | {sum(1 for x in o10 if x < 1)} of {len(needs)} |",
        ]
        out = config.path(config.pipeline().paths.reports) / "search-verification.md"
        write_text_atomic(out, "\n".join(lines) + "\n")
        r.add_output(out)
        r.counts.update(top10_overlap=float(np.mean(o10)), top20_overlap=float(np.mean(o20)))
    typer.echo("\n".join(lines))


@app.command("lock-prompts")
def lock_prompts() -> None:
    """Record the current prompts and schemas in prompts/versions.lock (for a new prompt version only)."""
    import json as _json

    from econ.answer.prompts import PROMPTS, current_lock

    lock = current_lock()
    (PROMPTS / "versions.lock").write_text(_json.dumps(lock, indent=2, sort_keys=True) + "\n")
    typer.echo(f"locked: {', '.join(lock)}")


@app.command()
def serve(port: int = 8787, reload: bool = False) -> None:
    """Run the API service locally (uses EMBEDDER_URL and model keys from the environment, if set)."""
    import uvicorn

    uvicorn.run("econ.service.app:app", host="127.0.0.1", port=port, reload=reload)


@app.command()
@loud
def ask(
    question: str,
    context: str = typer.Option("", help="Material to compare against the knowledge base (never cited)."),
    confirm: bool = typer.Option(False, help="Allow paid model calls. Without it, evidence-only."),
    local_embedder: bool = typer.Option(True, help="Embed the query with the local ONNX model."),
) -> None:
    """Ask one question from the command line and print every event."""
    import json as _json

    from econ.answer import pipeline
    from econ.answer.providers import configured
    from econ.retrieval.index import EmbedderClient, Index

    idx = Index()
    emb = EmbedderClient()
    if local_embedder and not emb.configured:
        emb = _LocalEmbedder(idx.meta["embedder"])
    found = configured() if confirm else None
    svc = pipeline.Services(
        index=idx, embedder=emb, model=found[0] if found else None, provider=found[1] if found else None
    )
    for e in pipeline.run(pipeline.Request(question=question, context=context), svc):
        if e["event"] == "retrieval":
            typer.echo(f"-- retrieval ({e['dense']}): queries {e['queries']}")
            for ev in e["evidence"]:
                typer.echo(
                    f"  [{ev['n']:2d}] {ev['chunk_id']:36s} {ev['year']} p{ev['pages']} "
                    f"{' > '.join(ev['section'])[:60]}"
                )
        else:
            typer.echo(_json.dumps(e, ensure_ascii=False, default=str)[:2000])


class _LocalEmbedder:
    """The EmbedderClient interface over the local ONNX model, for the CLI and tests on real data."""

    def __init__(self, key: str):
        from econ.embedder import OnnxEmbedder

        self.model = OnnxEmbedder(key, config.path(config.pipeline().paths.models) / "onnx" / key)
        self.configured, self.warm, self.health = True, True, {"status": "local"}

    def embed(self, texts, expect_model, expect_dim):
        return self.model.encode(texts, kind="query")

    def rerank(self, query, passages, expect_model):
        from econ.reranker import OnnxReranker

        if getattr(self, "rr", None) is None:
            self.rr = OnnxReranker(
                expect_model, config.path(config.pipeline().paths.models) / "rerank-onnx" / expect_model
            )
        return self.rr.score(query, passages)

    def ping(self):
        return self.health


if __name__ == "__main__":
    app()
