"""Stage `parse`: PDFs to layout elements with page and box provenance, using Docling.

Each document becomes library/elements/<doc_id>.jsonl: one row per body element in reading order, with
its label, text, page and bounding box (PDF points, top-left origin). Page furniture (running headers,
footers, page numbers), the table of contents and figure interiors are left out; captions are kept.
Documents whose text layer is empty are OCR'd at a higher render scale (D-002); their garbled elements
are then re-read from their own boxes (`econ.ingest.reocr`, D-022), against the vocabulary of the
text-layer documents, and library/reocr.json records every attempt.

The Docling result per document is cached in data/parsed/ under the input's hash, so a run can resume.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from econ import config, textcheck
from econ.manifest import Run, StageError, require_upstream, sha256_file, write_json_atomic, write_text_atomic

KEEP = {
    "title",
    "section_header",
    "text",
    "paragraph",
    "list_item",
    "caption",
    "footnote",
    "table",
    "formula",
    "code",
    "reference",
}
NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")

_converters: dict = {}


def _converter(ocr: bool):
    if ocr in _converters:
        return _converters[ocr]
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    cfg = config.pipeline().parse
    opts = PdfPipelineOptions(
        do_ocr=ocr,
        do_table_structure=cfg.table_structure,
        accelerator_options=AcceleratorOptions(num_threads=cfg.threads, device="cpu"),
    )
    if ocr:
        opts.images_scale = cfg.ocr_scale
        opts.ocr_options = RapidOcrOptions(force_full_page_ocr=True)
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    _converters[ocr] = conv
    return conv


def heading_level(text: str, docling_level: int | None) -> int:
    """Numbered headings ('2.1 Data') take their depth from the number; others keep Docling's level."""
    m = NUMBERED.match(text)
    if m:
        return min(m.group(1).count(".") + 1, 4)
    return max(1, int(docling_level or 1))


def elements_from_docling(
    doc, doc_id: str, ocr: bool, index_tables_on: set[int] | None = None
) -> tuple[list[dict], dict]:
    """`index_tables_on`: pages on which a table Docling labels a document index (a table of contents,
    left out by default) is kept as a table: the GII's economy profiles are labelled so (D-033)."""
    from docling_core.types.doc import TableItem

    rows: list[dict] = []
    pages = {
        int(no): {"width": round(p.size.width, 2), "height": round(p.size.height, 2)}
        for no, p in doc.pages.items()
    }
    for item, _level in doc.iterate_items():
        label = str(getattr(item, "label", "")).split(".")[-1].lower()
        if (
            label == "document_index"
            and index_tables_on
            and isinstance(item, TableItem)
            and getattr(item, "prov", None)
            and item.prov[0].page_no in index_tables_on
        ):
            label = "table"
        if label not in KEEP or not getattr(item, "prov", None):
            continue
        if isinstance(item, TableItem):
            text = item.export_to_markdown(doc=doc).strip()
        else:
            text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        # Docling's table markdown already starts with its caption; drop the separate caption element.
        if label == "caption" and rows and rows[-1]["label"] == "table" and text in rows[-1]["text"]:
            continue
        boxes = []
        for prov in item.prov:
            h = pages[prov.page_no]["height"]
            bb = prov.bbox.to_top_left_origin(page_height=h)
            boxes.append(
                {
                    "page": prov.page_no,
                    "bbox": [round(bb.l, 1), round(bb.t, 1), round(bb.r, 1), round(bb.b, 1)],
                }
            )
        row = {
            "doc_id": doc_id,
            "seq": len(rows),
            "label": label,
            "text": text,
            "page": boxes[0]["page"],
            "boxes": boxes,
            "ocr": ocr,
        }
        if label in ("section_header", "title"):
            row["level"] = 0 if label == "title" else heading_level(text, getattr(item, "level", None))
        rows.append(row)
    return rows, pages


