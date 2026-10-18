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


@app.command()
@loud
def index(
    model_dir: str = typer.Option(
        "", help="Directory with the adopted model's ONNX files (fetched if empty)."
    ),
) -> None:
    """Build the serving index (library/index/) from the adopted strategy and embedder, via ONNX."""
    import json as _json

    import numpy as np

    from econ.embedder import OnnxEmbedder, fetch_model
    from econ.evalr.retrieval import load_chunks
    from econ.kb.bm25 import BM25
    from econ.manifest import require_upstream, sha256_file, write_json_atomic, write_text_atomic

    cfg = config.pipeline()
    strategy, key = cfg.chunking.adopted, cfg.embedding.adopted
    if not strategy or not key:
        raise StageError("chunking.adopted and embedding.adopted must be set in config/pipeline.yaml")
    with run("index", _hash(), strategy=strategy, embedder=key) as r:
        r.upstream["chunk"] = require_upstream("chunk")["run_id"]
        from pathlib import Path

        mdir = Path(model_dir) if model_dir else config.path(cfg.paths.models) / "onnx" / key
        if not (mdir / "model.json").exists():
            fetch_model(key, mdir)
        emb = OnnxEmbedder(key, mdir, threads=4)
        chunks = load_chunks(strategy)
        vecs = emb.encode([c["embed_text"] for c in chunks], kind="doc")
        out = config.path("library/index")
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / "vectors.f16.npy", vecs.astype(np.float16))
        bm = BM25.build([c["embed_text"] for c in chunks])
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
            "built_from": r.upstream["chunk"],
            "files": {f: sha256_file(out / f)[:16] for f in files},
        }
        write_json_atomic(out / "index.json", meta)
        for f in [*files, "index.json"]:
            r.add_output(out / f)
        r.counts.update(chunks=len(chunks), dim=int(vecs.shape[1]))
    typer.echo(f"index passed: {r.counts}")


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

    def ping(self):
        return self.health


if __name__ == "__main__":
    app()