def _parse_one(args: tuple[str, str, bool, str]) -> tuple[str, dict]:
    doc_id, pdf_path, ocr, cache_path = args
    started = time.time()
    conv = _converter(ocr)
    batch = config.pipeline().parse.batch_pages
    pages = _page_count(pdf_path)
    if batch and pages > batch:
        # A long document in page batches: Docling holds every page's images until the end, and the
        # 348-page GII report ran out of memory whole (D-033). Pages keep their absolute numbers.
        # Each batch is cached as it finishes, so an interrupted run resumes where it stopped.
        from docling_core.types.doc import DoclingDocument

        # A batch already cached from a run with another batch size is reused as it is.
        size = config.pipeline().parse.batch_size or batch
        parts, statuses, a = [], set(), 1
        while a <= pages:
            done = sorted(Path(cache_path).parent.glob(f"{Path(cache_path).name}.pages-{a}-*"))
            if done:
                part = done[0]
                parts.append(DoclingDocument.model_validate(json.loads(part.read_text())))
                statuses.add("cached")
                a = int(part.name.rsplit("-", 1)[1]) + 1
                continue
            b = min(a + size - 1, pages)
            t0 = time.time()
            res = conv.convert(pdf_path, page_range=(a, b))
            write_text_atomic(Path(f"{cache_path}.pages-{a}-{b}"), json.dumps(res.document.export_to_dict()))
            parts.append(res.document)
            statuses.add(str(res.status))
            print(f"parsed {doc_id} pages {a}-{b} in {time.time() - t0:.1f}s", flush=True)
            a = b + 1
        document = DoclingDocument.concatenate(parts)
        status = ",".join(sorted(statuses))
    else:
        res = conv.convert(pdf_path)
        document, status = res.document, str(res.status)
    payload = document.export_to_dict()
    write_text_atomic(Path(cache_path), json.dumps(payload))
    return doc_id, {"seconds": round(time.time() - started, 1), "status": status}


def _page_count(pdf_path: str) -> int:
    import pypdfium2 as pdfium  # build extra

    return len(pdfium.PdfDocument(pdf_path))


def _catalogue(p: Path) -> dict:
    """parse.json as the stage builds it: page numbers as integers, so they sort as numbers when written."""
    if not p.exists():
        return {}
    cat = json.loads(p.read_text())
    for info in cat.values():
        info["pages"] = {int(k): v for k, v in info["pages"].items()}
    return cat


def parse(run: Run, *, workers: int = 1, only: list[str] | None = None) -> None:
    from docling_core.types.doc import DoclingDocument

    sweep_m = require_upstream("sweep")
    run.upstream["sweep"] = sweep_m["run_id"]
    lib = config.path(config.pipeline().paths.library)
    sweep_report = json.loads((lib / "sweep.json").read_text())
    raw = config.path(config.pipeline().paths.raw)
    cache = config.path("data/parsed")
    cache.mkdir(parents=True, exist_ok=True)
    cfg = config.pipeline().parse

    docs = sorted(config.sources().documents, key=lambda d: d.doc_id)
    if only:
        docs = [d for d in docs if d.doc_id in only]
    jobs, plan = [], {}
    for d in docs:
        pdf = raw / f"{d.doc_id}.pdf"
        digest = sha256_file(pdf)
        info = sweep_report[d.doc_id]
        if info["quarantined"]:
            raise StageError("document is quarantined by the sweep", item=d.doc_id)
        ocr = info["image_only_pages"] >= cfg.ocr_page_share * info["pages"]
        cpath = cache / f"{d.doc_id}.{digest[:16]}.{'ocr' if ocr else 'text'}.json"
        plan[d.doc_id] = (pdf, cpath, ocr)
        run.add_input(pdf)
        if not cpath.exists():
            jobs.append((d.doc_id, str(pdf), ocr, str(cpath)))

    timings = {}
    # OCR documents last: they are the slowest, and a failure there shouldn't hold up the rest.
    jobs.sort(key=lambda j: (j[2], j[0]))
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for doc_id, info in pool.map(_parse_one, jobs):
                timings[doc_id] = info
                print(f"parsed {doc_id} in {info['seconds']}s", flush=True)
    else:
        for job in jobs:
            doc_id, info = _parse_one(job)
            timings[doc_id] = info
            print(f"parsed {doc_id} in {info['seconds']}s", flush=True)

    out_dir = lib / "elements"
    out_dir.mkdir(parents=True, exist_ok=True)
    parsed = {}
    for d in docs:
        pdf, cpath, ocr = plan[d.doc_id]
        ddoc = DoclingDocument.model_validate(json.loads(cpath.read_text()))
        parsed[d.doc_id] = elements_from_docling(ddoc, d.doc_id, ocr)
        if not parsed[d.doc_id][0]:
            raise StageError("no body text extracted", item=d.doc_id)

    # Re-read the OCR documents' garbled elements (D-022), against the text-layer documents' vocabulary:
    # this run's, and for a partial run the committed elements of the text-layer documents it left out.
    reocr_report = {}
    if cfg.reocr and any(plan[d][2] for d in parsed):
        from econ.ingest import reocr

        texts = [r["text"] for d, (rows, _) in parsed.items() if not plan[d][2] for r in rows]
        prev = _catalogue(lib / "parse.json")
        for doc_id, info in prev.items():
            if doc_id not in parsed and not info["ocr"] and (out_dir / f"{doc_id}.jsonl").exists():
                texts += [json.loads(line)["text"] for line in (out_dir / f"{doc_id}.jsonl").open()]
        vocab = reocr.vocabulary(texts)
        for doc_id, (rows, _) in parsed.items():
            if plan[doc_id][2]:
                reader = reocr.BoxReader(str(plan[doc_id][0]), cfg.reocr_scales, cfg.reocr_pads)
                vision = (
                    reocr.VisionReader(str(plan[doc_id][0]), cfg.reocr_model) if cfg.reocr_model else None
                )
                reocr_report[doc_id] = reocr.repair(
                    rows,
                    vocab,
                    reader,
                    variants=len(reader.variants),
                    min_agreement=cfg.reocr_agreement,
                    fallback=vision,
                    fallback_name=cfg.reocr_model or "",
                )

    catalogue = {}
    n_el, findings = 0, []
    for d in docs:
        pdf, cpath, ocr = plan[d.doc_id]
        rows, pages = parsed[d.doc_id]
        for r in rows:
            for f in textcheck.scan(r["text"]):
                if f.severity == "high":
                    findings.append({"doc_id": d.doc_id, "seq": r["seq"], **f.as_dict()})
        body = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)
        out = out_dir / f"{d.doc_id}.jsonl"
        write_text_atomic(out, body)
        run.add_output(out)
        labels = {}
        for r in rows:
            labels[r["label"]] = labels.get(r["label"], 0) + 1
        body_text = " ".join(r["text"] for r in rows)
        licence = (
            "CC BY 4.0" if re.search(r"Creative Commons Attribution 4\.0|CC BY 4\.0", body_text) else None
        )
        if licence is None:
            run.warn(f"{d.doc_id}: no licence statement found in the extracted text")
        catalogue[d.doc_id] = {
            "licence": licence,
            "pages": pages,
            "page_count": len(pages),
            "ocr": ocr,
            "elements": len(rows),
            "labels": dict(sorted(labels.items())),
            "source_sha256": sha256_file(pdf),
        }
        n_el += len(rows)

    out = lib / "parse.json"
    if only and out.exists():
        # A partial run updates its own documents and keeps the rest of the catalogue as it was.
        catalogue = {**_catalogue(out), **catalogue}
    write_json_atomic(out, catalogue)
    run.add_output(out)
    if reocr_report:
        rp = lib / "reocr.json"
        old = json.loads(rp.read_text()) if (only and rp.exists()) else {}
        write_json_atomic(rp, dict(sorted({**old, **reocr_report}.items())))
        run.add_output(rp)
        tried = [e for rep in reocr_report.values() for e in rep]
        run.counts.update(reocr_garbled=len(tried), reocr_repaired=sum(e["repaired"] for e in tried))
    run.counts.update(
        documents=len(docs), parsed_now=len(timings), elements=n_el, text_findings=len(findings)
    )
    run.params["timings"] = timings
    if findings:
        run.params["findings"] = findings[:50]
        raise StageError(
            f"{len(findings)} high-severity text finding(s) in extracted text",
            item=f"{findings[0]['doc_id']}#{findings[0]['seq']}",
        )
